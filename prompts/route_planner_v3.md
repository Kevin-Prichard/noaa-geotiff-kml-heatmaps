Critique the following code generation prompt, without actually executing on it or generating code. 

Produce a markdown document explaining what's missing, what's incorrect, inconsistent, vague, unworkable, misspelled, and what can be added to make it complete per the overall intent of the prompt. Place the critique in a markdown file with a new and unique name (prompts/route_planner_critique_v3.md), and format each issue needing my attention with a checkbox in front.  If part of a numbered list, formatted as: "- [ ] **N.M <summary>** <detail>" where "N" is the current section number and ".M" is the current item number within the section.  Refer to "route_planner_critique_v2.md" for an example of the updated format.  Refer to files *.py, src/*.py and prompts/*.md.  You may exclude points which have already been covered in previous critique MD docs, to improve brevity for the human reader.

If you think of or find a better class design pattern / structure than what I've layed out here, please write a section about that.  You may offer alternatives within OOD/OOP if you develop a strong enough opinion about a better way to do it, but as a sidebar, bc mainly I want you to stick to the plan I've laid out as that's what's familiar to me.

# Aerial Route Planner producing a Waypoint List, in Python 3.11+ 

## Summary & overall prompt
Implement an aerial vehicle route planning system that generates a list of waypoints which result from evaluating possible edge paths, determining the cost of those paths, and delivering the list of least cost paths. Refer to prompts/plan-costFunctionPipeline.prompt.md for a detailed workup of how edge cost and graph of potential paths is to be calculated and managed.  Incorporate existing work in src/*.py

You may specify new modules+versions, and version changes for existing modules.  Generate code to accomplish this prompt.  Update requirements.txt as needed, but do not use pip to modify the venv -I will managed them.

Generate smoke tests, plus an example main() which exercises the full system and prints the produced waypoints list, and saves a png of the passed map.  All coordinates in this section are in (longitude, latitude) order.
  - Mission plan is to fly:
    - from: -122.29120393435966, 37.985653198087924
    - to: -121.60898943472321, 37.654702833452426
    - Map: [norcal-260410.osm.pbf.fgb](../osm/norcal-260410.osm.pbf.fgb)
    - bbox: constrained to bbox(-122.36581181660316, 38.01772638122616, ).  
    - layers for the smoke test and demo:
      - terrain elevation using SRTM geotiff: /home/kev/projs/thucy/nav/top/norcal/output_SRTMGL1.tif (downloaded from https://portal.opentopography.org/)
      - population: /home/kev/projs/thucy/nav/pop/get_wp_global/rasters/R2025A/2026/USA_States/CA/ca_pop_2026_CN_100m_R2025A_v1.tif (downloaded from https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2026/USA_States/CA/v1/100m/constrained/ca_pop_2026_CN_100m_R2025A_v1.tif)
      - solar luminance: : ![PVOUT.tif](../sol/World_PVOUT_GISdata_LTAy_AvgDailyTotals_GlobalSolarAtlas-v2_GEOTIFF/PVOUT.tif)

## Features
- Makes use of modern route planning algorithms and modules; based upon recommendations from Claude in file prompts/route_planner_algo_candidates_v2.md ("Algo Candidates Doc" in prompts/route_planner_algo_candidates_v2.md), incorporating factors from there, see below for concrete route planner subclasses to implement
- Coordinate reference systems (CRS) to use: WGS84 (EPSG:4326) for gps coordinates, and metric for all else
- Allow more than one implementation of path evaluators (aka route planners), and allow them to be executed & utilized in parallel, so that each one's results can be compared side-by-side, with the followng implementation notes-
  - use joblib for parallel processing
  - follow plan-layerStoreMemoryStrategy.prompt.md and use src/layer_store.py, adapting it as needed to the outcome of this prompt
- Implement route planner code in classes that subclass an abstract base class providing methods in common among the subclasses. Route planner class constructors accept a reference to a route planning session instance (below). Call the base class RoutePlanner, and subclasses will be named for the specific algorithm they implement, e.g. RoutePlannerDijkstras, RoutePlannerRRT
  - RoutePlanner the base class will itself subclass from abc.ABC, and have instance methods:
    - `__init__` (stores session, sets `_step_nr = 0`, initialises `self._graph`)
    - `_increment_step()`
    - `to_gdfs()`
    - `step()` and `plan()` should be marked `@abstractmethod`
- Implement an edge cost planning pipeline as a class, based on prompts/plan-costFunctionPipeline.prompt.md, the current edge cost calculation plan.  It needs to use PlanningSession to provide geotiff/grib resources and a OSM-PBF->FGB map
- Define a class FlightPoint with the following attributes, to use whenever referring to an aircraft's current basic physics variables:
  - _position: BaseGeometry  # which will most often be a Point, or in 
  - _altitude: float
  - _heading: float
  - _airspeed_mps: float
  - add getters and setters, and for instance method BaseGeometry.position() check whether self._position is a Point, immediately returnable, or a more complex geometry and then obtain its centroid or centerpoint (depending on the class)
- Route planning session class (PlanningSession)
  - acts as the coordinator for and runtime context provider to RoutePlanner subclasses
  - constructor parameters:
    - a list of route planner subclasses (to be instantiated by the session class)
    - start and end locations, each an instance of FlightPoint, so that anything from a Point to complex shapes can be specified as potential takeoff and landing zones, including longitude, latitude, altitude, heading and airspeed.  (Define a class to encapsulate these five parameters.)  For objects more complex than a Point, Planner will first obtain and use the lng/lat of its centroid or geometric center point. All objects for start and end location will use gps coordinates
    - a cost function or class instance object, which will be available to be used by those route planner classes that need one
    - a list of one or more .fgb file paths and/or gpd.GeoDataFrame instances, for accessing map features at arbitrary points along the paths being probed by the path evaluators / route planners, each map in a tuple with a bounding box (defined as gpd.GeoSeries([shapely.Point(lon0, lat0), shapely.Point(lon1, lat1)]))
    - a list of one or more grib, grib2 and/or geotiff files, each providing data which will be used by the cost function/evaluators/planners, each provided as a tuple paired with a bounding box (defined as gpd.GeoSeries([shapely.Point(lon0, lat0), shapely.Point(lon1, lat1)]))
    - no_fly_zones: List[ndarray|GeoDataFrame|BaseGeometry]  # to be utilised by the planner edge cost pipeline
    - grid_resolution_m: float = 100.0
    - max_grid_nodes: int = 50_000
  - instance methods: 
    - start(self) -> FlightPoint  # getter
    - end(self) -> FlightPoint  # getter
    - map_feats(self, area: BaseGeometry, buffer_dist_m: float = 0.0) -> gpd.GeoDataFrame # where isinstance(area, Point) == True raises an exception
    - layer_values(self, pt: shapely.geometry.Point, `layer_num: int | None = None`): # if layer_num=`None` → shape `(n_layers,)` (refer to prompts/plan-layerStoreMemoryStrategy.prompt.md for more detail about layers)
    - step(self, callback: Callable[tuple[int, networkx.MultiDiGraph, RoutePlanner]]) -> None  #where RoutePlanner being a type serves to indicate to caller/consumer from which planner the graph came
      - pseudocode
        ```
        for planner in self._planners:
          step_nr, graph = a_planner.step()
            yield step_nr, graph_so_far, planner.__class__
        ```
    - planAll(self) -> dict[RoutePlanner, networkx.MultiDiGraph]  # returns dict keyed by RoutePlanner subclass ref, values the completed graph
    - planAllFrom(self, start_point: FlightPoint) -> Dict[RoutePlanner, networkx.MultiDiGraph]  # returns dict keyed by RoutePlanner class object, not an instance, used just as an identifier of which planner produced the MultiDiGraph. This method provides a way to regenerate the graph(s) from a new FlightPoint, potentially after graphs have already been produced, meaning repeating an aspect of the lifecycle prior to destruction. 
    - plot(self) -> None: display all the contained RoutePlanners' current .planAll() MultiDiGraph overlaid on the map
    - destroy(self) -> None: performs orderly destruction and shutdown of the class, setting internal instance vars to None to eliminate ref counts for objects constructed during its lifecycle, closing all open filehandles (maps, rasterio datasets e.g. geotiffs, gribs), setting all self.attribs = None to release refcounts, and awaits or joins any currently outstanding subprocesses
  - life cycle & additional behaviors: 
    - instantiated for a single planning session
    - .step()
    - .plot() can be optionally invoked to display the route using matplotlib
    - .destroy()
    - Run each `RoutePlanner` concurrently using `joblib`, with results collected per planner.
- Route Planner class (RoutePlanner subclass)
  - constructor parameters:
    - session: PlanningSession
  - instance methods:
    - step(self) -> tuple[int, networkx.MutiDiGraph]: where int is the step number performed (maintained/iterated internal to the route planner base class or subclass), and the Graph instance is a ref to the graph built thus far (as of step int), where each node has lng, lat, cost and path_aggregate_cost attribs, where each end node's path_aggregate_cost is the sum of costs of itself and all nodes leading to it from the start point
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
  - UAVSpec class: performance characteristics of the UAV being planned for (see src/uav_spec.py)
  - UAVState class: current state of the UAV during route-planned (see src/uav_state.py)
  - class NoPathFoundError(RuntimeError): ...  # to be raised when a grid or map resource pathname is not found
  - Planner graph nodes need attributes which vary according to planner implementation; create a base @dataclass with subclasses matching each route planner subclass
    - Dijkstra's algorithm
    - D\* Lite requres g and rhs
    - ARA\* requires an epsilon tag
    - shared attribs: lng, lat, cost, path_aggregate_cost
  - Waypoint dataclass: based this upon the "items" objects from the Waypoint JSONSchema below

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
- Search space structure and resolution will vary according to data available at runtime.  Utilize `rasterio.sample.sample_gen` to obtain sub-pixel samples and interpolate.  Make a decision about how to represent grid resolution at runtime

- Error handling: log non-fatal exceptions such as warnings, log information that will be useful for debugging, and catch and log fatal exceptions then reraise them
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
        "longitude",
        "latitude",
        "altitude_m",
        "airspeed_mps",
        "heading",
        "action",
        "eta_unix_ms",
        "battery_soc_est",
        "cost",
        "path_aggregate_cost",     
      ],
      "properties": {
        "id": {
          "type": "number",
          "description": "Correlates with the networkx node key"
        },
        "planner": {
          "type": "string",
          "description": "Name of the Python class which produced this waypoint list"
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
        "heading": {
          "type": "number"
        },
        "action": {
          "enum": ["takeoff", "cruise", "loiter", "turning", "land"]     
        },
        "eta_unix_millis": {
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
