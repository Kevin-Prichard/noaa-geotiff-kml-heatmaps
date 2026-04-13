Critique the following code generation prompt, without actually executing on it or generating code. Produce a markdown document explaining what's missing, what's incorrect, vague, misspelled, and what can be added to make it complete per the overall intent of the prompt. Place the critique in a markdown file with a new and unique name, and format each issue needing my attention with a checkbox in front.  If part of a numbered list, formatted as: "- [ ] **N.M <summary>** <detail>" where "N" is the current section number and ".M" is the current item number within the section.  Refer to "route_planner_critique.md" for an example of the updated format.

If you think of or find a better class design pattern / structure than what I've layed out here, please write a section about that.

# Aerial Route Planner producing a Waypoint List, in Python 3.11+ 

## Summary & overall prompt
Implement in waypoints.py an aerial vehicle route planning system that generates a list of waypoints which result from evaluating possible paths, determining the cost of those paths, and delivering the list of least cost paths.

## Features
- Makes use of modern route planning algorithms and modules; based upon recommendations from Claude in file prompts/route_planner_algo_candidates_v2.md ("Algo Candidates Doc" in prompts/route_planner_algo_candidates_v2.md), incorporating factors from there, see below for concrete route planner subclasses to implement
- Coordinate reference systems (CRS) to use: WGS84 (EPSG:4326) for gps coordinates, and metric for all else
- Allow more than one implementation of path evaluators (aka route planners), and allow them to be executed & utilized in parallel, so that each one's results can be compared side-by-side, with the followng implementation notes-
  - 
- Implement route planner code in classes that subclass an abstract base class providing methods in common among the subclasses. Route planner class constructors accept a reference to a route planning session instance (below). Call the base class RoutePlanner, and subclasses will be named for the specific algorithm they implement, e.g. RoutePlannerDijkstras, RoutePlannerRRT
  - RoutePlanner the base class will itself subclass from abc.ABC, and all of its instance methods will be marked with @abstractmethod
- Implement a cost functions which avoids population areas and prefers to fly over farmers' fields, based on PlanningSession providing a geotiff/grib resource for population and a OSM-PBF->FGB map, more details follow
- Route planning session class (PlanningSession)
  - acts as the coordinator for and runtime context provider to RoutePlanner subclasses
  - constructor parameters:
    - a list of route planner subclasses (to be instantiated by the session class)
    - start and end locations, each an instance of shapely's BaseGeometry, so that anything from a Point to complex shapes can be specified as potential takeoff and landing zones, including longitude, latitude, altitude, heading and airspeed.  (Define a class to encapsulate these five parameters.)  For objects more complex than a Point, Planner will first obtain and use the lng/lat of its centroid or geometric center point. All objects for start and end location will use gps coordinates
    - a cost function, which will be available to be used by those route planner classes that need one
      - i.e. cost_func: Callable[[list[ndarray]], float]
    - a list of one or more .fgb file paths and/or gpd.GeoDataFrame instances, for accessing map features at arbitrary points along the paths being probed by the path evaluators / route planners, each map in a tuple with a bounding box (defined as gpd.GeoSeries([shapely.Point(lon0, lat0), shapely.Point(lon1, lat1)]))
    - a list of one or more grib, grib2 and/or geotiff files, each providing data which will be used by the cost function/evaluators/planners, each provided as a tuple paired with a bounding box (defined as gpd.GeoSeries([shapely.Point(lon0, lat0), shapely.Point(lon1, lat1)]))
  - instance methods: 
    - start(self) -> BaseGeometry
    - end(self) -> BaseGeometry
    - map_feats(self, area: BaseGeometry, buffer_dist_m: float = 0.0) -> gpd.GeoDataFrame
    - layer_values(self, pt: shapely.geometry.Point, layer_num: int) -> ndarray
    - planStep(self) -> Iterator[tuple[int, networkx.MultiDiGraph, RoutePlanner]]: where RoutePlanner being a type serves to indicate to caller/consumer from which planner the graph came
      ```
      for planner in self._planners:
        step_nr, graph = a_planner.step()
          yield step_nr, graph_so_far, planner.__class__
      ```
    - planAll(self) -> dict[RoutePlanner, networkx.MultiDiGraph]  # returns dict keyed by RoutePlanner subclass ref, values the completed graph
    - planAllFrom(self, start_point: shapely.BaseGeometry) -> Dict[RoutePlanner, networkx.MultiDiGraph]  # returns dict keyed by RoutePlanner class object, not an instance, used just as an identifier of which planner produced the MultiDiGraph
    - plot(self, route) -> None: display all the contained RoutePlanners' current .planAll() MultiDiGraph overlaid on the map
    - destroy(self) -> None: performs orderly destruction and shutdown of the class, setting internal instance vars to None to eliminate ref counts for objects constructed during its lifecycle, closing all open filehandles (maps, rasterio datasets e.g. geotiffs, gribs), setting all self.attribs = None to release refcounts, and awaits or joins any currently outstanding asyncio coroutines 
  - life cycle & additional behaviors: 
    - instantiated for a single planning session
    - .planStep()
    - .plot() can be optionally invoked to display the route using matplotlib
    - .destroy()
    - Run each `RoutePlanner` concurrently using `joblib` within the `plan` coroutines, with results collected per planner.
