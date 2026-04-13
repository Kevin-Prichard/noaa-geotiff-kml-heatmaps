"""
cost_model.py — CostModel ABC and default implementation.

Architecture (from prompts/plan-costFunctionPipeline.prompt.md):

  Stage 1 — node_cost()    : environmental soft cost at a location (raster lookup).
                              Position-only; vehicle-state-independent; pre-computable.
  Stage 2 — edge_cost()    : physics + energy cost of a transition between two FlightPoints.
                              Includes Dubins arc, wind, climb, and destination node_cost.
  Stage 3 — is_flyable()   : hard binary feasibility gate (terrain, no-fly zones, battery).
                              Applied BEFORE edge_cost; infeasible nodes are pruned entirely.

Planners call ``session.cost_model.edge_cost(...)`` without knowing the implementation.
Different cost models can be swapped in without touching any planner code.

Layer name constants defined here are the canonical string keys used in LayerStore.load().
"""

from __future__ import annotations

import abc
import logging
import math
from typing import TYPE_CHECKING

import numpy as np
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

# Optional runtime dependency — falls back to straight-line distance if absent.
try:
    import dubins as _dubins_lib  # pip install dubins
    _HAS_DUBINS = True
except ImportError:
    _dubins_lib = None  # type: ignore[assignment]
    _HAS_DUBINS = False

if TYPE_CHECKING:
    from src.flight_point import FlightPoint
    from src.layer_store import LayerStore
    from src.uav_spec import UAVSpec
    from src.uav_state import UAVState

logger = logging.getLogger(__name__)

# ── Canonical layer name keys ──────────────────────────────────────────────────
# Use these constants as keys when constructing LayerStore.load({...}) so that
# CostModel subclasses can locate layers by name without magic strings.
LAYER_TERRAIN    = "terrain"      # DEM / elevation (metres)
LAYER_POPULATION = "population"   # population density (persons / km²)
LAYER_SOLAR      = "solar"        # PVOUT solar luminance (kWh/m²/day)
LAYER_LAND_USE   = "land_use"     # land classification raster (optional)

# Default minimum clearance above terrain DEM (metres)
_DEFAULT_TERRAIN_CLEARANCE_M: float = 30.0


# ── Abstract base ──────────────────────────────────────────────────────────────

class CostModel(abc.ABC):
    """
    Abstract base class for all cost models.

    Subclasses must implement:
        - ``node_cost``   — environmental soft cost at a WGS84 point
        - ``edge_cost``   — total cost of transitioning between two FlightPoints
        - ``is_flyable``  — hard feasibility check (True = flyable)

    The separation between hard constraints (``is_flyable``) and soft costs
    (``node_cost``, ``edge_cost``) is intentional: a planner that folds terrain
    clearance into a very large penalty may still route through terrain given a
    sufficiently attractive destination.  Hard filters make it impossible.
    """

    @abc.abstractmethod
    def node_cost(
        self,
        pt: Point,
        layers: "LayerStore",
    ) -> float:
        """
        Soft environmental cost at WGS84 point ``pt``.

        Positive values = penalties (avoid); negative values = attractors (prefer).
        Called by ``edge_cost`` at the destination node, but may also be called
        independently for heatmap visualisation or candidate stop scoring.

        Args:
            pt:     WGS84 Point (EPSG:4326).
            layers: LayerStore with pre-loaded or streaming raster data.
        Returns:
            float cost contribution (unbounded; planners minimise total cost).
        """

    @abc.abstractmethod
    def edge_cost(
        self,
        from_fp: "FlightPoint",
        to_fp:   "FlightPoint",
        uav_state: "UAVState",
        uav_spec:  "UAVSpec",
        layers:    "LayerStore",
    ) -> float:
        """
        Total cost of transitioning from ``from_fp`` to ``to_fp``.

        Combines kinematic/energy costs (Dubins arc, wind, altitude change) with
        the environmental node cost at the destination.

        Args:
            from_fp:   Origin FlightPoint (WGS84, with heading and airspeed).
            to_fp:     Destination FlightPoint.
            uav_state: Live vehicle state (battery, wind, position).
            uav_spec:  Static vehicle specification (turn radius, efficiency, …).
            layers:    LayerStore providing raster data.
        Returns:
            float cost (Wh-equivalent scalar).  Returns ``math.inf`` if the
            transition is physically infeasible (``is_flyable`` fails).
        """

    @abc.abstractmethod
    def is_flyable(
        self,
        fp:          "FlightPoint",
        uav_state:   "UAVState",
        uav_spec:    "UAVSpec",
        layers:      "LayerStore",
        no_fly_zones: list[BaseGeometry] | None = None,
    ) -> bool:
        """
        Hard feasibility gate for a candidate FlightPoint.

        Returns ``False`` (prune) if any hard constraint is violated:
            - Altitude below terrain DEM + clearance margin.
            - Inside a no-fly zone / restricted airspace polygon.
            - Remaining battery cannot reach this point (reach_probability == 0).

        Never raises; logs warnings for near-miss conditions.
        """


