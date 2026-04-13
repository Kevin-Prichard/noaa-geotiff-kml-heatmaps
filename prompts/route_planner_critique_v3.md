# Critique v3: Aerial Route Planner Prompt

Items already resolved in `route_planner_critique_v2.md` are **excluded** for brevity.
Items marked `[ ]` require attention; `[x]` are resolved relative to v2.

---

## 1. Typos & Misspellings

|     | Location | Error | Correction |
|-----|---|---|---|
| [x] | RoutePlanner `step()` return type | `networkx.MutiDiGraph` | `networkx.MultiDiGraph` (missing `l`) |
| [x] | Features → FlightPoint | `_altitude: float` | `_altitude_m: float` — contradicts `src/flight_point.py` |
| [x] | UAVState comment in Additional classes | `"route-planned"` | `"route-planning"` |
| [x] | Summary bbox | `bbox(-122.36581181660316, 38.01772638122616, )` | Incomplete — one coordinate and trailing comma (see §3.5) |
| [x] | Solar luminance path | `` ![PVOUT.tif](../sol/...) `` | Markdown image syntax — should be a bare file path |

---

## 2. Incorrect Technical Details

- [x] **2.1 `rasterio.sample.sample_gen` is deprecated.**
  The prompt says *"Utilize `rasterio.sample.sample_gen` to obtain sub-pixel samples."*
  `sample_gen` was removed in rasterio ≥ 1.3. The current API is `dataset.sample([(x, y)])` or
  `rasterio.sample.sample(dataset, xy)`. For true sub-pixel bilinear interpolation use
  `scipy.ndimage.map_coordinates` on a pre-loaded array, or `rasterio.warp.reproject` to a finer
  grid. Correct the function name and specify the interpolation strategy.

- [x] **2.2 `NoPathFoundError` description is wrong.**
  The prompt says *"to be raised when a grid or map resource pathname is not found."*
  That is `FileNotFoundError` / `IOError` territory.
  `NoPathFoundError` should be raised when the **planner exhausts the search space** and no
  route exists between start and end. The two failure modes need separate exception classes:
  `ResourceNotFoundError` (file/layer missing) and `NoPathFoundError` (graph exhausted).

- [x] **2.3 `map_feats` raises on `Point` — logic is inverted.**
  `# where isinstance(area, Point) == True raises an exception`
  A `Point` is the **most common** query geometry (sample the map at a candidate waypoint).
  Raising on `Point` makes the method nearly useless to planners. The correct guard is: if
  `area` is a `Point` *and* `buffer_dist_m == 0.0`, either raise a descriptive error or
  silently apply a minimum buffer (e.g. 50 m). Remove the Point prohibition; document the
  buffer requirement instead.

- [x] **2.4 `PlanningSession.step()` pseudocode uses `yield` but signature says `-> None`.**
  A function containing `yield` is a generator; its return type would be
  `Iterator[tuple[int, networkx.MultiDiGraph, type[RoutePlanner]]]`, not `None`.
  Additionally, the signature accepts a `callback` — a generator does not invoke a callback,
  it yields to the caller. Pick one pattern:
  - **Generator:** `def step(self) -> Iterator[tuple[int, MultiDiGraph, type[RoutePlanner]]]`
  - **Callback:** `def step(self, callback: Callable[[int, MultiDiGraph, type[RoutePlanner]], None]) -> None` and call `callback(step_nr, graph, cls)` inside the loop.

- [x] **2.5 `destroy()` says "awaits … outstanding subprocesses."**
  joblib uses process pools, not asyncio coroutines. There is nothing to `await`.
  Correct description: *"cancels or waits for any active joblib `Parallel` workers by
  allowing the context manager to exit; sets all instance attributes to `None`."*

---

## 3. Internal Inconsistencies

- [x] **3.1 `planAll()` key type is `dict[RoutePlanner, ...]` — should be `dict[type[RoutePlanner], ...]`.**
  The key is described as "the RoutePlanner subclass ref" (a class object), not an instance.
  Both `planAll` and `planAllFrom` should use `dict[type[RoutePlanner], networkx.MultiDiGraph]`.

- [x] **3.2 JSON schema: `"eta_unix_ms"` in `required` vs `"eta_unix_millis"` as property name.**
  The `required` array lists `"eta_unix_ms"` but the `properties` object defines `"eta_unix_millis"`.
  These must match. Pick one name and use it consistently; `"eta_unix_ms"` is the shorter form
  but `"eta_unix_millis"` is clearer. Recommend `"eta_unix_ms"` everywhere.

- [x] **3.3 `FlightPoint` field name `_altitude` vs `_altitude_m` in `src/flight_point.py`.**
  The v3 prompt defines `_altitude: float` but `src/flight_point.py` (already generated) uses
  `_altitude_m`. The prompt will cause a regenerated class to conflict with the existing file.
  The prompt must match the file, or explicitly state "update the existing file."

