# Route Planner Algorithm Candidates — SUPERSEDED, see route_planner_algo_candidates_v2.md

## Précis

The seven candidate algorithms span roughly sixty years of path-planning research and represent three distinct paradigms. The first is **classical graph search**: Dijkstra's (1959) and A\* (1968) operate on discrete graphs or grids and guarantee optimal paths given non-negative edge weights and an admissible heuristic, respectively. They are foundational, well-understood, and directly supported by `networkx`. The second paradigm is **any-angle and optimised grid search**: Theta\* (2007) extends A\* with line-of-sight checks so that waypoints can be connected at arbitrary angles rather than snapped to grid directions; Jump Point Search (JPS, 2011) aggressively prunes symmetric paths on uniform-cost grids to achieve A\*-quality results many times faster; D\* Lite (2002) reformulates A\* to support incremental replanning when edge costs change mid-mission due to dynamic conditions such as shifting weather or newly declared no-fly zones. The third paradigm is **sampling-based and kinodynamic planning**: RRT\* (2011) grows a tree of collision-free samples in continuous space, converging asymptotically to the optimal path without requiring a grid; Hybrid A\* (2010, popularised by the DARPA Urban Challenge) discretises heading and uses vehicle motion primitives to enforce kinematic feasibility — making it the only candidate in this list that natively prevents physically unrealisable manoeuvres such as instantaneous direction reversals.

For the aerial route planner described in `route_planner.md`, the key differentiating axes are: (1) whether the algorithm operates on a pre-built discrete graph or searches a continuous space directly; (2) whether it produces smooth, any-angle paths or staircase paths along grid edges; (3) whether it can incorporate vehicle kinematic constraints; and (4) whether it supports efficient replanning when environmental data (grib/geotiff layers) changes during a planning run. No single algorithm is dominant across all four axes, which motivates running multiple planners in parallel and comparing their results — exactly the architecture the prompt describes.

All grid-based algorithms (Dijkstra, A\*, Theta\*, JPS, D\* Lite) require the mission area to be discretised into a cost-weighted grid or graph before search begins. The resolution of that grid is the most significant lever on both solution quality and runtime, and its specification was notably absent from the original prompt. RRT\* and Hybrid A\* bypass this requirement but introduce their own tuning parameters (sample count, motion primitive library). For a cost function that queries raster layers (grib/geotiff) at arbitrary GPS points, all algorithms are viable — but the grid-based ones must materialise a dense sample of those queries up front, while the sampling-based ones query lazily per node expanded.

---

## Attribute Comparison Matrix

Attributes are evaluated in the context of open-air **aerial** routing over a 2D (lat/lon) or 3D (lat/lon/alt) cost field derived from raster data.

| Attribute | Dijkstra's | A\* | Theta\* | D\* Lite | Jump Point Search | RRT\* | Hybrid A\* |
|---|---|---|---|---|---|---|---|
| **Optimal path guaranteed** | ✓ | ✓ ¹ | ~ ² | ✓ | ✓ ³ | ~ ⁴ | ~ ⁵ |
| **Complete (path found if one exists)** | ✓ | ✓ | ✓ | ✓ | ✓ | ~ ⁶ | ~ |
| **Any-angle waypoints** | ✗ | ✗ | ✓ | ✗ | ✗ ⁷ | ✓ | ✓ |
| **Dynamic replanning** | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ ⁸ | ✗ |
| **Kinematic constraints (turn radius, climb rate)** | ✗ | ✗ | ✗ | ✗ | ✗ | ~ ⁹ | ✓ |
| **Works in continuous space (no grid required)** | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ~ ¹⁰ |
| **Heuristic required** | ✗ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ |
| **Grid/graph required** | ✓ | ✓ | ✓ | ✓ | ✓ ¹¹ | ✗ | ~ |
| **Memory usage** | High | High | High | High | Medium | Medium | High |
| **Practical speed on typical mission areas** | Slow | Fast | Fast | Fast (replan) | Very Fast | Medium | Medium |
| **Produces smooth paths without post-processing** | ✗ | ✗ | ~ | ✗ | ✗ | ~ | ✓ |
| **Supports non-uniform cost fields** | ✓ | ✓ | ✓ | ✓ | ✗ ¹¹ | ✓ | ✓ |
| **3D (altitude) extension difficulty** | Low | Low | Medium | Medium | High ¹² | Low | Medium |
| **Implementation complexity** | Low | Low | Medium | High | High | High | Very High |
| **`networkx` native support** | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **Well-maintained Python library available** | ✓ | ✓ | ~ ¹³ | ~ | ~ | ✓ ¹⁴ | ~ ¹⁵ |
| **Parallelisable across multiple planners** | ✓ | ✓ | ✓ | ~ | ✓ | ✓ | ✓ |

