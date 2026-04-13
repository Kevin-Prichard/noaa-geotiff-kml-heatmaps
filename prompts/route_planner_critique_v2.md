# Critique v2: Aerial Route Planner Prompt (Updated)

Items marked `[x]` were already resolved in the previous revision (`route_planner_critique.md`).
Items marked `[ ]` require attention.

---

## 1. Typos & Misspellings

|     | Location | Error | Correction |
|-----|---|---|---|
| [x] | Features → cost function | `"popuation areas"` | *(fixed)* |
| [x] | Features bullet | `"Implement an cost functions"` | `"Implement a cost function"` — article + number agreement |
| [x] | Resources | `"Gemerated Waypoint output list"` | `"Generated Waypoint output list"` |
| [x] | Resources | `"recommend any additional data you think will be helpful+"` | Trailing `+` is an editing artefact — remove it |
| [x] | Education | `"recharing the batter"` | `"recharging the battery"` |
| [x] | PlanningSession methods | `Dict[RoutePlanner, networkx.MultiDiGraph1]` | `MultiDiGraph1` typo → `MultiDiGraph` |

---

## 2. Incorrect Technical Details

- [x] **2.1 "Dijkstra's with A\*"** *(fixed)*
- [x] **2.2 "Euler's method"** *(fixed)*
- [x] **2.5 `Callable[list[ndarray]]`** *(fixed)*
- [x] **2.6 `step -> [int, networkx.Graph]`** *(fixed)*

- [x] **2.3 `Iterator[int, networkx.MultiDiGraph, RoutePlanner]` is invalid Python typing.**
  `typing.Iterator` accepts exactly **one** type argument — the yielded value type. Correct form:
  `Iterator[tuple[int, networkx.MultiDiGraph, type[RoutePlanner]]]`
  Also, `planner.__class__` is a `type`, not a `RoutePlanner` instance, so the third element type is `type[RoutePlanner]`.

- [x] **2.4 `asyncio.gather` is the wrong tool for CPU-bound path planning.**
  `asyncio.gather` provides concurrency for **I/O-bound** coroutines on a single thread. A\*, ARA\*, and D\* Lite are **CPU-bound**. They will run sequentially and block the event loop. True parallelism requires `loop.run_in_executor(ProcessPoolExecutor(...))` (separate processes, no GIL) or `ThreadPoolExecutor` (threads, useful if planners release the GIL via numpy/C extensions). Specify which executor is intended.

- [x] **2.5 `step()` is synchronous but `asyncio.gather` requires awaitables.**
  `RoutePlanner.step()` is declared as a plain synchronous `def`. For `asyncio.gather` to drive planners concurrently, either: (a) `step()` must be `async def step()`, or (b) it must be wrapped in `run_in_executor`. These two requirements are currently contradictory in the prompt.

- [x] **2.6 `cost_func` signature doesn't match its described behaviour.**
  Type hint: `Callable[[list[ndarray]], float]`. Described behaviour: called with "gps point, altitude, heading and airspeed." These are incompatible. Define the signature explicitly, e.g.:
  `Callable[[shapely.Point, UAVState, list[np.ndarray]], float]`

- [x] **2.7 rasterio does NOT interpolate to arbitrary decimal lat/lon automatically.**
  The prompt states rasterio "return[s] grid values for decimal lng/lat regardless of resolution." This is incorrect. Rasterio returns the pixel value that **contains** the coordinate — no interpolation. For sub-pixel accuracy use `rasterio.sample.sample_gen` or `scipy.ndimage.map_coordinates`. The resolution of the answer equals the raster's native resolution.

- [x] **2.8 "All `RoutePlanner` methods `@abstractmethod`" is architecturally incorrect.**
  A pure-abstract base class with zero concrete methods forces every subclass to re-implement shared scaffolding (step counter, session reference, graph initialisation). The base class should provide concrete implementations for at minimum: `__init__` (stores session, sets `_step_nr = 0`, initialises `self._graph`), `_increment_step()`, and `to_gdfs()`. Only `step()` and `plan()` should be `@abstractmethod`.

---

## 3. Internal Inconsistencies

