
# Aerial Route Planner producing a Waypoint List, in Python 3.11+ 

## Summary & overall prompt
Implement an aerial vehicle route planning system that generates a list of waypoints which result from evaluating possible edge paths, determining the cost of those paths, and delivering the list of least cost paths. Refer to prompts/plan-costFunctionPipeline.prompt.md for a detailed workup of how edge cost and graph of potential paths is to be calculated and managed.  Incorporate existing work in src/*.py

You may specify new modules+versions, and version changes for existing modules.  Generate code to accomplish this prompt.  Update requirements.txt as needed, but do not use pip to modify the venv -I will managed them.

Generate smoke tests, plus an example main() which exercises the full system and prints the produced waypoints list, and saves a png of the passed map.  All coordinates in this section are in (longitude, latitude) order.
  - Mission plan is to fly:
    - from: FlightPoint(Point(-122.29120393435966, 37.985653198087924), altitude_m=50, heading_deg=0.0, airspeed_mps=0.0),  
    - to: FlightPoint(Point(-121.60898943472321, 37.654702833452426), altitude_m=100, heading_deg=180.0, airspeed_mps=0.0)
    - Map: osm/norcal-260410.osm.pbf.fgb
    - bbox: constrained to bbox(-122.36581181660316, 38.01772638122616, -121.76274978462865, 37.74053331132046)
    - layers for the smoke test and demo:
      - terrain elevation using SRTM geotiff: /home/kev/projs/thucy/nav/top/norcal/output_SRTMGL1.tif (downloaded from https://portal.opentopography.org/)
      - population: /home/kev/projs/thucy/nav/pop/get_wp_global/rasters/R2025A/2026/USA_States/CA/ca_pop_2026_CN_100m_R2025A_v1.tif (downloaded from https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2026/USA_States/CA/v1/100m/constrained/ca_pop_2026_CN_100m_R2025A_v1.tif)
      - solar luminance: : sol/World_PVOUT_GISdata_LTAy_AvgDailyTotals_GlobalSolarAtlas-v2_GEOTIFF/PVOUT.tif
    - uav_spec=...
      ```
          UAVSpec(
            max_airspeed_mps=25.7,
            cruising_speed_mps=18.0,
            stall_speed_mps=9.0,
            min_turn_radius_m=120.0,
            max_bank_angle_deg=35.0,
            climb_rate_mps=4.0,
            descent_rate_mps=3.0,
            max_range_m=80_000,
            battery_capacity_wh=1200.0,
            mass_kg=5.5,
            motor_efficiency=0.80,
            drag_coeff=0.035,
            has_vtol=True,
          )
      ```

Comment code with brevity, and not where the comment states the obvious.  Hold back on docstrings for functions and methods, because this code will continue to be modified, and I'll generate them once a stable release has been reached.

## Features
- Makes use of modern route planning algorithms and modules; based upon recommendations from Claude in file prompts/route_planner_algo_candidates_v2.md ("Algo Candidates Doc" in prompts/route_planner_algo_candidates_v2.md), incorporating factors from there, see below for concrete route planner subclasses to implement
- Coordinate reference systems (CRS) to use: WGS84 (EPSG:4326) for gps coordinates, and metric for all else
- Allow more than one implementation of path evaluators (aka route planners), and allow them to be executed & utilized in parallel, so that each one's results can be compared side-by-side, with the followng implementation notes-
  - use joblib for parallel processing
  - follow prompts/plan-layerStoreMemoryStrategy.prompt.md and use src/layer_store.py, adapting it as needed to the outcome of this prompt
- LayerStore is indexed by a string label per layer.  "terrain" will retrieve be the SRTM topo geotiff
- Implement route planner code in classes that subclass an abstract base class providing methods in common among the subclasses. Route planner class constructors accept a reference to a route planning session instance (below). Call the base class RoutePlanner, and subclasses will be named for the specific algorithm they implement, e.g. RoutePlannerDijkstras, RoutePlannerRRT
  - RoutePlanner the base class will itself subclass from abc.ABC, and have instance methods:
    - `__init__` (stores session, sets `_step_nr = 0`, initialises `self._graph` as session.grid.graph.copy())
    - `_increment_step()`
    - `to_gdfs()`:
      ```python
      def to_gdfs(self) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
        """Return (nodes_gdf, edges_gdf) for the current planning graph."""
    - `step()` and `plan()` should be marked `@abstractmethod`
    - for example-
    ```python
    @abstractmethod
def plan(self) -> networkx.MultiDiGraph:
    """Run the algorithm to completion and return the final graph."""
    ```
- Implement an edge cost planning pipeline as a class, call it EdgeCostPipeline, base its code on prompts/plan-costFunctionPipeline.prompt.md, the current edge cost calculation plan.  It needs to use PlanningSession to provide geotiff/grib resources and a OSM-PBF->FGB map. Use src/cost_model.py. PlanningSession accepts a cost_model: CostModel parameter. The default is DefaultCostModel(). Do not implement EdgeCostPipeline."

- use class FlightPoint in src/flight_point.py wherever flight points are to be used
- Route planning session class (PlanningSession)
  - acts as the coordinator for and runtime context provider to RoutePlanner subclasses
  - constructor parameters:
    - a list of route planner subclasses (to be instantiated by the session class)
    - start and end locations, each an instance of FlightPoint, so that anything from a Point to complex shapes can be specified as potential takeoff and landing zones, including longitude, latitude, altitude, heading and airspeed.  (Define a class to encapsulate these five parameters.)  For objects more complex than a Point, Planner will first obtain and use the lng/lat of its centroid or geometric center point. All objects for start and end location will use gps coordinates
    - cost_model: CostModel = DefaultCostModel()
    - a list of one or more .fgb file paths and/or gpd.GeoDataFrame instances, for accessing map features at arbitrary points along the paths being probed by the path evaluators / route planners, each map in a tuple with a bounding box (defined as gpd.GeoSeries([shapely.Point(lon0, lat0), shapely.Point(lon1, lat1)]))
    - a list of one or more grib, grib2 and/or geotiff files, each providing data which will be used by the cost function/evaluators/planners, each provided as a tuple paired with a bounding box (defined as gpd.GeoSeries([shapely.Point(lon0, lat0), shapely.Point(lon1, lat1)]))
    - no_fly_zones: List[GeoDataFrame|BaseGeometry]  # to be utilised by the planner edge cost pipeline
    - grid_resolution_m: float = 100.0
    - max_grid_nodes: int = 50_000
    - uav_spec: UAVSpec # instance
    - uav_state: UAVState # instance
    - grid_margin_m: float = 5_000.0  # expands the bbox: add grid_margin_m to all four sides of bbox after converting to the local AEQD frame
  - PlanningSession.__init__:
    - builds a `networkx.MultiDiGraph` grid over `bbox(start, end, margin)` at `grid_resolution_m` spacing, capped at `max_grid_nodes`, and stores it as `self._grid`.
      ```python
      self.grid = PlanningGrid.build(
        bbox=..., resolution_m=grid_resolution_m, max_grid_nodes=max_grid_nodes,
        layers=..., terrain_layer=LAYER_TERRAIN)
      ```
    - Each `RoutePlanner.__init__` receives has access session.grid.graph (the raw MultiDiGraph). 
)
  - instance methods: 
    - start(self) -> FlightPoint  # getter
    - end(self) -> FlightPoint  # getter
    - map_feats(self, area: BaseGeometry, buffer_dist_m: float = 50.0) -> gpd.GeoDataFrame # where `isinstance(area, Point) == True and buffer_dist_m == 0` raises an exception due to the low probability that anything will be at that point, and to push the caller to make use of a more complex BaseGeometry that specifies an area, wherein the likelihood of intersecting map features will be higher 
    - layer_values(self, pt: shapely.geometry.Point, `layer: str | None = None`): # if layer=`None`; → shape `(n_layers,)` (refer to prompts/plan-layerStoreMemoryStrategy.prompt.md for more detail about layers)
    - dispatch_step(self, callback: Callable[[int, networkx.MultiDiGraph, type[RoutePlanner]], None] = None) -> None  #where RoutePlanner being a type serves to indicate to caller/consumer from which planner the graph came. When callback == None, use joblib.Parallel
      - pseudocode
        ```python
  for planner in self._planners:
      step_nr, graph = planner.step()
      callback(step_nr, graph, planner.__class__)
        ```
    - plan_all(self) -> dict[type[RoutePlanner], networkx.MultiDiGraph]  # returns dict keyed by RoutePlanner subclass ref, values the completed graph
    - plan_all_from(self, start_point: FlightPoint) -> Dict[type[RoutePlanner], networkx.MultiDiGraph]  # returns dict keyed by RoutePlanner class object, not an instance, used just as an identifier of which planner produced the MultiDiGraph. This method provides a way to regenerate the graph(s) from a new FlightPoint, potentially after graphs have already been produced, meaning repeating an aspect of the lifecycle prior to destruction. 
    - plot(self) -> None: display all the contained RoutePlanners' current .plan_all() MultiDiGraph overlaid on the map
    - destroy(self) -> None: performs orderly destruction and shutdown of the class, setting internal instance vars to None to eliminate ref counts for objects constructed during its lifecycle, closing all open filehandles (maps, rasterio datasets e.g. geotiffs, gribs), setting all self.attribs = None to release refcounts, and waits for any active joblib `Parallel` workers by allowing the context manager to exit; sets all instance attributes to `None`.
  - life cycle & additional behaviors: 
    - instantiated for a single planning session
    - .step(my_callbaack)
    - .plot() can be optionally invoked to display the route using matplotlib
    - .destroy()
    - Run each `RoutePlanner` concurrently using `joblib`, with results collected per planner.
- Route Planner class (RoutePlanner subclass)
  - constructor parameters:
    - session: PlanningSession
  - instance methods:
    - step(self) -> tuple[int, networkx.MultiDiGraph]: where int is the step number performed (maintained/iterated internal to the route planner base class or subclass), and the Graph instance is a ref to the graph built thus far (as of step int), where each node has lng, lat, cost and path_aggregate_cost attribs, where each end node's path_aggregate_cost is the sum of costs of itself and all nodes leading to it from the start point
  - operational behaviors:
    - with the PlanningSession instance provided at construction time, the RoutePlanner subclass will call its methods to obtain the cost_func, retrieve map features (.map_feats) and layer values (.layer_values) and use them to perform the cost_func's evaluation work.
    - cost_funcs are passed necessary data layers and map areas needed to perform evaluation / estimation / cost calculation for the given gps point, altitude, heading and airspeed provided when called, and has access to the intrinsic status variables of the vehicle
    - terrain is always a requirement
    - a continual awareness of the hard deck indicated by the terrain map must be kept "in mind" at all times while planning waypoints, descents and ascents. Eventually 3D building outlines will be added as additional data, though not in this iteration.
  - life cycle:
    - forward-moving, reversible or reroutable when the underlying planner module supports it - when .step(...) is called it produces a navigation waypoint recommendation for the next time point
  - Route Planner subclasses to be implemented, as described in Tier 1 in Algo Candidates Doc v2:
    1. Dijkstra's algorithm as a baseline for correctness comparison
    2. A* with geodesic heuristic
    3. ARA* — Anytime Repairing A*
    4. D* Lite
- Additional classes:
  - UAVSpec class: performance characteristics of the UAV being planned for
  - UAVState class: current state of the UAV during route-planning
  - For both UAVSpec and UAVState, import these classes, do not re-implement them:
     - Add `from src.uav_spec import UAVSpec` and `from src.uav_state import UAVState` to the module's imports and remove them from the class list to be generated
  - class NoPathFoundError(RuntimeError): ...  # to be raised when planner exhausts the search space** and no route exists between start and end.
  - Planner graph nodes need attributes which vary according to planner implementation; create a base @dataclass with subclasses matching each route planner subclass
    - Dijkstra's algorithm
    - D\* Lite requres g and rhs
    - ARA\* requires an epsilon tag
    - shared attribs: lng, lat, cost, path_aggregate_cost
  - Waypoint dataclass: based this upon the "items" objects from the Waypoint JSONSchema below.  Add to_json() and save_as(pathname) methods

## Typical runtime
A PlanningSession is instantiated and provided with the lists of things it needs, and then the life cycle is followed. 

## Resources
- environmental data available from grib, grib2, geojson, geotiff files and others, the values at lng/lat points within which will be used to produce a cost function result per potential waypoint
  - such data may include:
    - population
    - solar luminance
    - topography (terrain elevation)
    - no-fly zones, notams, restricted airspace: these will be specified as BaseGeometry boundaries
    - noise levels
    - recommend any additional data you think will be helpful
- intrinsic/implicit status variables & parameters to route planning:
  - current location lng/lat, altitude, airspeed, heading
  - current ambient temperature
  - current pitot tube readings (if the sensor is available), telling of headwind, tailwind, lateral winds -all if which may affect travel efficiency and battery drain rate
  - remaining battery charge
  - solar PV in-flight charge rate, and how that may extend battery life
  - distance to next recharge layover
  - continuously updated estimated electrical current required to complete leg to recharge layover, and the amount of cruise flying time it provides  
  - probability that remaining battery charge will enable vehicle to reach the next waypoint / recharge layover / mission objective & terminus
  - notify if you think of any parameters I've missed here
- static or unchanging characteristics of the UAV:
  - cruising speed
  - minimum turn radius
  - climb and descent rate
  - max range on fully charged battery 
- map data available from .fgb files (converted from .osm.pbf files typically), wherein waypoints, stop-and-rest points and terminus, may be chosen based upon map features selected based on criteria as well as environmental factors
  - map file inputs should be provided with bbox or BaseGeometry objects for clipping the map file on load, to limit to both potential mission area and to reduce memory consumed by unneeded map data
- for example, if a route is to be planned for which the cost_func wants to avoid areas with population and fly over farmland, it should be able to make that happen based on the data layers provided, but the combination of data layers and cost_func is up to the invoker of course
- Search space structure and resolution will vary according to data available at runtime.  Obtain sub-pixel samples with `dataset.sample([(x, y)])` or
  `rasterio.sample.sample(dataset, xy)`, if this works best. But for true sub-pixel bilinear interpolation use `scipy.ndimage.map_coordinates` if the array is  pre-loaded, or `rasterio.warp.reproject` to a finer grid.

- Error handling: log non-fatal exceptions such as warnings, log information that will be useful for debugging, and catch and log fatal exceptions then reraise them
- Runtime facts:
  - Human will maintain virtual Python environments, PYTHONPATH, and the obtainment of resources from the web (geotiffs, PBFs, FGBs)
  - LLM will learn about system parameters at runtime: CPU cores, RAM, disk space (if it becomes relevant)
- Generated Waypoint output list as JSON schema:
  ```JSON
  {
    "type": "array",
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "description": "",
    "minItems": 1,
    "uniqueItems": false,
    "items": {
      "type": "object",
      "required": [
        "id",
        "planner",
        "longitude",
        "latitude",
        "altitude_m",
        "airspeed_mps",
        "heading_deg",
        "action",
        "eta_unix_ms",
        "battery_soc_est",
        "cost",
        "path_aggregate_cost"
      ],
      "properties": {
        "id": {
          "type": "integer",
          "description": "Correlates with the networkx node key"
        },
        "planner": {
          "type": "string",
          "description": "Name of the Python class which produced this waypoint list"
        },
        "longitude": {
          "type": "number"
        },
        "latitude": {
          "type": "number"
        },
        "altitude_m": {
          "type": "number"
        },
        "airspeed_mps": {
          "type": "number"
        },
        "heading_deg": {
          "type": "number"
        },
        "action": {
          "enum": ["takeoff", "cruise", "loiter", "holding", "turning", "recharge_stop", "rtl", "land"]     
        },
        "eta_unix_ms": {
          "type": "number"
        },
        "battery_soc_est": {
          "type": "number"
        },
        "cost": {
          "type": "number" 
        },
        "path_aggregate_cost": {
          "type": "number"
        }
      }
    }
  }
    ```

## Python module preferences (besides route planner packages)
- geopandas, pandas
- shapely
- rasterio
- numpy
- osmnx
- packaging
- networkx
- requests