- [x] **3.4 `UAVSpec` / `UAVState` are both "see src/*.py" and implicitly re-implemented.**
  The prompt says "see src/uav_spec.py" and "see src/uav_state.py" — but earlier says
  *"Generate code to accomplish this prompt … Incorporate existing work in src/*.py."*
  The instruction should be explicit: **import these classes, do not re-implement them.**
  Add `from src.uav_spec import UAVSpec` and `from src.uav_state import UAVState` to the
  module's imports and remove them from the class list.

- [x] **3.5 Smoke test bbox is incomplete.**
  `bbox(-122.36581181660316, 38.01772638122616, )` provides only one coordinate pair and has
  a trailing comma. A bounding box requires four values (west, south, east, north).
  Based on the start/end coordinates the southeast corner is approximately
  `(-121.55, 37.60)`. Provide the complete bbox or the smoke test cannot be implemented.

- [x] **3.6 `UAVSpec` and `UAVState` are absent from `PlanningSession` constructor parameters.**
  Both classes are used by cost functions and feasibility checks (`is_flyable`, `edge_cost`),
  but neither appears in the `PlanningSession` constructor parameter list. Add:
  - `uav_spec: UAVSpec`
  - `uav_state: UAVState`  (initial state at mission start)

- [x] **3.7 Lifecycle shows `.step()` but `step` now requires a `callback` argument.**
  The lifecycle reads:
  ```
  .step()
  ```
  but the method signature is `step(self, callback: Callable[...]) -> None`.
  Either the lifecycle must pass a callback, or `callback` must be made optional
  (`callback: Callable[...] | None = None`).

---

## 4. Vague or Underspecified Requirements

- [x] **4.1 Edge cost pipeline class has no name or interface.**
  The prompt says *"Implement an edge cost planning pipeline as a class."*
  Neither a class name, constructor parameters, nor public methods are specified.
  From `plan-costFunctionPipeline.prompt.md` the natural name is `CostModel` or
  `EdgeCostPipeline`. At minimum specify:
  - class name
  - `node_cost(pt: Point, layers: LayerStore) -> float`
  - `edge_cost(from_fp: FlightPoint, to_fp: FlightPoint, uav_state: UAVState, uav_spec: UAVSpec, layers: LayerStore) -> float`
  - `is_flyable(fp: FlightPoint, uav_state: UAVState, uav_spec: UAVSpec) -> bool`

- [x] **4.2 `map_feats` default `buffer_dist_m=0.0` is still 0.0 (flagged in v2 §4.2).**
  A zero-metre buffer on any geometry except a polygon that already has area returns
  almost nothing useful. Default should be `50.0` or `None`; document `0.0` behaviour.

- [x] **4.3 Smoke test `FlightPoint` construction is missing altitude, heading, airspeed.**
  Only `(longitude, latitude)` coordinates are given for start and end. `FlightPoint`
  requires `_altitude_m`, `_heading_deg`, and `_airspeed_mps`. Provide sensible values
  for the demo (e.g. altitude 300 m AGL, heading derived from bearing, cruise speed).

- [x] **4.4 No `UAVSpec` instance provided for the smoke test.**
  The smoke test `main()` cannot call any planner or cost function without a `UAVSpec`.
  Provide a complete example instantiation using the 50-kt VTOL spec from `src/uav_spec.py`.

- [x] **4.5 Grid building responsibility is unspecified.**
  `grid_resolution_m` and `max_grid_nodes` are `PlanningSession` constructor parameters,
  but the prompt does not say who builds the grid graph, what type it is, or how planners
  receive it. Specify: `PlanningSession.__init__` builds a `networkx.MultiDiGraph` grid
  over `bbox(start, end, margin)` at `grid_resolution_m` spacing, capped at `max_grid_nodes`,
  and stores it as `self._grid`. Each `RoutePlanner.__init__` receives a reference to
  `session._grid` and operates on it.

- [x] **4.6 Terrain layer index undocumented.**
  The prompt says "terrain is always a requirement" and "hard deck … must be kept in mind."
  But the layer list passed to `PlanningSession` is positional (`layer_num: int`). There is
  no convention for which index is terrain vs population vs solar. Either:
  (a) add a `terrain_layer_index: int` constructor parameter, or
  (b) use a named-layer dict (`dict[str, tuple[Path, BoundingBox]]`) in `LayerStore` so
  planners can request `layers["terrain"]` by name.

- [x] **4.7 `Waypoint` dataclass serialization not specified.**
  The prompt says "based on the items objects from the Waypoint JSONSchema" but does not
  specify a `to_dict()` / `to_json()` method or say how the list of waypoints is exported.
  Add a `to_dict(self) -> dict` method and a module-level
  `waypoints_to_json(waypoints: list[Waypoint]) -> str` function.

---

## 5. JSON Schema Errors

- [x] **5.1 Invalid JSON — trailing comma in `required` array.**
  `"path_aggregate_cost",` has a trailing comma. JSON does not permit trailing commas.

- [x] **5.2 Invalid JSON — `"planner"` property missing closing `}`.**
  The `"planner"` property block is:
  ```json
  "planner": {
    "type": "string",
    "description": "Name of the Python class which produced this waypoint list"
  ```
  The closing `}` is missing before `"longitude"`. This will cause a JSON parse error.