- [x] **3.1 `.plat` typo / `plot` signature** *(fixed)*
- [x] **3.2 "SessionPlanner" name mismatch** *(fixed)*
- [x] **3.3 `cost_func` double-sourcing** *(resolved)*
- [x] **3.5 Singular planner in constructor** *(fixed)*

- [x] **3.1 `BaseGeometry` vs. `LocationSpec` contradiction.**
  The constructor says start/end are "each an instance of shapely's `BaseGeometry`" then immediately says they include "altitude, heading and airspeed — define a class to encapsulate these five parameters." `BaseGeometry` cannot carry those fields. The parameter type must be the new class (`FlightPoint` / `LocationSpec`), not `BaseGeometry`. The `BaseGeometry` mention should be reframed: *"`FlightPoint.position` holds a `shapely.BaseGeometry`."*

- [x] **3.2 `step()` returns `networkx.Graph` but session uses `networkx.MultiDiGraph`.**
  `planStep()` and `planAll()` use `MultiDiGraph` throughout. `RoutePlanner.step()` returns `Graph`. These are four distinct types in networkx. Standardise on `MultiDiGraph` everywhere — it is the correct type for a weighted directed waypoint graph with potentially multiple parallel edges (different Dubins arc radii between the same two nodes).

- [x] **3.3 `planStep()` pseudocode is sequential, not parallel.**
  The pseudocode `for planner in self._planners: yield planner.step()` is a serial generator. The feature requires concurrent execution. If asyncio is the mechanism, `planStep` must be an `async def` using `asyncio.gather` or `asyncio.as_completed`, not a `for` loop.

- [x] **3.4 `plan()` referenced in the lifecycle but not defined.**
  *"Run each `RoutePlanner` concurrently using `asyncio.gather` within the `plan` coroutines"* — but `plan()` was removed and replaced by `planStep()`/`planAll()`. Add it back or remove the reference.

- [x] **3.5 `RoutePlanner` lifecycle is incompatible with D\* Lite.**
  *"forward-moving, not reversible"* is accurate for A\* and ARA\* but **incorrect for D\* Lite**, which searches goal-to-start and repairs backwards through the tree when costs change. This lifecycle constraint must be qualified per subclass or removed from the base description.

- [ ] **3.6 `planAllFrom()` is cut off and overlaps with `planAll()`.**
  The description ends with `# returns dict keyed` (incomplete). The relationship to `planAll()` is unexplained. Does it override the session start point temporarily? Is it for multi-mission leg chaining? Needs full specification.

- [x] **3.7 `destroy()` cannot `await` as a synchronous method.**
  *"awaits or joins any currently outstanding asyncio coroutines"* — `def destroy(self)` is synchronous and cannot use `await`. It must be `async def destroy(self)` or use `asyncio.get_event_loop().run_until_complete(...)`.

---

## 4. Vague or Underspecified Requirements

- [x] **4.3 `feather` → `buffer_dist_m`** *(fixed)*
- [x] **4.5 asyncio.gather named** *(specified, though see §2.4)*
- [x] **4.8 `destroy()` content** *(now described)*

- [x] **4.1 `layer_values` return shape still unspecified.**
  `layer_values(pt, layer_num: int) -> ndarray` — what shape is returned? `(1,)`? `(n_bands,)`? A scalar? With `layer_num` now required, how does a caller retrieve all layers at once? Consider restoring `layer_num: int | None = None` where `None` → shape `(n_layers,)`.

- [x] **4.2 `map_feats` `buffer_dist_m=0.0` default is likely wrong.**
  A buffer of exactly `0.0 m` on a `Point` geometry returns features that geometrically intersect the exact point — almost nothing. Default should be a practical distance (e.g., `50.0`) or `None` meaning "exact match." Document the `0.0` behaviour explicitly.

- [x] **4.3 `plot(self, route)` has no type annotation for `route`.**
  Is `route` a waypoint list? A `MultiDiGraph`? A `dict[type[RoutePlanner], MultiDiGraph]`? Without a type, this is unimplementable.

- [x] **4.4 `action` field has no enum constraint.**
  `"type": "string", "minLength": 1` with no `"enum"` allows arbitrary strings. Define valid values, e.g.: `["waypoint", "loiter", "recharge_stop", "land", "takeoff", "rtl"]`.