**Key:**  ✓ = yes / strong  ✗ = no / not applicable  ~ = partial / conditional

**Footnotes:**
1. Optimal only with an admissible (non-overestimating) heuristic. Inadmissible heuristics trade optimality for speed (Weighted A\*).
2. Near-optimal: any-angle paths are shorter than grid-constrained A\* but may not be globally optimal due to discrete node anchoring.
3. Optimal on uniform-cost grids only. Non-uniform cost fields break JPS's symmetry-pruning assumptions.
4. Asymptotically optimal — converges to the optimum as sample count → ∞, but any finite run is approximate.
5. Near-optimal: optimality is sacrificed for kinematic feasibility; path cost depends on motion primitive resolution.
6. Probabilistically complete — finds a path with probability approaching 1 as samples → ∞, but may miss solutions with finite samples.
7. JPS moves in 8 grid directions only; final path is not any-angle, though a post-processing spline/string-pull can approximate it.
8. DRRT\* and Informed RRT\* extensions provide limited replanning but are not standard.
9. RRT\* can incorporate kinodynamic constraints by using a kinematic model to generate tree branches, but requires significant additional engineering.
10. Hybrid A\* uses a continuous SE(2)/SE(3) state space for expansion but typically uses a discrete grid for the heuristic lookup.
11. JPS requires a **uniform-cost** grid. Non-uniform cost fields (the primary use case here) require falling back to standard A\*.
12. 3D JPS exists but is rarely used; the symmetry-pruning rules become substantially more complex in 3D.
13. Theta\* has pure-Python implementations (e.g. `python-pathfinding`) but no dedicated, actively maintained package with broad adoption.
14. `rrtplanner` and `ompl` (via Python bindings) provide RRT\* implementations. `ompl` is the gold standard but requires a C++ build.
15. Hybrid A\* implementations exist in robotics frameworks (e.g. `rs_path` for Reeds-Shepp curves) but no aerial-specific pure-Python package is widely maintained.

---

## Per-Algorithm Pros and Cons (Aerial Routing Context)

### Dijkstra's Algorithm
**Pros**
- Trivial to implement; directly available as `networkx.shortest_path(method='dijkstra')`.
- Optimal for any non-negative cost graph — a perfect baseline for result validation.
- No heuristic to tune; behaviour is entirely determined by edge weights (cost function output).
- Serves as a correctness reference: any other planner's result should have cost ≥ Dijkstra's result on the same graph.

**Cons**
- Explores in all directions uniformly — extremely slow on large mission areas without a bounding heuristic.
- Produces staircase paths along graph edges; waypoints are locked to grid intersections.
- No kinematic awareness, no altitude reasoning, no replanning capability.
- Practical only at coarse grid resolution or over small areas; scales poorly.

**Verdict for this project:** Include as the mandatory baseline/reference implementation. Do not use as the primary production planner.

---

### A\*
**Pros**
- The industry standard for discrete path planning; directly available as `networkx.astar_path()`.
- Dramatically faster than Dijkstra's in practice due to the heuristic (geodesic distance is a natural admissible heuristic for aerial routing).
- Optimal with an admissible heuristic; near-optimal with an inadmissible one (useful for trading off speed vs. quality).
- Simple, well-documented, easy to debug, and easy to extend (e.g., to Weighted A\*, Anytime A\*).
- Pairs naturally with the `networkx.Graph` node/edge attribute model required by the prompt.