# ── Concrete base with physics helpers ────────────────────────────────────────

class BaseCostModel(CostModel):
    """
    Provides concrete ``edge_cost`` and ``is_flyable``; leaves ``node_cost`` abstract.

    ``edge_cost`` formula::

        edge_cost = dubins_arc_energy(from → to)
                  + climb_energy(Δalt)
                  + wind_cruise_energy(segment_length)
                  + node_cost(to_fp.point)      ← subclass-provided

    Subclasses only need to implement ``node_cost`` to produce a fully functional
    cost model with physically correct energy costs.
    """

    def __init__(
        self,
        terrain_layer:       str   = LAYER_TERRAIN,
        terrain_clearance_m: float = _DEFAULT_TERRAIN_CLEARANCE_M,
        no_fly_zones:        list[BaseGeometry] | None = None,
    ) -> None:
        """
        Args:
            terrain_layer:       Key in LayerStore identifying the DEM layer.
            terrain_clearance_m: Minimum AGL clearance above DEM height (metres).
            no_fly_zones:        List of BaseGeometry polygons that are always excluded.
                                 Additional zones can be passed per-call to is_flyable().
        """
        self.terrain_layer       = terrain_layer
        self.terrain_clearance_m = terrain_clearance_m
        self._no_fly_zones       = no_fly_zones or []

    # ── Still abstract ─────────────────────────────────────────────────────────

    @abc.abstractmethod
    def node_cost(self, pt: Point, layers: "LayerStore") -> float: ...

    # ── Concrete implementations ───────────────────────────────────────────────

    def edge_cost(
        self,
        from_fp:   "FlightPoint",
        to_fp:     "FlightPoint",
        uav_state: "UAVState",
        uav_spec:  "UAVSpec",
        layers:    "LayerStore",
    ) -> float:
        if not self.is_flyable(to_fp, uav_state, uav_spec, layers):
            return math.inf

        dubins_e = self._dubins_energy(from_fp, to_fp, uav_state, uav_spec)
        climb_e  = uav_spec.climb_energy_wh(to_fp.altitude_m - from_fp.altitude_m)
        wind_e   = self._wind_cruise_energy(from_fp, to_fp, uav_state, uav_spec)
        env_cost = self.node_cost(to_fp.point, layers)

        total = dubins_e + climb_e + wind_e + env_cost
        logger.debug(
            "edge_cost (%.5f,%.5f)→(%.5f,%.5f): "
            "dubins=%.4f climb=%.4f wind=%.4f env=%.4f  Σ=%.4f Wh",
            from_fp.point.x, from_fp.point.y,
            to_fp.point.x,   to_fp.point.y,
            dubins_e, climb_e, wind_e, env_cost, total,
        )
        return total

    def is_flyable(
        self,
        fp:           "FlightPoint",
        uav_state:    "UAVState",
        uav_spec:     "UAVSpec",
        layers:       "LayerStore",
        no_fly_zones: list[BaseGeometry] | None = None,
    ) -> bool:
        pt = fp.point

        # 1. Terrain clearance (hard floor)
        try:
            terrain_vals = layers.values_at(pt, layer=self.terrain_layer)
            terrain_alt  = float(terrain_vals[0]) if not np.isnan(terrain_vals[0]) else 0.0
            min_alt      = terrain_alt + self.terrain_clearance_m
            if fp.altitude_m < min_alt:
                logger.debug(
                    "is_flyable FAIL terrain: (%.5f,%.5f) alt=%.1f < floor=%.1f",
                    pt.x, pt.y, fp.altitude_m, min_alt,
                )
                return False
        except Exception as exc:
            logger.warning(
                "is_flyable: terrain check error at (%.5f,%.5f): %s", pt.x, pt.y, exc
            )

        # 2. No-fly zones
        all_nfz = (no_fly_zones or []) + self._no_fly_zones
        for zone in all_nfz:
            if zone.contains(pt):
                logger.debug(
                    "is_flyable FAIL no-fly zone at (%.5f,%.5f)", pt.x, pt.y
                )
                return False

        # 3. Battery — prune if zero probability of reaching this point
        if uav_state.reach_probability(fp, uav_spec) <= 0.0:
            logger.debug(
                "is_flyable FAIL battery soc=%.3f cannot reach (%.5f,%.5f)",
                uav_state.battery_soc, pt.x, pt.y,
            )
            return False

        return True

    # ── Physics helpers (shared by all subclasses) ─────────────────────────────

    @staticmethod
    def _great_circle_m(p0: Point, p1: Point) -> float:
        """Great-circle distance in metres between two WGS84 Points."""
        import pyproj
        geod = pyproj.Geod(ellps="WGS84")
        _, _, dist = geod.inv(p0.x, p0.y, p1.x, p1.y)
        return abs(dist)

    @staticmethod
    def _dubins_energy(
        from_fp:   "FlightPoint",
        to_fp:     "FlightPoint",
        uav_state: "UAVState",
        uav_spec:  "UAVSpec",
    ) -> float:
        """
        Energy (Wh) for the minimum-length Dubins arc from ``from_fp`` → ``to_fp``.

        Projects points into a local azimuthal equidistant CRS centred on the
        midpoint so Dubins path lengths are in metres.

        Falls back to straight-line segment energy if the ``dubins`` package
        is not installed (logs a one-time warning).
        """
        import pyproj  # always available; only dubins may be absent

        if _HAS_DUBINS:
            try:
                mid_lon = (from_fp.point.x + to_fp.point.x) / 2
                mid_lat = (from_fp.point.y + to_fp.point.y) / 2
                aeqd_crs = pyproj.CRS.from_proj4(
                    f"+proj=aeqd +lat_0={mid_lat} +lon_0={mid_lon} +units=m"
                )
                t = pyproj.Transformer.from_crs("EPSG:4326", aeqd_crs, always_xy=True)

                x0, y0 = t.transform(from_fp.point.x, from_fp.point.y)
                x1, y1 = t.transform(to_fp.point.x,   to_fp.point.y)

                r  = uav_spec.turn_radius_at(uav_state.airspeed_mps)
                q0 = (x0, y0, math.radians(from_fp.heading_deg))
                q1 = (x1, y1, math.radians(to_fp.heading_deg))
                arc_m = _dubins_lib.shortest_path(q0, q1, r).path_length()  # type: ignore[union-attr]
            except Exception as exc:
                logger.warning("_dubins_energy: dubins path failed (%s); using straight-line.", exc)
                arc_m = BaseCostModel._great_circle_m(from_fp.point, to_fp.point)
        else:
            logger.warning(
                "_dubins_energy: 'dubins' package not installed; "
                "using straight-line distance (add dubins to requirements.txt)"
            )
            arc_m = BaseCostModel._great_circle_m(from_fp.point, to_fp.point)

        wind = uav_state.effective_wind_component_mps()
        return arc_m * uav_spec.cruise_energy_wh_per_m(uav_state.airspeed_mps, wind)

    @staticmethod
    def _wind_cruise_energy(
        from_fp:   "FlightPoint",
        to_fp:     "FlightPoint",
        uav_state: "UAVState",
        uav_spec:  "UAVSpec",
    ) -> float:
        """
        Additional wind-adjusted cruise energy for the straight-line segment.

        Note: ``_dubins_energy`` already includes the arc-length wind cost.
        This term accounts for any straight segment between the Dubins arc
        endpoints and the destination — in practice often zero for short hops
        but non-trivial for long legs where Dubins arc << segment length.
        """
        seg_m = BaseCostModel._great_circle_m(from_fp.point, to_fp.point)
        wind  = uav_state.effective_wind_component_mps()
        return seg_m * uav_spec.cruise_energy_wh_per_m(uav_state.airspeed_mps, wind)


