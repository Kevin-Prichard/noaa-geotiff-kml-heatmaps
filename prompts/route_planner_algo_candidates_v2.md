# Recommended Route-Planning Algorithms for UAV Mission Planning

## Context Summary

Drawn from `route_planner.md`, `route_planner_critique.md`, `heatmap.py`, and `roads_near_me.py`, the system is an offline-and-live mission planner for a **fixed-wing pusher-prop UAV with VTOL capability**, operating at up to 50 kts on battery power. The early experiments establish the data stack clearly: rasterio for reading geotiff/grib layers (terrain, weather, solar luminance), geopandas with FlatGeobuf for OSM-derived map features (roads, land plots, buildings), and UTM reprojection for metric distance calculations. The output is a **priority-sorted set of waypoint graphs** — multiple feasible route alternatives ranked by cost — for human review before mission commit.

---

## Vehicle and Mission Constraint Summary

| Constraint | Planning implication |
|---|---|
| Fixed-wing during cruise | Minimum turn radius applies; cannot hover; kinematic trajectory model needed |
| VTOL take-off/landing | Origin/destination can be any accessible flat surface; not restricted to runways |
| 50 kts max airspeed (~25 m/s) | Turn radius at max speed ≈ 150–300 m depending on bank angle; must be modelled |
| Battery-powered | Energy is the primary cost dimension; sudden direction changes waste battery; smooth acceleration required |
| Mission leg length cap | Hard range constraint per leg; multi-leg assembly required |
| Solar recharge layovers | Recharge stops must be on sun-exposed, flat, accessible terrain (roads/fields from OSM) |
| Dynamic replanning | Must re-route mid-mission when updated weather geotiffs change the cost landscape |
| Non-uniform cost field | Cost at each point derived from multiple raster layers (terrain, wind, population density, land type) — disqualifies algorithms requiring uniform-cost grids |
| Multiple output alternatives | Algorithm must produce a ranked set, not a single path |

---

## Recommended Algorithm Stack

Algorithms are grouped by the **role they play** in the overall system. Several are intended to run in parallel as separate `RoutePlanner` subclasses.

---

### Tier 1 — Essential (implement first)

#### 1. A\* with geodesic heuristic
- **Role:** Primary single-mission grid planner. Baseline against which all others are compared.
- **Why:** `networkx.astar_path()` directly satisfies the `step() -> tuple[int, Graph]` interface. The admissible heuristic is the geodesic (great-circle) distance between candidate and goal, making it both correct and fast. Non-uniform cost fields are natively supported via edge weights.
- **New consideration:** For this UAV, the edge weight between two grid nodes should encode the **energy cost** of the transition, not just the geographic distance. This is straightforward to inject through A*'s weight function. Wind vectors from grib U10/V10 components make headwind/tailwind legs noticeably different in cost.
- **Reference:** Hart, Nilsson & Raphael (1968). *IEEE Transactions on Systems Science and Cybernetics*.
- **Library:** `networkx` (built-in, `networkx.astar_path`). Grid construction via `numpy` + `rasterio`.
- **Priority:** Essential.

---

#### 2. ARA\* — Anytime Repairing A\*
- **Role:** Produces the **priority-sorted set of alternatives** the prompt requires. Finds an initial (possibly suboptimal) solution quickly by inflating the heuristic by factor `ε`, then iteratively reduces `ε` and repairs the solution, yielding a sequence of complete paths of monotonically decreasing cost.
- **Why this system specifically:** The stated output is "a priority-sorted set of mission waypoint graphs, with cost the sort key." ARA\* generates exactly this: a sequence of complete paths each provably within `ε × optimal_cost`. No other algorithm in this list produces multiple complete alternative paths as a natural by-product of a single run. The solutions at different `ε` values serve as the human-reviewable alternatives — a plan that costs 15% more than optimal but avoids a particular urban area or turbulence cell may be operationally preferred.
- **Reference:** Likhachev, Gordon & Thrun (2003). *Advances in Neural Information Processing Systems 16*.
- **Library:** No dedicated PyPI package; ARA\* is a thin wrapper over A\* (~50 additional lines). Add `ε`-inflation to the heuristic call, decrement `ε` after each complete path is found, record each solution.
- **Priority:** Essential — directly addresses the multi-alternative ranked output requirement.