**Cons**
- Same staircase-path limitation as Dijkstra's without post-processing.
- Memory-intensive on large grids (open/closed sets can grow to O(grid size)).
- No kinematic constraints or replanning support in the base form.
- Heuristic design matters — a bad heuristic degrades to Dijkstra's speed or worse.

**Verdict for this project:** Include as the primary fast grid-search planner. Its `networkx` integration makes it the natural fit for the `step() -> tuple[int, Graph]` interface.

---

### Theta\*
**Pros**
- Produces genuinely any-angle paths by short-circuiting the line-of-sight from grandparent to child — resulting in far fewer, more natural waypoints than A\*.
- Typically yields shorter total path length than A\* on the same grid without increasing node expansion count significantly.
- For an aerial vehicle, any-angle routing is more realistic: aircraft do not fly in 8-directional hops.
- Moderate implementation complexity — it is essentially A\* with a modified `relax_edge` function.

**Cons**
- Requires a line-of-sight check (ray-cast) at every node expansion, which adds overhead and requires a binary obstacle mask in addition to the cost field.
- Still grid-based; the grid must be constructed up front.
- No kinematic constraints, no replanning.
- No `networkx`-native implementation; must be written from scratch or adapted.
- The path is not truly continuous — waypoints are still anchored to grid nodes; only the connecting edges bypass intermediate nodes.

**Verdict for this project:** Strong candidate for the "any-angle grid" planner slot. Provides meaningfully better path geometry than A\* with modest additional complexity. Recommended as the third planner if RRT\* or Hybrid A\* is out of scope.

---

### D\* Lite
**Pros**
- Specifically designed for **dynamic environments**: when edge costs change (e.g., a new no-fly zone appears, a weather cell moves), it repairs only the affected portion of the search tree rather than replanning from scratch.
- Highly relevant for aerial missions where grib data is updated during flight or no-fly zones are declared en route.
- Provably optimal; produces the same path as A\* on a static graph.
- Well-studied; the original Koenig & Likhachev (2002) paper is the definitive reference.

**Cons**
- Substantially more complex to implement than A\* — maintains two cost estimates per node (`g` and `rhs`), a priority queue with two keys, and a full predecessor/successor graph.
- Operates backwards (goal-to-start), which can be unintuitive and complicates the `step()` interface.
- Only pays off if the environment actually changes during planning; for a one-shot static plan it offers no advantage over A\* and runs slower.
- No any-angle paths, no kinematic constraints.
- The existing Python implementations are generally unmaintained; a clean implementation likely requires writing from scratch.

**Verdict for this project:** High value if dynamic replanning during a live mission is a requirement. Lower priority for an initial offline route planner. Defer to v2 unless live replanning is explicitly in scope.

---

### Jump Point Search (JPS)
**Pros**
- Achieves A\*-equivalent optimal paths on uniform-cost grids **10–100× faster** by pruning provably suboptimal symmetric paths.
- Reduces memory consumption compared to A\* by storing fewer nodes on the open set.
- Well-suited to large, open-terrain grids (exactly the aerial routing scenario) where many grid cells have the same cost.

**Cons**
- **Only correct on uniform-cost grids.** The raster cost fields in this project (grib + geotiff layers → varying cost per cell) violate JPS's uniform-cost assumption. JPS would need to fall back to A\* for non-uniform cost or use the JPS+ extension, which is significantly more complex.
- Still produces 8-directional staircase paths without post-processing.
- No kinematic constraints, no replanning, no 3D extension without significant additional work.
- Implementation is substantially more complex than A\* (the jump-point logic is non-trivial).
- No `networkx`-native support; the `python-pathfinding` library provides a basic implementation.

**Verdict for this project:** Low priority. The non-uniform cost fields (the core of the cost function feature) are precisely the condition under which JPS's main advantage disappears. If the cost field turns out to be mostly uniform with sparse obstacles, reconsider.

---

