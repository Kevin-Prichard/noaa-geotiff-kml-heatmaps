# Cost Functions, State Evaluation, and the Route Planning Pipeline

## The short answer

"Cost function" is actually three distinct things in this system, applied at **different stages** of the planning pipeline. Vehicle state variables (heading, airspeed, altitude, position) do not all feed into the same place:

| Input | What it is | Where it lives in the pipeline |
|---|---|---|
| `lat`, `lon` | Address into the cost field | Stage 1 — cost field lookup |
| Population, land-use, solar luminance rasters | Environmental penalties/attractors | Stage 1 — cost field |
| Wind GRIB layers | Environmental force | Stage 2 — edge energy model |
| Terrain DEM | Hard floor + soft climb cost | Stage 2 (soft) / Stage 3 (hard) |
| `altitude` | Hard terrain clearance check + climb energy | Stage 2 (soft) / Stage 3 (hard) |
| `heading` | Turn-cost input to Dubins arc | Stage 2 — kinematic edge cost |
| `airspeed` | Wind effective component, lift energy | Stage 2 — edge energy model |
| Battery state, range | Pruning criterion | Stage 3 — feasibility filter |
| No-fly zones | Binary exclusion | Stage 3 — feasibility filter |

---

## Stage 1 — Static Cost Field (raster-based, position only)

Built **once** at session initialisation (or refreshed when new weather data arrives).
Maps `(lat, lon) [, alt]` → scalar cost contribution.

```
cost_field(lat, lon) = Σ  weight_i × normalised_layer_value_i(lat, lon)

layers:
  population_density  → positive weight  (penalty: avoid people)
  land_use_farmland   → negative weight  (attractor: prefer open fields)
  noise_sensitivity   → positive weight  (penalty: avoid sensitive areas)
  solar_luminance     → negative weight  (attractor near recharge stops)
  urban_density       → positive weight  (penalty)
```

**Who builds it:** `LayerStore` + `CostField` (or `CostModel.node_cost`).
**When:** Once at startup; rebuilt if raster data changes (D* Lite then repairs the affected graph edges).
**Output:** A callable `node_cost(pt: Point) -> float` over the planning bbox.

---

## Stage 2 — State-Dependent Edge Cost (vehicle-state + physics)

Evaluated **per candidate edge** during graph expansion. This is where heading, airspeed, and altitude enter.

```
edge_cost(from_state, to_state) =
    dubins_path_energy(from_state, to_state, uav_spec)   # kinematic turn cost
  + wind_energy_cost(from_state, to_state, wind_field)   # headwind/tailwind
  + climb_energy_cost(from_state.alt, to_state.alt, uav_spec)  # ΔE = m·g·Δh/η
  + node_cost(to_state.position)                         # Stage 1 lookup at destination
```

### Dubins arc cost
A fixed-wing aircraft cannot teleport from heading 090° to heading 270°.
The `dubins` library computes the **minimum-length arc** between two `(lat, lon, heading)` states
given the vehicle's minimum turn radius. That arc length is multiplied by energy-per-metre to get cost.

```python
import dubins
q0 = (from_x, from_y, from_heading_rad)
q1 = (to_x,   to_y,   to_heading_rad)
path = dubins.shortest_path(q0, q1, turning_radius_m)
arc_cost = path.path_length() * energy_per_metre(airspeed, wind_at_altitude)
```

This naturally **penalises sharp turns**: a 180° reversal costs far more than continuing straight, which matches the battery and structural constraints.

### Wind energy cost
```python
# GRIB U10/V10 surface wind components at waypoint location
u, v = wind_field.at(to_lat, to_lon)          # m/s eastward, northward
flight_dir = heading_to_unit_vector(heading)  # unit vector
wind_component = dot(np.array([u, v]), flight_dir)  # + = tailwind, - = headwind

# Power required ∝ (airspeed - wind_component)² (simplified drag model)
effective_airspeed = airspeed_mps - wind_component
energy = drag_coeff * effective_airspeed**2 * segment_length_m
```

Tailwind legs are genuinely cheaper; headwind legs genuinely more expensive. Without this, the planner treats all directions equally — a physically wrong model.

### Climb energy cost
```python
delta_alt = to_alt_m - from_alt_m
if delta_alt > 0:
    climb_energy = uav_spec.mass_kg * 9.81 * delta_alt / uav_spec.motor_efficiency
else:
    climb_energy = 0.0  # glide descent is (nearly) free; optionally model brake drag
```

Altitude is therefore **both** a hard constraint (must stay above DEM floor) **and** a soft cost (climbing costs energy). The two roles are handled differently:
- **Soft cost:** `climb_energy` added to `edge_cost` above
- **Hard floor:** See Stage 3