# ── Default implementation ─────────────────────────────────────────────────────

class DefaultCostModel(BaseCostModel):
    """
    Avoids populated areas; prefers farmland and high-solar locations.

    node_cost formula::

        cost = w_pop  × tanh(population / pop_ref)     # penalty  (+)
             − w_sol  × tanh(solar_pvout / solar_ref)  # attractor (−)

    ``tanh`` provides a soft-clamp: extreme outliers do not dominate the cost
    landscape, while the sign convention (positive = penalty) is preserved.

    Weights and reference values are tunable at construction time so the
    invoker can calibrate for the mission without subclassing.

    Usage::

        layers = LayerStore.load({
            LAYER_TERRAIN:    (Path("srtm.tif"),    bbox),
            LAYER_POPULATION: (Path("ca_pop.tif"),  bbox),
            LAYER_SOLAR:      (Path("PVOUT.tif"),   bbox),
        })
        model = DefaultCostModel()
        cost  = model.edge_cost(start_fp, next_fp, uav_state, uav_spec, layers)
    """

    def __init__(
        self,
        *,
        weight_population:   float = 1.0,
        weight_solar:        float = 0.5,
        population_ref:      float = 500.0,   # persons/km² treated as "high density"
        solar_ref:           float = 4.0,     # kWh/m²/day treated as "good solar"
        population_layer:    str   = LAYER_POPULATION,
        solar_layer:         str   = LAYER_SOLAR,
        terrain_layer:       str   = LAYER_TERRAIN,
        terrain_clearance_m: float = _DEFAULT_TERRAIN_CLEARANCE_M,
        no_fly_zones:        list[BaseGeometry] | None = None,
    ) -> None:
        super().__init__(
            terrain_layer=terrain_layer,
            terrain_clearance_m=terrain_clearance_m,
            no_fly_zones=no_fly_zones,
        )
        self.weight_population = weight_population
        self.weight_solar      = weight_solar
        self.population_ref    = population_ref
        self.solar_ref         = solar_ref
        self.population_layer  = population_layer
        self.solar_layer       = solar_layer

    def node_cost(self, pt: Point, layers: "LayerStore") -> float:
        """
        Environmental cost at WGS84 point ``pt``.

        Positive = penalty (avoid high population).
        Negative = attractor (prefer high solar luminance).
        """
        cost = 0.0

        # Population penalty
        try:
            pop_val = float(layers.values_at(pt, layer=self.population_layer)[0])
            if not math.isnan(pop_val):
                cost += self.weight_population * math.tanh(pop_val / self.population_ref)
        except (KeyError, IndexError, Exception) as exc:
            logger.debug("node_cost: population lookup failed at (%.5f,%.5f): %s",
                         pt.x, pt.y, exc)

        # Solar luminance attractor (subtract → lower cost near good solar sites)
        try:
            sol_val = float(layers.values_at(pt, layer=self.solar_layer)[0])
            if not math.isnan(sol_val):
                cost -= self.weight_solar * math.tanh(sol_val / self.solar_ref)
        except (KeyError, IndexError, Exception) as exc:
            logger.debug("node_cost: solar lookup failed at (%.5f,%.5f): %s",
                         pt.x, pt.y, exc)

        return cost