- [x] **5.3 `"id"` should be type `"integer"`, not `"number"`.**
  networkx node keys are integers by default. `"number"` allows floats; use `"integer"`.

- [x] **5.4 `"action"` enum is missing `"recharge_stop"` and `"rtl"`.**
  The v2 critique (§4.4) recommended these values. `"recharge_stop"` is critical given the
  solar-recharge multi-leg mission design. `"rtl"` (return-to-launch) is standard UAV
  firmware vocabulary. `"holding"` / `"loiter"` should be kept as is.

- [x] **5.5 `"planner"` is not in the `required` array.**
  The field is defined in `properties` but omitted from `required`. Since the primary
  purpose of the output set is side-by-side planner comparison, `"planner"` should be required.

---

## 6. Existing Code Issues (from review of `src/*.py`)

- [x] **6.1 `uav_spec.py` line 99: `reference_power` is computed but never used.**
  ```python
  reference_power = self.drag_coeff * self.cruising_speed_mps ** 2  # ← dead code
  actual_power    = self.drag_coeff * effective ** 2
  ```
  Either use it to normalise `actual_power`, or remove it.

- [x] **6.2 `uav_state.py`: unused import inside `reach_probability()`.**
  `from shapely.ops import transform` is imported but never called. Remove it.

- [x] **6.3 `src/*.py` use bare module imports that will fail without `src/` on `sys.path`.**
  `uav_state.py` contains `from flight_point import FlightPoint` (no package prefix).
  If `waypoints.py` lives in the project root and imports from `src/`, Python will not
  find `flight_point` unless `src/` is explicitly added to `sys.path` or a package
  `__init__.py` is present and relative imports are used.
  Resolve by either:
  - adding `src/__init__.py` and using `from src.flight_point import FlightPoint`, or
  - using relative imports (`from .flight_point import FlightPoint`) inside the `src` package.

- [x] **6.4 `LayerStore.BoundingBox` NamedTuple conflicts with the prompt's GeoSeries bbox format.**
  The prompt specifies bounding boxes as
  `gpd.GeoSeries([shapely.Point(lon0, lat0), shapely.Point(lon1, lat1)])`.
  `src/layer_store.py` defines its own `BoundingBox(west, south, east, north)` NamedTuple.
  Pick one representation project-wide and convert at the boundary. Using
  `BoundingBox` everywhere internally is cleaner; add a
  `BoundingBox.from_geoseries(gs: gpd.GeoSeries) -> BoundingBox` classmethod as the
  conversion point.

---

## 7. Module List Issues

| | Module | Issue |
|---|---|---|
| [ ] | `dubins` | Still missing — P0 primitive per algo candidates doc; required by Dubins edge weighter |
| [ ] | `scipy` | Missing — needed for sub-pixel raster interpolation (`scipy.ndimage.map_coordinates`) |
| [ ] | `pyproj` | Missing from module preferences — already used in `src/uav_state.py` and `src/layer_store.py` |
| [ ] | `packaging` | Still listed with no described use case — remove or justify |
| [ ] | `python-pathfinding` | Missing — recommended for Theta\* (Tier 2 in algo candidates doc) |

---

## 8. Class Design Observations (sidebar)

### 8.1 `step()` name collision

`PlanningSession.step()` and `RoutePlanner.step()` share a name but have **different semantics**:
- `RoutePlanner.step()` advances one algorithm iteration and returns a graph snapshot.
- `PlanningSession.step()` drives *all* planners and dispatches results via callback or yield.

This will cause confusion in code (especially when reading `session.step()` vs `planner.step()`).
Recommend renaming the session-level method to `dispatch_step()` or `advance()`.

### 8.2 `CostModel` class still absent

The v2 critique (§9.3) recommended a `CostModel` ABC with `edge_cost()`, `node_cost()`, and
the feasibility-check `is_flyable()`. The v3 prompt still passes "a cost function or class
instance object" — which is too ambiguous for a code generator to produce a consistent
interface. Adding `CostModel` as a formal ABC would:
- give cost functions a typed, testable interface
- allow planners to call `self.session.cost_model.edge_cost(...)` without knowing the
  implementation
- separate hard constraints (`is_flyable`) from soft costs (`edge_cost`, `node_cost`)

### 8.3 `PlanningGrid` class (missing abstraction)

Neither `PlanningSession` nor any `RoutePlanner` is clearly responsible for building the
grid graph. A thin `PlanningGrid` dataclass would resolve this:

```python
@dataclass
class PlanningGrid:
    graph: networkx.MultiDiGraph   # nodes at grid_resolution_m spacing over bbox
    resolution_m: float
    bbox: BoundingBox
    terrain_layer_index: int       # which LayerStore layer is the DEM

    @classmethod
    def build(cls, session: "PlanningSession") -> "PlanningGrid": ...
    def is_flyable(self, node_id: int, alt_m: float, clearance_m: float = 30.0) -> bool: ...
```

`PlanningSession` builds and holds one `PlanningGrid`; planners receive it at construction.
This cleanly answers the "who builds the grid?" question and centralises terrain-clearance
checks in one testable place.