---

## Stage 3 — Feasibility Filters (hard constraints, not costs)

These are **not costs** — they are **binary pruning decisions** applied before adding a node to the open set. A node that fails a hard constraint is discarded entirely, regardless of cost.

```python
def is_flyable(pt: Point, alt_m: float, uav_state: UAVState, session: PlanningSession) -> bool:
    # 1. No-fly zones
    if session.no_fly_zones.contains(pt):
        return False
    # 2. Terrain clearance (DEM height + safety margin)
    terrain_alt = session.layer_store.values_at(pt, layer=DEM_LAYER)[0]
    if alt_m < terrain_alt + MIN_CLEARANCE_M:
        return False
    # 3. Battery range — prune if we can't reach this node on remaining charge
    if uav_state.battery_soc * uav_spec.max_range_m < cost_to_reach:
        return False
    return True
```

The distinction matters: if you fold terrain clearance into a very high cost penalty, a planner may still route through it (cost is large but finite). A hard filter makes it impossible — which is the correct safety model.

---

## Stage 4 — Waypoint / Stop Scoring (post-planning)

After the planner produces a route graph, candidate **recharge stops** and **waypoints of interest** are scored separately using a combination of Stage 1 and Stage 2 factors:

```
stop_score(pt) =
    solar_luminance(pt, time_of_day)    # will we actually recharge here?
  + terrain_flatness(pt)               # can we land?
  + accessibility(pt)                  # road verge or open field from OSM?
  - detour_cost(pt, route)             # how far off the optimal line?
```

This is handled by **P5 Solar Recharge Stop Selector** from the algo candidates doc.

---

## Is "cost" the right word?

Technically it is, but it's overloaded. A cleaner vocabulary:

| Term | What it means |
|---|---|
| **Node cost** | Environmental penalty/attractor at a location (Stage 1) |
| **Edge cost** | Energy to transition between two states (Stage 2) |
| **Path cost** | Σ edge costs from start → node (`path_aggregate_cost` / A*'s `g` value) |
| **Heuristic** | Lower-bound estimate of path cost from node → goal (A*'s `h` value) |
| **Hard constraint** | Binary feasibility check — not a cost at all (Stage 3) |

The "cost function" the prompt describes is specifically the **edge cost function** (Stage 2), which uses the **cost field** (Stage 1) as a lookup component. They are two different things.

Is a simple weighted sum the right model? For A*/ARA*/D* Lite: yes, it must be a single scalar. For NAMOA*: no, you maintain a vector. ARA* with a single energy scalar covers the practical need first (algo candidates doc §11).

---

## Full pipeline sketch

```
PlanningSession.plan_all()
│
├── [once] LayerStore.load()            → raster arrays or stream handles
├── [once] CostField.build()            → node_cost(pt) callable   [Stage 1]
├── [once] build_planning_graph()       → networkx.MultiDiGraph (grid or sample)
│           └── for each edge:
│               ├── is_flyable()?       → prune if False            [Stage 3]
│               └── edge_cost()         → float                     [Stage 2]
│                   ├── dubins_arc_energy(from_state, to_state)
│                   ├── wind_energy(heading, wind_field, segment)
│                   ├── climb_energy(Δalt)
│                   └── node_cost(to_pt)  ← Stage 1 lookup
│
├── [parallel] RoutePlannerAStar.run()      → MultiDiGraph + path
├── [parallel] RoutePlannerARAStar.run()    → list[MultiDiGraph] ranked by cost
├── [parallel] RoutePlannerDStarLite.run()  → MultiDiGraph (repairable)
│
└── [post] PathSmoother.reduce()        → Waypoint list (JSON schema output)
         └── Dubins-arc interpolation between simplified nodes      [Stage 4]
```

---

## Where UAVState fits in this picture

`UAVState` is **not a raster layer** — it is the current snapshot of vehicle physics. It feeds into Stage 2 (edge cost) and Stage 3 (battery feasibility). It does NOT feed into Stage 1 (the static cost field is vehicle-state-independent by design, so it can be pre-built).

Cost functions should therefore be typed as:

```python
def edge_cost(
    from_state: FlightPoint,
    to_state:   FlightPoint,
    uav_state:  UAVState,       # battery, current position, current heading
    uav_spec:   UAVSpec,        # turn radius, mass, efficiency (static)
    layers:     LayerStore,     # environmental data
) -> float: ...
```

`UAVState` updates **between steps** as the vehicle moves. This is why D* Lite is valuable: when `UAVState.position` changes significantly (new sensor reading) or a raster layer is updated, only the edges adjacent to changed cells need re-costing — not the whole graph.