---

#### 3. D\* Lite
- **Role:** Dynamic replanning. When updated weather geotiffs arrive mid-mission, D\* Lite repairs only the invalidated portion of the existing plan rather than replanning from scratch.
- **Why:** Operates on the same grid/graph as A\*, so the two share all infrastructure. D\* Lite is provably optimal and produces the same path as A\* on a static graph. Changed pixels in an updated weather raster translate directly to changed edge weights in the planning graph — exactly D\* Lite's intended use case. Critical for a 50-kt aircraft that has limited time to wait for a full replan.
- **Reference:** Koenig & Likhachev (2002). *Proceedings of AAAI-02*.
- **Library:** `PythonRobotics` (MIT-licensed, actively maintained on GitHub, [DStarLite reference](https://github.com/AtsushiSakai/PythonRobotics/tree/master/PathPlanning/DStarLite)). ~200 lines of Python. No PyPI package.
- **Priority:** Essential given the dynamic weather replanning requirement.

---

### Tier 2 — Strongly Recommended

#### 4. Theta\* — Any-Angle A\*
- **Role:** Replaces A\* as the primary grid planner for production use, producing far fewer and more natural waypoints via any-angle path shortcutting (line-of-sight shortcuts from grandparent to child node).
- **Why this system specifically:** A fixed-wing aircraft cannot execute grid-staircase turns. Theta\* keeps the grid-based cost field but produces waypoints connected at arbitrary angles — reducing waypoint count by 60–80% on open terrain. Fewer waypoints means fewer banked turns, lower energy cost, and simpler human review. **Bonus:** the line-of-sight check naturally embeds terrain clearance — if the LOS ray crosses a DEM cell whose height exceeds the UAV's planned altitude, the shortcut is rejected, giving obstacle avoidance as a side-effect of the LOS test.
- **Reference:** Nash, Daniel, Koenig & Felner (2007). *AAAI-07*. Lazy Theta\* (deferred LOS checks): Nash et al. (2010), *AAAI-10*.
- **Library:** `python-pathfinding` (PyPI, actively maintained). `PythonRobotics` also has a standalone implementation.
- **Priority:** High — implement as a drop-in upgrade to A\* once the grid pipeline is stable.

---

#### 5. RRT\* with Dubins Steering — Optimal Rapidly-exploring Random Trees
- **Role:** Continuous-space planner. Operates without a pre-built grid; samples GPS coordinates directly and queries the cost function lazily per sample. Naturally extends to 3D (lat/lon/alt).
- **Why this system specifically:** The mission area may span hundreds of kilometres; materialising a dense grid up front is expensive. RRT\* discovers the route incrementally, only evaluating cost where it actually explores. With a **Dubins steering function** (see §P3 below) each tree edge is a kinematically feasible arc, respecting minimum turn radius automatically. This is the only algorithm in this list that is simultaneously continuous-space, any-angle, and kinematically constrained without the complexity of Hybrid A\*.
- **Reference:** Karaman & Frazzoli (2011). *International Journal of Robotics Research, 30*(7).
- **Library:** `rrtplanner` (PyPI, MIT licence, actively maintained). `ompl` (Python bindings) is the gold standard if a compiled C++ dependency is acceptable.
- **Priority:** High — provides the strongest paradigm contrast with grid-based methods for side-by-side comparison.

---

#### 6. Field D\* — Smooth Dynamic Replanning
- **Role:** Any-angle *and* dynamic replanning combined. Extends D\* Lite by interpolating costs *across* grid cell boundaries rather than snapping to grid nodes — producing smooth, any-angle replanned paths with no post-processing required.
- **Why this system specifically:** This is the algorithm NASA used for Mars Exploration Rover path planning — the most battle-tested planner in this list for autonomous vehicles on complex terrain. For a UAV that needs to replan smoothly around a newly reported storm cell, Field D\* is the most direct match. Unlike D\* Lite, waypoints are not anchored to grid nodes at all, eliminating staircase turns entirely from replanned paths.
- **Reference:** Ferguson & Stentz (2005). *Proceedings of ICRA-05*. Extended: Ferguson & Stentz (2006). *Journal of Field Robotics*.
- **Library:** `PythonRobotics` Python port; standalone [field_d_star](https://github.com/wuyuanmm/field_d_star) on GitHub. Expect ~300 lines of Python. No PyPI package.
- **Priority:** High if smooth dynamic replanning is a Day-1 requirement; otherwise implement after D\* Lite is working and validated.

---

### Tier 3 — Recommended for Specific Needs

#### 7. ANYA — Optimal Any-Angle Search on Grids
- **Role:** Drop-in replacement for Theta\* providing *provably optimal* any-angle paths on grids with non-uniform costs. Theta\* is near-optimal (~0.1% longer than optimal due to node anchoring); ANYA eliminates this gap entirely.
- **Why this system specifically:** When battery margin is tight and the cost field is accurately modelled, the ~0.1% suboptimality of Theta\* translates directly to wasted battery. ANYA finds the true shortest any-angle path on a non-uniform cost grid.
- **Reference:** Harabor & Grastien (2013). *IJCAI-13*. Expanded: Harabor, Grastien, Öz & Aksakalli (2016). *Artificial Intelligence Journal*.
- **Library:** Reference implementation in Java by the original authors. Python port: [anyangle](https://github.com/EpicDavi/anyangle) on GitHub (functional, not PyPI-packaged). Expect to implement from the paper for a production-quality Python version.
- **Priority:** Medium — implement if Theta\* path quality proves insufficient, or as a research comparison point.

---

#### 8. PRM — Probabilistic Roadmap Method
- **Role:** Multi-query roadmap planner. Builds a reusable navigation graph over the mission area once (offline), then answers many routing queries cheaply by running A\* on the pre-built roadmap. Best suited to repeated operations over the same geographic region.
- **Why this system specifically:** As missions accumulate over the same terrain, a PRM roadmap can be extended with new samples rather than rebuilt. Solar recharge stop candidates (flat sunny fields, road verges from OSM) can be injected as mandatory nodes in the roadmap — making multi-mission assembly with solar layovers a straightforward shortest-path problem on a pre-built graph.
- **Reference:** Kavraki, Svestka, Latombe & Overmars (1996). *IEEE Transactions on Robotics and Automation*.
- **Library:** `ompl` (Python bindings). Also implementable from scratch in ~100 lines using `scipy.spatial.cKDTree` for nearest-neighbour queries and `networkx` for the roadmap graph.
- **Priority:** Medium-high — most valuable once single-mission planning is working and multi-mission leg assembly is the next objective.

---

#### 9. Energy-Aware A\* (E-A\*)
- **Role:** A\* variant where the edge cost is an explicit **energy consumption model** rather than a proxy. Accounts for airspeed, wind vector (from grib U10/V10), altitude change (from DEM), and Dubins-arc turn cost.
- **Why this system specifically:** Battery capacity is the hard constraint on mission range. A standard geographic-distance cost is a poor proxy — a headwind leg costs 2–3× more energy than a tailwind leg of the same distance. An accurate energy model enables the planner to predict remaining charge at each waypoint, enforce the leg-length cap, and identify optimal recharge timing. The solar luminance geotiff feeds the recharge rate model at stop nodes.
- **Reference:** Morbidi, Cano, Le Berre & Doisy (2016). *IEEE Robotics and Automation Letters* for battery-discharge UAV models. Algorithmic structure is standard A\* — the energy model is the novel contribution.
- **Library:** Built on `networkx.astar_path` with a custom weight function. No separate package needed; uses `pygrib`/`rasterio` for wind and solar data, already in `requirements.txt`.
- **Priority:** High — this is the correct formulation of the cost function for this vehicle. The energy model should be implemented before any planner, since it is shared across all of them.

---

### Tier 4 — Specialised / Deferred

#### 10. Hybrid A\* with Reeds-Shepp Curves
- **Role:** Full kinodynamic planner in SE(2)/SE(3) state space (position + heading ± pitch), enforcing turn radius at every expansion step.
- **Why deferred:** Most valuable for fixed-wing cruise where every waypoint transition must be flyable. However, since the vehicle has VTOL capability, kinematic constraints only apply during cruise, not at take-off, landing, or recharge stops. The added complexity of Hybrid A\* is only justified once Dubins-path edge costs (§P3) prove insufficient — which they likely will not for the initial implementation.
- **Reference:** Dolgov, Thrun, Montemerlo & Diebel (2010). *The International Journal of Robotics Research*.
- **Library:** `reeds-shepp` (PyPI) for curve primitives. No aerial-specific maintained pure-Python implementation exists.
- **Priority:** Deferred — revisit after Dubins-path edge costs are validated in A\*/RRT\*.

---

#### 11. Multi-Objective A\* (NAMOA\* / BOA\*)
- **Role:** Pareto-optimal path planning across two or more cost dimensions simultaneously (e.g., minimise energy *and* minimise time *and* minimise population overflight risk). Returns a frontier of non-dominated solutions rather than a single path.
- **Why deferred:** The human review phase in the prompt is essentially selecting from a Pareto frontier. NAMOA\* formalises this rigorously — but ARA\* with a single energy cost function covers the practical need first. Multi-objective is a refinement once the single-objective pipeline is validated.
- **Reference:** Mandow & de la Cruz (2005). *IJCAI-05*. BOA\*: Ulloa, Baier & Hernández (2020). *Artificial Intelligence Journal*.
- **Library:** `pymoo` (PyPI, well-maintained) for general multi-objective optimisation as a wrapper.
- **Priority:** Deferred.

---

## Supporting Primitives (Required Regardless of Planner)

These are architectural dependencies shared by all planners above. They should be implemented before any planner subclass.

### P1. Cost Field Builder
Converts multi-layer raster inputs (terrain DEM, wind grib U10/V10, population geotiff, land-use geotiff, solar luminance geotiff) into a unified cost callable `cost(lat, lon) -> float` over the mission bounding box. Implemented with `rasterio` (windowed reads, reprojection to UTM), `pygrib`/`xarray` (grib/grib2 parsing), and `numpy` (layer arithmetic and normalisation). **This component is the most important single piece** — all planners consume its output and its accuracy determines route quality.

### P2. OSM Feature Querier
Returns land-use, road, and building features at or near a given point or polygon. Implemented with `geopandas.read_file(path, bbox=area)` on `.fgb` files (as demonstrated in `roads_near_me.py`), with UTM reprojection for metric buffering. Feeds the cost function: farmland → cost reduction; urban areas → cost increase; road verges → candidate recharge stop locations.

### P3. Dubins Edge Weighter
Computes the energy-weighted Dubins path length between two `(lat, lon, heading)` states. Uses the `dubins` PyPI package (C-extension, actively maintained). Wrap it with the energy model from §9 to produce a physically meaningful scalar edge cost. The Dubins path length can replace Euclidean distance as the A\* edge weight, naturally penalising sharp turns by making them more expensive than shallow arcs. For VTOL transitions at origin/destination, substitute a straight-line segment.

### P4. Path Smoother / Waypoint Reducer
Post-processes any grid-path output (A\*, D\* Lite, Theta\*) through B-spline smoothing and Ramer-Douglas-Peucker simplification to reduce waypoint count and ensure heading continuity between waypoints. `scipy.interpolate.BSpline` or `shapely.simplify()` followed by Dubins-arc interpolation between simplified nodes. Required for all grid-based planners to produce flyable trajectories.

### P5. Solar Recharge Stop Selector
Given a set of candidate stopping points (road verges and open fields from OSM), scores each by: solar luminance at that location (from solar geotiff), time of day, surface slope (from DEM), and proximity to the planned route. Outputs a ranked list of recharge stop candidates for injection as forced waypoints or PRM roadmap nodes.

---

## Higher-Level Planning: Multi-Mission Leg Assembly

The single-mission path planners above plan one leg at a time. Assembling legs into a complete multi-mission sequence with solar recharge intervals is a distinct, higher-level problem best modelled as a two-level graph:

1. **Low level:** Each planner (A\*, Theta\*, RRT\*) plans the minimum-energy path between two points, subject to the range/battery cap.
2. **High level:** Build a directed graph where nodes are the origin, destination, and all viable recharge stops (from P5). Each edge represents a single low-level mission leg; edge weight is the low-level plan's total energy cost. Dijkstra's or A\* on this high-level graph gives the optimal sequence of legs and recharge stops.

This two-level structure (leg planner + sequencer) cleanly separates the geometric path problem from the logistics problem and allows each level to be extended independently.

**Reference:** For energy-constrained multi-stop UAV routing — Kivelevitch, Cohen & Kumar (2013). *Journal of Intelligent & Robotic Systems*.

---

## Consolidated Priority List

| Priority | Algorithm | Role | Library / implementation path |
|---|---|---|---|
| **P0** | **Energy cost function + Cost Field Builder** | Shared foundation for all planners | Custom; `rasterio`, `pygrib`, `numpy` |
| **P0** | **Dubins edge weighter** | Kinematic turn-cost primitive | `dubins` (PyPI) |
| **1** | **A\*** | Primary grid planner; `networkx` interface | `networkx.astar_path` |
| **1** | **ARA\*** | Multi-alternative ranked output | ~50 lines custom on top of A\* |
| **2** | **D\* Lite** | Dynamic weather replanning | `PythonRobotics` reference impl |
| **2** | **Theta\*** | Any-angle grid paths | `python-pathfinding` (PyPI) |
| **3** | **RRT\* + Dubins steering** | Continuous-space kinematic planner | `rrtplanner` (PyPI) |
| **3** | **Field D\*** | Smooth dynamic replanning | `PythonRobotics` / custom |
| **4** | **PRM + A\* on roadmap** | Multi-mission leg assembly | `ompl` or custom + `networkx` |
| **4** | **Energy-aware A\*** | Accurate range/battery planning | Custom cost fn on `networkx.astar_path` |
| **5** | **ANYA** | Provably optimal any-angle (research comparison) | Custom from paper |
| **6** | **Hybrid A\*** | Full kinodynamic planning | Deferred — validate Dubins first |
| **7** | **NAMOA\*** | Multi-objective Pareto frontier | Deferred — ARA\* covers initial need |
| **–** | **Dijkstra's** | Correctness baseline | `networkx.shortest_path` |
| **–** | **JPS** | Not recommended | Fails on non-uniform cost fields |

---

## Excluded Algorithms and Rationale

| Algorithm | Reason excluded |
|---|---|
| **Jump Point Search** | Requires uniform-cost grid; the multi-layer cost field is inherently non-uniform throughout. |
| **Bellman-Ford** | Handles negative edge weights but is always slower than Dijkstra's for non-negative weights. No negative-cost terrain in this system. |
| **Genetic / evolutionary algorithms** | Non-deterministic, no completeness guarantee, difficult to bound runtime. Poor fit for safety-critical mission planning with a hard battery constraint. |
| **Reinforcement learning planners** | Require extensive domain-specific training; outputs are not interpretable waypoint graphs; cannot provide optimality bounds. |
| **Visibility graph** | Optimal for 2D polygon obstacle environments but does not handle continuous cost fields; would require converting all raster data to discrete polygons. |
| **Bellman-Ford / SPFA** | Handles negative cycles, which cannot occur in a non-negative energy cost field. No benefit over Dijkstra's or A\*. |
