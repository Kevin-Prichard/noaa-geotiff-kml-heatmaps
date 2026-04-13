# Critique v4: Aerial Route Planner Prompt

Items already covered in `route_planner_critique_v3.md` and resolved in v4 are **excluded** for brevity.
Items marked `[ ]` require attention; `[x]` are resolved relative to v3.

---

## Resolution summary (v3 → v4)

| v3 Item | Status |
|---|---|
| §1 all typos | ✅ |
| §2.1 `sample_gen` deprecated | ✅ |
| §2.2 `NoPathFoundError` description | ✅ |
| §2.3 `map_feats` Point guard logic | ✅ |
| §2.4 `step()` yield vs callback | ✅ renamed to `dispatch_step` |
| §2.5 `destroy()` await language | ✅ |
| §3.1–§3.7 all internal inconsistencies | ✅ |
| §4.1 `EdgeCostPipeline` named + interfaced | ⚠️ partially — new conflicts (see §2 below) |
| §4.2–§4.6 vague items | ✅ |
| §4.7 `Waypoint` serialisation | ⚠️ partially — `to_json()` + `save_as()` added; `to_dict()` / list-level fn absent |
| §5.1–§5.3 JSON errors | ✅ |
| §5.4 `"action"` enum `"recharge_stop"` | ✅ added; **`"rtl"` still absent** |
| §5.5 `"planner"` in `required` | ✅ |
| §6.1–§6.4 src/*.py issues | ✅ |
| §7 module list | ⚠️ `pyproj` ✅; `dubins`/`scipy`/`python-pathfinding` still absent |
| §8.1 `dispatch_step` rename | ✅ |
| §8.2 `CostModel` ABC | ✅ src/cost_model.py exists — **but v4 prompt ignores it** (see §3.1) |
| §8.3 `PlanningGrid` | ✅ src/planning_grid.py exists — **but v4 prompt ignores it** (see §3.2) |

---

## 1. Regressions (resolved in v3, reintroduced in v4)

| | Location | Error | Correction |
|---|---|---|---|
| [ ] | Features → FlightPoint attributes | `_heading: float` | `_heading_deg: float` — `src/flight_point.py` uses `_heading_deg`; v3 fixed `_altitude_m` but `_heading` suffix was not updated |
| [ ] | `PlanningSession.layer_values` signature | `layer_num: int \| None = None` | `layer: str \| None = None` — `LayerStore` uses string keys; v3 §4.6 established this |
| [ ] | JSON schema `"action"` enum | `"rtl"` absent | v3 §5.4 explicitly recommended adding `"rtl"` (return-to-launch); `"recharge_stop"` was added but `"rtl"` still missing |

---

## 2. Incorrect Technical Details

- [ ] **2.1 `EdgeCostPipeline.is_flyable` is missing `layers: LayerStore`.**
  The terrain-clearance check (the most critical hard constraint) reads the DEM from `LayerStore`.
  The signature `is_flyable(fp, uav_state, uav_spec)` without `layers` cannot perform that check.
  Correct signature (matching `src/cost_model.py`):
  ```python
  def is_flyable(
      fp: FlightPoint,
      uav_state: UAVState,
      uav_spec:  UAVSpec,
      layers:    LayerStore,
      no_fly_zones: list[BaseGeometry] | None = None,
  ) -> bool: ...
  ```

- [ ] **2.2 `no_fly_zones: List[ndarray|GeoDataFrame|BaseGeometry]` — `ndarray` is not a zone type.**
  An `ndarray` is an array of numbers and does not represent a geographic polygon.
  A code generator receiving this type will not know what coordinate system or shape convention
  the array uses. Correct type: `list[BaseGeometry | GeoDataFrame]`.
  If raw coordinate arrays need to be accepted, specify the convention explicitly:
  `ndarray` of shape `(N, 2)` in WGS84 (lon, lat) — then convert to `Polygon` at construction.

- [ ] **2.3 `dispatch_step` pseudocode has two bugs.**
  ```python
  # as written in v4:
  step_nr, graph = a_planner.step()                     # ← 'a_planner' is not the loop variable
  callback(step_nr, graph_so_far, planner.__class__)    # ← 'graph_so_far' is not defined
  ```
  Correct pseudocode:
  ```python
  for planner in self._planners:
      step_nr, graph = planner.step()
      callback(step_nr, graph, planner.__class__)
  ```

- [ ] **2.4 `dispatch_step` sequential loop contradicts the concurrent execution requirement.**
  The lifecycle section says *"Run each `RoutePlanner` concurrently using `joblib`."*
  The pseudocode shows a sequential `for` loop with a callback — which is inherently serial.
  These two specifications are mutually exclusive as written.
  Pick one and make it explicit:
  - **Callback (serial):** the for-loop pattern; remove the `joblib` parallelism requirement, or
    limit `joblib` to `plan_all()` only.
  - **Parallel (joblib):** `plan_all()` uses `joblib.Parallel`; `dispatch_step` is kept serial
    for step-by-step inspection / debugging use cases.

---

## 3. Internal Inconsistencies

- [ ] **3.1 `EdgeCostPipeline` conflicts with the already-existing `src/cost_model.py`.**
  `src/cost_model.py` (generated in our last session) provides:
  - `CostModel` — ABC with `node_cost`, `edge_cost`, `is_flyable`
  - `BaseCostModel` — concrete physics helpers; leaves only `node_cost` abstract
  - `DefaultCostModel` — full implementation (population penalty + solar attractor)
  - `LAYER_TERRAIN`, `LAYER_POPULATION`, `LAYER_SOLAR` constants

  The v4 prompt asks for a *new* `EdgeCostPipeline` class with a slightly different (and
  incomplete — see §2.1) interface, which would create a parallel, conflicting hierarchy.
  The prompt should instead say:
  *"Use `src/cost_model.py`. `PlanningSession` accepts a `cost_model: CostModel` parameter.
  The default is `DefaultCostModel()`. Do not implement `EdgeCostPipeline`."*

- [ ] **3.2 `PlanningGrid` from `src/planning_grid.py` is not integrated into the spec.**
  `src/planning_grid.py` (generated in our last session) implements `PlanningGrid.build()`,
  `is_flyable()`, and `nearest_node()`. The v4 prompt says `PlanningSession.__init__` stores
  `self._grid` as a `networkx.MultiDiGraph`, but it should store a `PlanningGrid` instance:
  ```python
  self.grid = PlanningGrid.build(
      bbox=..., resolution_m=grid_resolution_m, max_grid_nodes=max_grid_nodes,
      layers=..., terrain_layer=LAYER_TERRAIN,
  )
  ```
  Planners then receive `session.grid` (a `PlanningGrid`) and access `session.grid.graph`
  (the raw `MultiDiGraph`). Without this, the terrain-clearance work in `PlanningGrid`
  is unreachable.

- [ ] **3.3 `FlightPoint` re-definition instruction is too ambiguous.**
  The Features section defines `FlightPoint` attributes and adds *"(superseded by
  `src/flight_point.py`)"* as a parenthetical. A code generator may treat this as
  "generate the class and note the file exists" rather than "import and do not reimplement."
  Replace with an explicit instruction matching the existing UAVSpec/UAVState pattern:
  *"Import `FlightPoint` from `src/flight_point.py`; do not reimplement it."*

- [ ] **3.4 `PlanningSession` constructor still accepts "a cost function or class instance object."**
  This untyped description will cause the code generator to accept `Any`, losing all type safety.
  The parameter should be explicitly typed:
  ```python
  cost_model: CostModel = DefaultCostModel()
  ```
  referencing the ABC from `src/cost_model.py`.

- [ ] **3.5 `RoutePlanner._graph` — copy or reference to `session.grid.graph` is unspecified.**
  `RoutePlanner.__init__` *"initialises `self._graph`"* — but from what source?
  If `self._graph = session.grid.graph` (shared reference), planners running in parallel
  via joblib will corrupt each other's node/edge annotations.
  The intent is almost certainly a **copy**: `self._graph = session.grid.graph.copy()`.
  State this explicitly. (Note: `networkx.MultiDiGraph.copy()` is a shallow copy; for deep
  isolation use `copy.deepcopy`.)

- [ ] **3.6 `grid_margin_m` referenced but not defined as a constructor parameter.**
  The spec says `PlanningSession.__init__` builds the grid over `bbox(start, end, margin)`,
  but `margin` appears nowhere in the constructor parameter list.
  Add: `grid_margin_m: float = 5_000.0` (metres) and specify how it expands the bbox
  (e.g., add `grid_margin_m` to all four sides after converting to the local AEQD frame).

---

## 4. Vague or Underspecified Requirements

- [ ] **4.1 `RoutePlanner.plan()` has no return type or description.**
  Listed as `@abstractmethod` alongside `step()`, but no signature is given.
  Specify at minimum:
  ```python
  @abstractmethod
  def plan(self) -> networkx.MultiDiGraph:
      """Run the algorithm to completion and return the final graph."""
  ```

- [ ] **4.2 `RoutePlanner.to_gdfs()` has no return type or description.**
  Listed in the base class method inventory with no specification.
  Without knowing what GeoDataFrames it should return (nodes? edges? both?),
  the code generator will guess. Specify:
  ```python
  def to_gdfs(self) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
      """Return (nodes_gdf, edges_gdf) for the current planning graph."""
  ```

- [ ] **4.3 ARA\* ε parameters are not specified for `RoutePlannerARAStar`.**
  ARA\* requires an initial inflation factor, a final (target) value, and a decrement step.
  The code generator will have to invent values with no guidance.
  Add constructor parameters:
  - `epsilon_initial: float = 3.0`
  - `epsilon_final: float = 1.0`
  - `epsilon_decrement: float = 0.5`
  and state that the `epsilon` tag in the node dataclass records the ε value at which
  the node was last expanded.

- [ ] **4.4 Node dataclass subclass names are not specified.**
  *"create a base `@dataclass` with subclasses matching each route planner subclass"* —
  no class names are given for either the base or the four subclasses.
  Specify names, e.g.:
  ```
  PlanNodeBase       → shared: lng, lat, cost, path_aggregate_cost
  PlanNodeDijkstra   → (no extras)
  PlanNodeAStar      → (no extras; g is path_aggregate_cost, h stored separately)
  PlanNodeARAStar    → epsilon: float
  PlanNodeDStarLite  → g: float, rhs: float
  ```

- [ ] **4.5 `plan_all_from(start_point)` — grid rebuild behavior not specified.**
  If `start_point` is outside the original session bbox, the existing grid does not cover
  the new start. The method must either: (a) raise `ValueError` with a clear message, or
  (b) rebuild `self.grid` with a new bbox. Neither option is stated.

- [ ] **4.6 FGB map file loading strategy is not specified.**
  `PlanningSession` accepts FGB file paths and/or `GeoDataFrame` instances.
  `map_feats()` queries them — but are they pre-loaded at construction (buffered in RAM)
  or opened on demand per call? This distinction matters for memory use and joblib worker
  serialisation (file paths cross process boundaries safely; open GeoDataFrames may not).
  Specify: pre-load all FGB files into `GeoDataFrame` instances at construction time,
  clipped to the provided bbox.

- [ ] **4.7 `Waypoint.save_as(pathname)` file format is not specified.**
  The JSON schema is given, but `save_as` doesn't say it writes JSON.
  Also missing: `to_dict(self) -> dict` (needed to compose `to_json`) and a
  module-level `waypoints_to_json(waypoints: list[Waypoint]) -> str` for serialising
  a full route. `to_json()` on a single waypoint is not the serialisation unit — the
  route (list of waypoints) is. Specify all three:
  ```python
  # on Waypoint:
  def to_dict(self) -> dict: ...
  def to_json(self) -> str: ...          # single waypoint
  def save_as(self, path: Path) -> None: ...
  # module-level:
  def waypoints_to_json(waypoints: list[Waypoint]) -> str: ...
  def save_waypoints(waypoints: list[Waypoint], path: Path) -> None: ...
  ```

- [ ] **4.8 D\* Lite cost-update mechanism not specified.**
  D\* Lite is described as providing dynamic replanning when "updated weather geotiffs
  arrive mid-mission." But no method on `RoutePlannerDStarLite` or `PlanningSession`
  is defined to accept updated raster data and trigger edge-weight repair.
  At minimum add:
  ```python
  # on RoutePlannerDStarLite:
  def update_edge_costs(self, changed_nodes: list[int]) -> None:
      """Rekey the priority queue for nodes whose edge costs have changed."""
  ```
  and a corresponding `PlanningSession.refresh_layer(key: str, path: Path)` or similar.

---

## 5. Smoke Test Gaps

- [ ] **5.1 `uav_state` instance is missing from the smoke test.**
  `PlanningSession` now requires `uav_state: UAVState` but the smoke test provides no
  example construction. Add, e.g.:
  ```python
  uav_state = UAVState(
      flight_point=start_fp,
      battery_soc=1.0,
  )
  ```

- [ ] **5.2 `plot()` signature doesn't support PNG save.**
  The smoke test instructions say *"saves a png of the passed map"* but `plot(self) -> None`
  accepts no path argument. Either:
  ```python
  def plot(self, save_path: Path | str | None = None) -> None: ...
  ```
  or add a separate `save_png(path: Path) -> None` method.

---

## 6. Module List (carryover open items from v3 §7)

| | Module | Status |
|---|---|---|
| [ ] | `dubins` | Still absent from `requirements.txt` and module preferences — P0 primitive; `src/cost_model.py` already imports it |
| [ ] | `scipy` | Still absent — needed for sub-pixel bilinear interpolation (`scipy.ndimage.map_coordinates`); also used by P4 Path Smoother (`scipy.interpolate.BSpline`) |
| [ ] | `python-pathfinding` | Still absent — Theta\* (Tier 2 in algo candidates doc) uses this PyPI package |
| [ ] | `packaging` | Still listed in module preferences with no described use case — remove or justify |
| [ ] | `osmnx` | Listed in module preferences; map data comes from pre-provided FGB files; if `osmnx` is only for downloading data the human manages, remove it |
| [ ] | `requests` | Listed in module preferences; human manages web resource retrieval per the prompt — no HTTP call from generated code is described; remove or justify |
| [x] | `pyproj` | Added to `requirements.txt` ✅ |

---

## 7. Class Design Observations (sidebar)

### 7.1 `RoutePlanner._graph`: shallow copy is not sufficient for joblib isolation

`networkx.MultiDiGraph.copy()` copies the graph structure but **shares the node and edge
attribute dictionaries** between the original and the copy. When joblib forks worker
processes, each worker gets its own copy of the Python object graph — so forked-process
isolation is fine. But if workers share memory via `loky`'s memory-mapped arrays, mutations
to node attribute dicts in one worker can corrupt another's view.

The safe, explicit specification is:
```python
self._graph = copy.deepcopy(session.grid.graph)
```
or, if RAM is a concern (4 planners × 50 000 nodes × ~200 bytes/node ≈ 40 MB — acceptable),
accept the deep-copy cost and document it.

### 7.2 `CostModel` vs `EdgeCostPipeline` — one ABC, not two

`src/cost_model.py` already resolves the v3 §8.2 gap. Introducing `EdgeCostPipeline` as a
*second* cost interface creates an unmaintainable split. The unified path:

```
CostModel (ABC)          — src/cost_model.py
  └─ BaseCostModel       — concrete edge_cost + is_flyable; node_cost abstract
       └─ DefaultCostModel — population penalty + solar attractor

PlanningSession.cost_model: CostModel   ← single typed seam
RoutePlanner uses:  self.session.cost_model.edge_cost(...)
```

Every planner, regardless of algorithm, evaluates cost through the same typed interface.
Swapping in a wind-aware model or a multi-objective model requires only changing the
`cost_model` argument at `PlanningSession` construction — no planner code changes.

### 7.3 `PlanningGrid` should be the grid seam, not `networkx.MultiDiGraph`

`src/planning_grid.py` already wraps the `MultiDiGraph` with:
- `is_flyable(node_id, alt_m)` — O(1) DEM lookup (no I/O during planning)
- `nearest_node(lon, lat)` — O(1) projected grid lookup
- `node_terrain_elev(node_id)` — cached DEM value

If `PlanningSession._grid` is typed as a raw `MultiDiGraph`, callers lose these conveniences
and have to reimplement terrain queries inline. Update the spec to:

```python
# PlanningSession:
self.grid: PlanningGrid = PlanningGrid.build(...)

# RoutePlanner.__init__:
self._grid: PlanningGrid = session.grid
self._graph: networkx.MultiDiGraph = copy.deepcopy(session.grid.graph)
```

Planners call `self._grid.is_flyable(node_id, alt_m)` for the hard constraint check
and annotate `self._graph` with algorithm-specific node/edge attributes independently.
