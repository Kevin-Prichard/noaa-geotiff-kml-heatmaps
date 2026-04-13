# Critique: Aerial Route Planner Prompt

---

## 1. Typos & Misspellings

| _ | Location | Error | Correction |
|---|---|---|---|
| x | Features → cost function | `"popuation areas"` | `"population areas"` |
| x | Features → cost function | `"farmers fields"` | `"farmers' fields"` (missing possessive apostrophe) |
| x | PlanningSession constructor | `"available to used by"` | `"available to be used by"` |
| x | PlanningSession lifecycle | `".plat(route=my_route)"` | `".plot(route=my_route)"` — `"plat"` is not defined anywhere |
| x | Resources section | `"will used to produce"` | `"will be used to produce"` |

---

## 2. Incorrect Technical Details

- [x] **2.1 "Dijkstra's algorithm with A\*" is a confused formulation.**
A\* and Dijkstra's are two distinct algorithms. A\* is an informed generalization of Dijkstra's (Dijkstra's is equivalent to A\* with a zero heuristic). Writing "Dijkstra's with A\*" implies they are used together or that one augments the other. The clear intent is to implement them as two separate route planners. Should read: *"Dijkstra's algorithm and A\*, as two separate RoutePlanner subclass implementations."*

- [x] **2.2 "Euler's method" is not a route/path planning algorithm.**
Euler's method is a first-order numerical integration technique for solving ordinary differential equations. It has no established role as a path planner. Its inclusion here is a category error. The prompt presumably intends a second distinct pathfinding algorithm (in addition to A\*) — candidates include RRT\*, Theta\*, D\* Lite, Jump Point Search, or Hybrid A\* — but Euler's method is none of these.

- [x] **2.3 `cost_func(self) -> float` has the wrong return type.**
This is named as a getter that returns the session's cost function callable. Its return type should be `Callable[..., float]` (or a more specific signature), not `float`. Returning `float` would imply it *calls* the cost function and returns its scalar result — but the method accepts no arguments to compute with, making that interpretation self-contradictory.

- [x] **2.4 `Callable[BaseMultiGeometry]` is invalid Python typing syntax.**
`typing.Callable` requires the form `Callable[[ArgType, ...], ReturnType]`. Argument types must be enclosed in a list, and a return type is required. Should be written as `Callable[[BaseMultiGeometry], None]` or a more descriptive equivalent.

- [x] **2.5 `Callable[list[ndarray]]` is invalid Python typing syntax.**
Same issue as above — missing the return type. Should be `Callable[[list[ndarray]], float]` (or whatever the actual return type is).

- [x] **2.6 `step(self) -> [int, networkx.Graph]` uses a list literal as a type annotation.**
`[int, networkx.Graph]` is not a valid Python type hint — it is a list of type objects. The correct annotation for a two-element return is `tuple[int, networkx.Graph]`.

- [x] **2.7 "methods in common among the base classes" is technically inverted.**
An abstract base class provides methods in common among its *subclasses*, not "among the base classes." Should read: *"…an abstract base class providing methods in common among all subclasses."*

---

## 3. Internal Inconsistencies

- [x] **3.1 `.plat(route=my_route)` in the lifecycle contradicts `plot(self) -> None` in the method list.**
Two compounding problems: (a) `.plat` is a typo for `.plot`; and (b) the lifecycle passes `route=my_route` as a keyword argument, but the declared method signature accepts no parameters. Either the signature must be updated to `plot(self, route=None) -> None`, or the lifecycle description must be corrected.

- [x] **3.2 "A SessionPlanner is instantiated" (Typical Runtime) — class is defined as `PlanningSession` everywhere else.**
"SessionPlanner" appears only in the Typical Runtime section and matches no class name defined elsewhere. This would cause a code generator to produce an inconsistently named or broken implementation.

- [x] **3.3 `RoutePlanner` constructor accepts `cost_func` directly, but operational behavior says to retrieve it from `PlanningSession`.**
The constructor defines `cost_func: Callable[list[ndarray]]` as an explicit constructor parameter, while the operational behaviors section says *"the RoutePlanner subclass will call [the session's] methods to obtain the cost_func."* Both cannot be the authoritative source. This contradiction must be resolved — either cost_func comes from the session (and should be removed from the constructor), or it is an override/substitution mechanism that must be explicitly documented.

- [x] **3.4 `async plan(...) -> None` contradicts "the promise for which is returned and can be tested for completion."**
An async method declared as returning `None` cannot also return a handle for progress tracking. In Python, to make a coroutine testable for completion, `plan` would need to return an `asyncio.Task` (created via `asyncio.create_task`), or accept a progress queue/event. As written, the lifecycle description and the return type are mutually exclusive.

- [x] **3.5 `PlanningSession` constructor accepts "a route planner subclass" (singular) while the feature list requires multiple planners running in parallel.**
The singular "a" directly contradicts the stated feature of parallel execution for side-by-side comparison. The parameter must accept a `list` of planner subclasses or instances.

- [x] **3.6 `plan` callback type `Callable[BaseMultiGeometry]` is disconnected from the graph output of `step`.**
`step` yields a `networkx.Graph` at each step, but the callback to `plan` receives `BaseMultiGeometry`. There is no described mechanism for converting the graph to a geometry at callback time. The extraction/conversion logic is entirely absent.

---

## 4. Vague or Underspecified Requirements

- [-] **4.1 "whatever else you can think of" and "a third that's much more recent, something that's come into use since 2010."**
No algorithm name is given. A code generator will choose arbitrarily and the results will be unpredictable and unreproducible. A specific algorithm should be named (e.g., RRT\*, Theta\*, D\* Lite, Jump Point Search, or Hybrid A\*).

- [x] **4.2 `layer_values(..., layer_num: int = None) -> ndarray` — semantics of `None` are undefined.**
When `layer_num=None`, should all layers be returned as a 2D array? The first layer? An error? The return shape (`(n_layers, )`, `(1,)`, or scalar) is not specified, which will produce non-deterministic implementations.

- [x] **4.3 `map_feats(..., feather: float = 0.0)` — unit and `None` semantics are undefined.**
"Feather" is non-standard GIS terminology for a buffer distance (in raster contexts it typically refers to edge blending/transparency). No unit (meters? degrees?) is specified, and `None` is not defined as meaning "no buffer." Should be renamed (e.g., `buffer_dist_m`) and fully documented.

- [x] **4.4 `plot(self) -> None` — plot content is completely unspecified.**
Does it display the single best route? All candidate routes overlaid with cost coloring? A cost landscape heatmap? A side-by-side comparison of planner outputs? Without this, every code generator will produce something different.

- [x] **4.5 "parallel" execution mechanism is unspecified.**
No concurrency primitive is named: `asyncio.gather`, `concurrent.futures.ThreadPoolExecutor`, `multiprocessing.Pool`, or otherwise. This is an architectural decision that must be specified.

- [x] **4.6 Callback calling convention is entirely unspecified.**
When is `callback` invoked — once on final completion, once per planner, once per `step` iteration, or continuously? What geometry argument does it receive — the final route, a partial path, the union of all planner routes?

- [x] **4.7 "cost_funcs evaluate layer data for a given gps point provided it when called" is ambiguous.**
Who assembles the call? Does the planner call `cost_func(point, layer_data)`, or does the cost function call `session.layer_values(point)` internally? The cost function calling convention is never formally defined.

- [x] **4.8 `destroy(self)` — what is being destroyed is unspecified.**
Are there open file handles (rasterio datasets, pygrib files)? Running async tasks? Background threads? Without knowing what `PlanningSession` constructs internally, the cleanup contract is too vague to implement correctly.

---

## 5. Missing Requirements

- [x] **5.1 No altitude dimension for an aerial vehicle.**
All geometry in the prompt is 2D (`lng`, `lat` only). An aerial route planner must operate in 3D space. Node attributes should include altitude (`alt_m`), and inputs/outputs should carry altitude data. Minimum safe altitude, terrain clearance, and altitude-based cost modeling are all absent.

- [x] **5.2 No-fly zones and restricted airspace are entirely absent.**
These are fundamental hard constraints for any aerial route planner and must be explicitly included — either as a constructor parameter (`no_fly_zones: list[BaseGeometry]`) or as a map-data feature type.

- [ ] **5.3 No waypoint output format or schema is defined.**
The title promises "a Waypoint List" but the output structure is never specified. What type is a waypoint — `shapely.Point` (with Z?), a named dataclass, a dict? What file format, if any, is the export target (MAVLink JSON, GPX, KML)?

- [x] **5.4 No coordinate reference system (CRS) convention is established.**
No CRS is specified for inputs, internal calculations, or outputs. This is critical: buffer operations and distance calculations must be performed in a projected (metric) CRS, while GPS coordinates use WGS84 (EPSG:4326). Without a CRS convention the implementation will silently produce incorrect results.

- [x] **5.5 Search space structure and resolution are entirely unspecified.**
How is the planning space discretized? A uniform lat/lon grid? A graph derived from OSM data? A random sample (as in RRT)? At what resolution? Over what bounding area? These are architectural fundamentals that the prompt omits entirely.

- [ ] **5.6 Multiple planner output comparison is not described.**
"Compare side-by-side" is stated as a goal, but the mechanism is not described. Should results be a `dict[str, list[Waypoint]]` keyed by planner class name? An overlay plot? A ranked table of total path costs?

- [x] **5.7 `.osm.pbf` support is described in Resources but absent from the constructor.**
The Resources section lists `.osm.pbf` files as valid inputs, but the `PlanningSession` constructor only mentions `.fgb` paths and `GeoDataFrame` instances. Either add `.osm.pbf` to the constructor parameter or remove it from Resources.

- [x] **5.8 Raster/GRIB file clipping on load is not specified.**
Resources describes bounding/clipping for vector map files, but an equivalent clipping mechanism for (potentially large) grib and GeoTIFF inputs is never mentioned.

- [x] **5.9 Resolution of non-Point start/end geometries is not specified.**
If the start zone is a `Polygon`, how does the planner determine a concrete origin point? Centroid? Nearest vertex? A sampled set of candidate start points? This is unspecified.

- [x] **5.10 `RoutePlanner` as an ABC is not formally specified.**
No mention is made of `abc.ABC` and `@abstractmethod` decorators. Which methods are abstract (must be overridden)? Which should have concrete default implementations in the base class? Without this, code generators may or may not produce a proper ABC.

- [x] **5.11 Aircraft performance parameters are absent.**
Airspeed, minimum turn radius, climb/descent rate, range/endurance — none are represented. Even a minimal, toy model is needed to prevent generation of physically non-realizable routes (e.g., instantaneous 180° turns, infinite altitude changes).

- [x] **5.12 Error handling and edge cases are completely unspecified.**
What happens when no path exists between start and end? When a grib file is missing or malformed? When `layer_values` is queried for a point outside the raster extent? No exceptions, error codes, or fallback behaviors are defined.

---

## 6. Module List Issues

| _ | Module | Issue |
|---|---|---|
| _ | `kiwisolver` | An internal C extension dependency of matplotlib; it should not be listed as a direct application dependency. Its appearance suggests a `pip freeze` copy-paste. Remove it. |
| _ | `packaging` | No described use case in the prompt. Typically used for version-string parsing in build tooling. Remove it or justify its inclusion. |
| _ | `pygrib` | **Missing from module preferences** despite being the primary Python library for reading grib/grib2 files — which are a named core feature. Should be listed explicitly. |
| _ | `cfgrib` / `xarray` | Common complement to `pygrib` for multidimensional grib/netCDF handling. Absent without justification, and `xarray` is already in `requirements.txt`. |
| _ | `osmnx` | Listed but its role is unexplained. `osmnx` is designed for street/road network retrieval. Its application to open-air aerial routing over arbitrary terrain should be clarified or justified. |
| _ | `requests` | Listed with no described use. Is the planner expected to call external weather APIs or airspace APIs? If so, this is an undocumented feature. |
| _ | `"for path and A* solvers- the most widely used and best maintained modules"` | Vague, non-actionable directive. `networkx` (already listed) provides `networkx.shortest_path` (Dijkstra) and `networkx.astar_path` (A\*). If additional solver packages are intended, name them explicitly. |
| _ | `asyncio` | Not listed, but the `async plan(...)` method requires it. It is stdlib, but its omission from a list that otherwise names low-level utilities is inconsistent. |

---

## 7. Summary of Recommended Additions

To make this a complete and unambiguous code generation prompt, the following additions and corrections are recommended:

- [x] **1. Name all three algorithms explicitly.** Replace "whatever else you can think of" and the misplaced "Euler's method" with concrete names (e.g., Dijkstra's, A\*, and RRT\* or Theta\*). Fix the wording to read "Dijkstra's and A\* as two separate `RoutePlanner` subclasses."

- [x] **2. Add altitude as a first-class dimension.** Require 3D waypoints `(lng, lat, alt_m)`, add `alt_m` to node attributes, and specify terrain-clearance constraints.

- [x] **3. Define the waypoint output schema.** Specify the type (e.g., `@dataclass Waypoint(lng, lat, alt_m, cost)`), the list type returned, and any export format (GPX, KML, MAVLink JSON).

- [x] **4. Fix all `Callable` type hints.** Rewrite as `Callable[[ArgType, ...], ReturnType]` throughout, and define the cost function's exact signature, e.g. `Callable[[shapely.Point, np.ndarray], float]`.

- [x] **5. Fix `cost_func(self) -> float`.** Change the return type to `Callable[[shapely.Point, np.ndarray], float]` to make it a proper getter returning the callable.

- [x] **6. Fix `step` return type.** Change `[int, networkx.Graph]` to `tuple[int, networkx.Graph]`.

- [x] **7. Change the planner constructor parameter to a list.** Use `planner_classes: list[type[RoutePlanner]]` to support the parallel execution requirement.

- [x] **8. Specify the concurrency model.** For example: *"Run each `RoutePlanner` concurrently using `asyncio.gather` within the `plan` coroutine, with results collected per planner."*

- [x] **9. Fix `plan`'s return and progress contract.** Either change the return type to `asyncio.Task` (so callers can await or test completion), or add a `progress: asyncio.Queue` parameter for step-level progress events.

- [ ] **10. Fix `plot` method signature.** Add a `route` parameter to match the lifecycle description, and specify what is plotted (e.g., all routes overlaid, cost-colored, with start/end markers).

- [ ] **11. Add a `no_fly_zones` parameter to `PlanningSession`.** Accept `list[BaseGeometry]` representing airspace restrictions.

- [x] **12. Specify search space resolution and bounds.** For example: *"Construct a grid over the bounding box of start + end + margin at a configurable resolution in meters."*

- [x] **13. Establish CRS convention.** For example: *"Public APIs accept and return WGS84 (EPSG:4326); distance and buffer calculations must reproject to the appropriate UTM zone."*

- [x] **14. Rename `feather` → `buffer_dist_m`** and document its units and the meaning of `None`.

- [x] **15. Add `pygrib` (and optionally `cfgrib`/`xarray`) to module preferences;** remove `kiwisolver` and `packaging`.

- [x] **16. Formally specify the `RoutePlanner` ABC.** Identify which methods are `@abstractmethod` and which have concrete default implementations in the base class.

- [x] **17. Align `.osm.pbf` support** — add it to the constructor file-list parameter, or remove it from Resources.

- [x] **18. Add error handling requirements.** For example: define a `NoPathFoundError` exception; specify fallback behavior for out-of-bounds `layer_values` queries; specify what happens if a GRIB file is missing or unreadable.