- [x] **4.5 Callback convention in `plan()` is still unspecified.**
  When is `callback` invoked? Once per `step()`? Once per planner on completion? Once at the end? And what geometry does it receive — `MultiLineString` (route), `MultiPoint` (waypoints), or the graph?

- [x] **4.6 Grid resolution and bounding area are unspecified.**
  *"Search space structure and resolution will vary according to data available at runtime"* is not actionable. Who builds the grid — `PlanningSession` or each `RoutePlanner`? What is the default resolution? There should be a `grid_resolution_m: float` constructor parameter.

- [x] **4.7 No-fly zones have no constructor parameter or enforcement mechanism.**
  Listed as data in Resources but `PlanningSession.__init__` has no `no_fly_zones` parameter, and there is no `is_flyable(pt: Point) -> bool` method. Hard constraints (must exclude) are architecturally different from soft cost penalties (discourage).

- [x] **4.8 UAV static characteristics (`UAVSpec`) have no class or constructor parameter.**
  Cruising speed, min turn radius, climb/descent rate, max range are listed in Resources but never given a class definition or a home in any constructor. Where does a planner or cost function access them?

- [x] **4.9 Live vehicle state (`UAVState`) has no class definition.**
  The many intrinsic status variables (position, battery, pitot, solar rate, etc.) need a typed `UAVState` dataclass, both for type safety and to define the cost function's calling convention.

- [x] **4.10 `eta_ms` is ambiguous.**
  Milliseconds since Unix epoch? Since mission start? Since previous waypoint? Add a `"description"` to the schema field.

---

## 5. Missing Requirements

- [x] **5.4 CRS convention** *(fixed)*
- [x] **5.10 ABC with `@abstractmethod`** *(specified, though see §2.8)*
- [x] **5.11 Aircraft performance listed** *(in Resources, though no class — see §4.8)*
- [x] **5.12 Error handling** *(now described)*

- [x] **5.1 `NoPathFoundError` exception class is not defined.**
  Error handling is described generically. Define `class NoPathFoundError(RuntimeError): ...` and specify planners raise it when the search space is exhausted.

- [x] **5.2 D\* Lite-specific node attributes are unspecified.**
  D\* Lite requires `g` and `rhs` per node; ARA\* solutions need an `epsilon` tag. Document algorithm-specific node attributes alongside the shared ones (`lng`, `lat`, `cost`, `path_aggregate_cost`).

- [x] **5.3 No `Waypoint` output dataclass defined.**
  The JSON schema defines serialisation but there is no Python `@dataclass` / `TypedDict` for a finalised waypoint. The graph node attributes are planning-internal; a separate `Waypoint` dataclass with fields matching the JSON schema is the clean separation between planner internals and the UAV firmware interface.

- [x] **5.4 Dijkstra's omission from the Tier 1 list should be stated explicitly.**
  The algo candidates doc marks it Essential as a correctness baseline. Its absence from the three subclasses to implement should be acknowledged (e.g., "deferred; A\* serves as the baseline").

- [x] **5.5 Additional missing vehicle state parameters:**
  - Wind at altitude (GRIB upper-air `UGRD`/`VGRD` layers, separate from surface pitot)
  - Turbulence index (affects structural load and battery drain)
  - Icing risk (altitude + temperature + humidity — a hard safety constraint)
  - Maximum bank angle (static spec — determines minimum turn radius at a given airspeed)
  - Stall speed (minimum safe airspeed; headwind may push apparent airspeed toward stall)
  - Autopilot/firmware type (determines valid `action` values in the waypoint schema)

---

## 6. JSON Schema Issues

- [x] **6.1 Draft-04 is outdated.** Use `"$schema": "https://json-schema.org/draft/2020-12/schema"`.
- [x] **6.2 `action` needs `"enum"` of valid values** (see §4.4).
- [x] **6.3 No `cost` or `path_aggregate_cost` field** — the sort key of the output is absent from the schema.
- [x] **6.4 `airspeed_ms` → `airspeed_mps`** — `ms` conventionally means milliseconds; `mps` means metres per second.
- [x] **6.5 `eta_ms` needs `"description"` stating its reference point** (see §4.10).
- [x] **6.6 No waypoint `id` field** correlating to the networkx node key.
- [x] **6.7 No `planner` field** identifying which algorithm generated this waypoint.
- [x] **6.8 `uniqueItems: true` may conflict with loiter patterns** where the same position is legitimately repeated.