- Route Planner class (RoutePlanner subclass)
  - constructor parameters:
    - session: PlanningSession
  - instance methods:
    - step(self) -> tuple[int, networkx.Graph]: where int is the step number performed (maintained/iterated internal to the route planner base class or subclass), and the Graph instance is a ref to the graph built thus far (as of step int), where each node has lng, lat, cost and path_aggregate_cost attribs, where each end node's path_aggregate_cost is the sum of costs of itself and all nodes leading to it from the start point
  - operational behaviors:
    - with the PlanningSession instance provided at construction time, the RoutePlanner subclass will call its methods to obtain the cost_func, retrieve map features (.map_feats) and layer values (.layer_values) and use them to perform the cost_func's evaluation work.
    - cost_funcs are passed necessary data layers and map areas needed to perform evaluation / estimation / cost calculation for the given gps point, altitude, heading and airspeed provided when called, and has access to the intrinsic status variables of the vehicle
  - life cycle:
    - forward-moving, not reversible - when .step(...) is called it produces a navigation waypoint recommendation for the next time point
  - Route Planner subclasses to be implemented, as described in Tier 1 in Algo Candidates Doc v2:
    1. A* with geodesic heuristic
    2. ARA* — Anytime Repairing A*
    3. D* Lite

## Typical runtime
A PlanningSession is instantiated and provided with the lists of things it needs, and then the life cycle is followed. 

## Resources
- environmental data available from grib, grib2, geojson, geotiff files and others, the values at lng/lat points within which will be used to produce a cost function result per potential waypoint
  - such data may include:
    - population
    - solar luminance
    - topography (terrain elevation)
    - no-fly zones, notams, restricted airspace
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
- Search space structure and resolution will vary according to data available at runtime.  rasterio data formats seem to account for this by returning grid values for decimal lng/lat regardless of resolution, but correct me on this if needed
- Error handling: log non-fatal exceptions such as warnings, log information that will be useful for debugging, and catch and log fatal exceptions then reraise them
- Generated Waypoint output list as JSON schema:
  {
  "type": "array",
  "$schema": "http://json-schema.org/draft-04/schema#",
  "description": "",
  "minItems": 1,
  "uniqueItems": true,
  "items": {
    "type": "object",
    "required": [
      "longitude",
      "latitude",
      "altitude_m",
      "airspeed_ms",
      "heading",
      "action",
      "eta_ms"
    ],
    "properties": {
      "longitude": {
        "type": "number"
      },
      "latitude": {
        "type": "number"
      },
      "altitude_m": {
        "type": "number"
      },
      "airspeed_ms": {
        "type": "number"
      },
      "heading": {
        "type": "number"
      },
      "action": {
        "type": "string",
        "minLength": 1
      },
      "eta_ms": {
        "type": "number"
      }
    }
  }
}

## Education
- Discuss how cost functions work.  With all the possible inputs, is "cost" an accurate description still?  The cost becomes an aggregate of positive and negative factors, but is a simple one-dimensional sum the right way to go?  Do planner algos consider each factor separately?  For example-
  - population: for avoiding populated areas, population would increase cost and cause the planner to steer around, correct?
  - solar luminance: a desired landing point for recharge layovers, so areas with better luminance are an attractor, and the path to get there would seem to need a lower cost in order to get to "life saving" sunshine for recharging the battery, even though some or all of that path might have a higher than desired cost given other parameters and factors
  - topography: this would affect climb and descent control, not necessarily a cost factor, except climbing would add to electricity and time costs, I suppose?

## Python module preferences (besides route planner packages)
- geopandas, pandas
- shapely
- rasterio
- numpy
- osmnx
- packaging
- networkx
- requests