### RRT\*
**Pros**
- Works directly in **continuous space** — no grid required. Nodes are sampled at GPS coordinates and connected by straight-line or curved segments, making it a natural fit for an aerial vehicle.
- Asymptotically optimal and probabilistically complete — given enough samples, finds the optimal path through the continuous cost field.
- Natively supports 3D (lat/lon/alt) without the complexity explosion that plagues 3D grid-based methods.
- Can incorporate kinodynamic constraints by using a vehicle model to generate tree branches (kinodynamic RRT\*).
- Lazy cost evaluation: the cost function is called only for sampled points, not for every grid cell — favourable for expensive grib/geotiff queries.
- `rrtplanner` and `ompl` provide usable Python implementations.

**Cons**
- Convergence is slow in practice — many thousands of samples may be needed for high-quality paths over large mission areas.
- Non-deterministic: each run produces a different path. Reproducibility requires a fixed random seed.
- The final path from a finite RRT\* run is ragged and typically requires post-processing (path smoothing/shortcutting).
- More complex to implement from scratch than A\*-family algorithms.
- Integrating `networkx` as the graph backend is natural but requires wrapping the RRT\* tree structure.

**Verdict for this project:** Recommended as the modern/sampling-based planner. Provides the strongest contrast against grid-search methods, works well with continuous cost fields, and extends to 3D. Pair with a path-smoothing post-process step.

---

### Hybrid A\*
**Pros**
- The **only candidate** that natively enforces vehicle kinematic constraints (minimum turn radius, maximum climb/descent angle) — producing paths a real aerial vehicle can actually fly without post-processing.
- Operates in a continuous SE(2) or SE(3) state space (x, y, heading — or x, y, z, heading, pitch), producing smooth, drivable/flyable trajectories.
- Well-proven in autonomous vehicle navigation (DARPA Urban Challenge, autonomous aircraft taxiing).
- Typically uses a Reeds-Shepp or Dubins curve library for the final segment, ensuring a smooth arrival at the destination.

**Cons**
- By far the **most complex** algorithm in this list to implement correctly: requires a motion primitive library, a two-level heuristic (non-holonomic-without-obstacles + holonomic-with-obstacles), and a continuous state space manager.
- High memory and time cost due to the expanded state space (grid cells × heading bins × altitude bins).
- No `networkx`-native or widely-maintained pure-Python aerial implementation exists; most references are in C++ (ROS/OMPL).
- The `networkx` `step() -> tuple[int, Graph]` interface is an awkward fit — the Hybrid A\* state space is not a simple node graph.
- For the scope of this project (offline planning from raster data), the kinematic fidelity may be premature unless the vehicle model is well-specified.

**Verdict for this project:** Highest real-world value but highest implementation cost. Recommend deferring to a later phase once the core A\*/RRT\* pipeline is validated, or use it as the "premium" planner with a simplified Dubins-path vehicle model.

---

## Prioritisation Summary

| Priority | Algorithm | Rationale |
|---|---|---|
| 1 | **A\*** | Optimal, fast, `networkx`-native, natural fit for the `step()`/Graph interface. Essential. |
| 2 | **Dijkstra's** | Trivial to add alongside A\*; provides the correctness baseline for cost comparison. Essential. |
| 3 | **RRT\*** | Best contrast to grid methods; continuous space, lazy cost queries, 3D-ready. High value. |
| 4 | **Theta\*** | Any-angle paths; a meaningful improvement over A\* for aerial use with modest extra effort. Medium value. |
| 5 | **D\* Lite** | High value *only if* live replanning (dynamic weather/NFZ) is in scope. Otherwise defer. |
| 6 | **Hybrid A\*** | Best kinematic realism but highest implementation cost. Defer to later phase. |
| 7 | **Jump Point Search** | Speed advantage eliminated by non-uniform cost fields. Lowest priority for this use case. |

**Recommended implementation set for v1:** A\* + Dijkstra's + RRT\*, satisfying the prompt's requirement for three algorithms from different paradigms (classical uninformed, classical informed, sampling-based), covering the `networkx` graph interface, and providing meaningful side-by-side comparison material.