---

## 7. Education Section Issues

- [x] **7.1 "Education" will be interpreted as a code generation instruction.**
  Specify the intent: *"Produce inline documentation / a README section discussing the following…"* Otherwise a code generator will embed the discussion as comments or confuse it with implementation requirements.

- [x] **7.2 Cost function sign convention should be stated, not left open.**
  The solar luminance observation is correct: it creates a **negative cost** (attractor) while most factors create positive costs (penalties). Specify the convention: `cost = Σ(weight_i × factor_i)` where attractors have negative weights, penalties have positive weights, and the planner minimises the total. Leave the specific weight values to the invoker.

- [x] **7.3 Topography is both a hard constraint and a soft cost — state this.**
  (a) Terrain height defines a hard minimum altitude floor (must fly above it). (b) Climbing costs extra energy proportional to altitude gain × mass × g / motor efficiency (a soft positive cost term). Both should be stated rather than left as open questions.

---

## 8. Module List Issues
`
| | Module | Issue |
|---|---|---|
| [ ] | `pygrib` | **Still missing** — primary grib/grib2 reader; must be added |
| [ ] | `dubins` | Missing — recommended as P0 primitive in algo candidates doc |
| [ ] | `python-pathfinding` | Missing — recommended library for Theta\* |
| [ ] | `asyncio` | Missing — required by the concurrency model (stdlib, but list it) |
| [ ] | `xarray` | Missing — in `requirements.txt`, useful for multi-dim grib data |
| [ ] | `kiwisolver` | Remove — internal matplotlib dep, not a direct application dep |
| [ ] | `packaging` | Remove or justify — no described use case |
| [ ] | `requests` | Specify use: weather API? Airspace/NOTAM API? |

---

## 9. Recommended Class Design Alternatives

The current design concentrates data access, coordination, concurrency, visualisation, and lifecycle in one `PlanningSession` class. The following restructuring prevents it from becoming a God Object.

### 9.1 Separate `LayerStore` (Repository Pattern)

```python
@dataclass
class LayerStore:
    raster_sources: list[tuple[Path | str, BoundingBox]]
    map_sources:    list[tuple[Path | str | gpd.GeoDataFrame, BoundingBox]]

    def layer_values(self, pt: shapely.Point, layer_num: int | None = None) -> np.ndarray: ...
    def map_feats(self, area: BaseGeometry, buffer_dist_m: float = 50.0) -> gpd.GeoDataFrame: ...
    def close(self) -> None: ...
```

`PlanningSession` holds a `LayerStore` and delegates. `LayerStore` is independently testable and reusable across sessions.

### 9.2 `UAVSpec` and `UAVState` dataclasses

```python
@dataclass(frozen=True)
class UAVSpec:
    cruising_speed_mps: float
    min_turn_radius_m: float
    climb_rate_mps: float
    descent_rate_mps: float
    max_range_m: float
    max_bank_angle_deg: float
    stall_speed_mps: float
    battery_capacity_wh: float

@dataclass
class UAVState:
    position: shapely.Point          # WGS84; .z = altitude_m
    heading_deg: float
    airspeed_mps: float
    battery_soc: float               # 0.0–1.0
    ambient_temp_c: float
    wind_vector_mps: tuple[float, float, float]
    solar_charge_rate_w: float
    timestamp_utc: datetime
```

Both are constructor parameters of `PlanningSession` and passed directly to cost functions, removing the need for cost functions to reach back into the session.

### 9.3 `CostModel` Protocol instead of bare `Callable`

```python
class CostModel(abc.ABC):
    @abc.abstractmethod
    def edge_cost(self, from_pt: shapely.Point, to_pt: shapely.Point,
                  uav_state: UAVState, uav_spec: UAVSpec,
                  layers: LayerStore) -> float: ...

    @abc.abstractmethod
    def node_cost(self, pt: shapely.Point, uav_state: UAVState,
                  layers: LayerStore) -> float: ...
```

Separates edge cost (kinematic/energy) from node cost (terrain/population). Different planners need them differently: A\* uses edge costs primarily; some samplers use node costs.

### 9.4 Async Generator for `step()` — Cleaner Concurrency Model

```python
# RoutePlanner base:
@abc.abstractmethod
async def plan(self) -> AsyncIterator[tuple[int, networkx.MultiDiGraph]]:
    """Yield (step_nr, graph_so_far) after each planning step."""

# PlanningSession:
async def plan_all(self) -> dict[type[RoutePlanner], networkx.MultiDiGraph]:
    tasks = {type(p): asyncio.create_task(p.run_to_completion())
             for p in self._planners}
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    return dict(zip(tasks.keys(), results))
```

Async generators allow live intermediate yields for visualisation while integrating cleanly with `asyncio`. `run_to_completion()` drains the generator and returns the final graph.

### 9.5 `FlightPoint` replaces `BaseGeometry` + bolted-on fields

```python
@dataclass
class FlightPoint:
    position: shapely.Point     # WGS84; Z = altitude_m if known
    altitude_m: float
    heading_deg: float
    airspeed_mps: float

    @classmethod
    def from_geometry(cls, geom: BaseGeometry, **kwargs) -> "FlightPoint":
        return cls(position=geom.centroid, **kwargs)
```

`PlanningSession.__init__` accepts `FlightPoint` for `start` and `end`. Resolves §3.1.

---

## 10. Summary Checklist

- [x] **10.1** Resolve `BaseGeometry` vs `FlightPoint` contradiction in constructor (§3.1)
- [x] **10.2** Fix `Iterator` type: `Iterator[tuple[int, MultiDiGraph, type[RoutePlanner]]]` (§2.3)
- [x] **10.3** Replace `asyncio.gather` with `run_in_executor(ProcessPoolExecutor)` for CPU-bound work (§2.4)
- [x] **10.4** Make `step()` `async def` or document executor wrapping (§2.5)
- [x] **10.5** Fix `cost_func` signature to include `UAVState` (§2.6)
- [x] **10.6** Correct the rasterio resolution claim (§2.7)
- [x] **10.7** Revise "all methods `@abstractmethod`" — list which are concrete (§2.8)
- [x] **10.8** Define `UAVSpec` and `UAVState` and add to constructors (§4.8, §4.9)
- [x] **10.9** Define `NoPathFoundError` (§5.1)
- [x] **10.10** Add `pygrib`, `dubins`; remove `kiwisolver`, `packaging` (§8)
- [x] **10.11** Fix JSON schema: draft version, `action` enum, `cost`/`id`/`planner` fields, `airspeed_mps`, `eta_ms` description (§6)
- [x] **10.12** Add `no_fly_zones` constructor parameter and `is_flyable(pt)` method (§4.7)
- [x] **10.13** Complete `planAllFrom()` spec and clarify its relationship to `planAll()` (§3.6)
- [x] **10.14** Make `destroy()` `async def` (§3.7)
- [x] **10.15** Add `grid_resolution_m` constructor parameter (§4.6)
- [x] **10.16** Fix `MultiDiGraph1` typo in `planAllFrom` (§1)

---

**Summary of what's new vs. the first critique:**

The prompt has improved substantially — the algorithm names, CRS, ABC declaration, error handling, JSON schema, and `buffer_dist_m` rename are all addressed. The remaining issues are mostly **new ones introduced by the revision itself**:

1. **`asyncio.gather` + CPU-bound work** — the biggest architectural problem: asyncio doesn't parallelize CPU work without an executor
2. **`BaseGeometry` vs. `FlightPoint`** — the start/end type is now contradictory within a single bullet
3. **"All methods `@abstractmethod`"** — would produce a useless interface with no shared scaffolding
4. **`Iterator[int, MultiDiGraph, RoutePlanner]`** — invalid Python type syntax
5. **`step()` sync/async conflict** — the sync signature can't work with `asyncio.gather`
6. **JSON schema gaps** — no `cost`/`id`/`planner` fields, stale draft version, missing `action` enum
7. **Design section** — recommends extracting `LayerStore`, `UAVSpec`, `UAVState`, `CostModel`, and `FlightPoint` as dedicated classes to keep `PlanningSession` manageable
