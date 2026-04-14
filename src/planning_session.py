"""planning_session.py — PlanningSession: coordinator and runtime context for RoutePlanners."""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import geopandas as gpd
import networkx
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from src.cost_model import CostModel, DefaultCostModel, LAYER_TERRAIN
from src.flight_point import FlightPoint
from src.layer_store import BoundingBox, LayerStore
from src.planning_grid import PlanningGrid
from src.uav_spec import UAVSpec
from src.uav_state import UAVState

if TYPE_CHECKING:
    from src.route_planner import RoutePlanner

logger = logging.getLogger(__name__)


class PlanningSession:
    """
    Coordinator for one route planning run.

    Builds LayerStore, PlanningGrid, instantiates RoutePlanner subclasses,
    and provides shared helpers (map_feats, layer_values, dispatch_step, plan_all).
    """

    def __init__(
        self,
        planner_classes:    list[type],                  # RoutePlanner subclasses to run
        start:              FlightPoint,
        end:                FlightPoint,
        cost_model:         CostModel | None = None,
        # dict of {label: (path_or_str, bbox_geoseries)}
        layers:             dict[str, tuple] | None = None,
        # list of (fgb_path_or_gdf, bbox_geoseries)
        maps:               list[tuple] | None = None,
        no_fly_zones:       list[BaseGeometry | gpd.GeoDataFrame] | None = None,
        grid_resolution_m:  float = 100.0,
        max_grid_nodes:     int   = 50_000,
        uav_spec:           UAVSpec  | None = None,
        uav_state:          UAVState | None = None,
        grid_margin_m:      float = 5_000.0,
    ) -> None:
        if uav_spec is None:
            raise ValueError("uav_spec is required")
        if uav_state is None:
            raise ValueError("uav_state is required")

        self._start          = start
        self._end            = end
        self.uav_spec        = uav_spec
        self.uav_state       = uav_state
        self.cost_model      = cost_model if cost_model is not None else DefaultCostModel()
        self.no_fly_zones: list[BaseGeometry] = _normalise_nfz(no_fly_zones or [])
        self._planner_classes = list(planner_classes)

        # ── Build LayerStore ───────────────────────────────────────────────────
        self._layer_sources: dict[str, tuple[Path, BoundingBox]] = {}
        layer_sources_for_store: dict[str, tuple[Path, BoundingBox]] = {}
        for label, (src, bbox_gs) in (layers or {}).items():
            bb = BoundingBox.from_geoseries(bbox_gs)
            layer_sources_for_store[label] = (Path(src), bb)
            self._layer_sources[label] = (Path(src), bb)

        if layer_sources_for_store:
            try:
                self.layers: LayerStore = LayerStore.load(layer_sources_for_store)
            except Exception as exc:
                logger.error("LayerStore.load failed: %s", exc)
                raise
        else:
            logger.warning("PlanningSession: no raster layers provided; "
                           "terrain checks will be skipped")
            self.layers = LayerStore()

        # ── Pre-load FGB map files ─────────────────────────────────────────────
        self._maps: list[gpd.GeoDataFrame] = []
        for src, bbox_gs in (maps or []):
            bb = BoundingBox.from_geoseries(bbox_gs)
            if isinstance(src, gpd.GeoDataFrame):
                self._maps.append(src)
            else:
                try:
                    gdf = gpd.read_file(str(src), bbox=(bb.west, bb.south, bb.east, bb.north))
                    self._maps.append(gdf)
                    logger.info("Loaded map %s (%d features)", Path(src).name, len(gdf))
                except Exception as exc:
                    logger.error("Failed to load map %s: %s", src, exc)
                    raise

        # ── Build grid BBox from start + end + margin ──────────────────────────
        sp_lon, sp_lat = start.point.x, start.point.y
        ep_lon, ep_lat = end.point.x,   end.point.y
        # Metric margin → approximate degree expansion
        mid_lat    = (sp_lat + ep_lat) / 2.0
        lat_deg    = grid_margin_m / 111_320.0
        lon_deg    = grid_margin_m / (111_320.0 * max(math.cos(math.radians(mid_lat)), 1e-6))
        grid_bbox  = BoundingBox(
            west  = min(sp_lon, ep_lon) - lon_deg,
            south = min(sp_lat, ep_lat) - lat_deg,
            east  = max(sp_lon, ep_lon) + lon_deg,
            north = max(sp_lat, ep_lat) + lat_deg,
        )

        # ── Build PlanningGrid ─────────────────────────────────────────────────
        self.grid: PlanningGrid = PlanningGrid.build(
            bbox           = grid_bbox,
            resolution_m   = grid_resolution_m,
            max_grid_nodes = max_grid_nodes,
            layers         = self.layers,
            terrain_layer  = LAYER_TERRAIN,
        )
        logger.info("PlanningSession: grid %s", self.grid)

        # ── Instantiate planners ───────────────────────────────────────────────
        self._planners: list[RoutePlanner] = [cls(self) for cls in self._planner_classes]

    # ── Getters ────────────────────────────────────────────────────────────────

    def start(self) -> FlightPoint:
        return self._start

    def end(self) -> FlightPoint:
        return self._end

    # ── Map feature query ──────────────────────────────────────────────────────

    def map_feats(
        self,
        area:          BaseGeometry,
        buffer_dist_m: float = 50.0,
    ) -> gpd.GeoDataFrame:
        if isinstance(area, Point) and buffer_dist_m == 0.0:
            raise ValueError(
                "map_feats: area is a Point and buffer_dist_m=0.0; "
                "provide a non-zero buffer or a polygon geometry.")
        import pyproj
        from shapely.ops import transform as shp_transform

        # Buffer in metres using AEQD centroid projection
        query_geom = area
        if buffer_dist_m > 0.0:
            pt = area.centroid
            aeqd = pyproj.CRS.from_proj4(
                f"+proj=aeqd +lat_0={pt.y} +lon_0={pt.x} +units=m")
            fwd = pyproj.Transformer.from_crs("EPSG:4326", aeqd, always_xy=True)
            inv = pyproj.Transformer.from_crs(aeqd, "EPSG:4326", always_xy=True)
            proj_geom = shp_transform(fwd.transform, area)
            buffered  = proj_geom.buffer(buffer_dist_m)
            query_geom = shp_transform(inv.transform, buffered)

        frames: list[gpd.GeoDataFrame] = []
        for gdf in self._maps:
            try:
                clip = gdf[gdf.geometry.intersects(query_geom)]
                if not clip.empty:
                    frames.append(clip)
            except Exception as exc:
                logger.debug("map_feats: intersect failed: %s", exc)

        if frames:
            import pandas as pd
            return gpd.GeoDataFrame(
                pd.concat(frames, ignore_index=True), crs=frames[0].crs)
        return gpd.GeoDataFrame()

    # ── Layer value query ──────────────────────────────────────────────────────

    def layer_values(
        self,
        pt:    Point,
        layer: str | None = None,
    ):
        return self.layers.values_at(pt, layer=layer)

    # ── Planning dispatch ──────────────────────────────────────────────────────

    def dispatch_step(
        self,
        callback: Callable[[int, networkx.MultiDiGraph, type], None] | None = None,
    ) -> None:
        """
        Advance every planner by one step.

        callback provided → step each planner serially, call callback after each.
        callback=None     → step each planner serially without notification
                            (use plan_all() for true parallel execution).
        """
        for planner in self._planners:
            step_nr, graph = planner.step()
            if callback is not None:
                callback(step_nr, graph, type(planner))

    def plan_all(self) -> dict[type, networkx.MultiDiGraph]:
        """Run all planners to completion in parallel via joblib."""
        from joblib import Parallel, delayed
        from multiprocessing import cpu_count

        n = len(self._planners)
        logger.info("plan_all: running %d planner(s) in parallel", n)
        try:
            results = Parallel(
                n_jobs=min(n, cpu_count()), backend="loky", prefer="processes"
            )(delayed(_planner_plan)(p) for p in self._planners)
        except Exception as exc:
            logger.warning("plan_all: joblib failed (%s); falling back to serial", exc)
            results = [_planner_plan(p) for p in self._planners]
        return dict(results)

    def plan_all_from(
        self,
        start_point: FlightPoint,
    ) -> dict[type, networkx.MultiDiGraph]:
        """Replan from a new start point (must be within the existing grid bbox)."""
        lon, lat = start_point.point.x, start_point.point.y
        bb = self.grid.bbox
        if not (bb.west <= lon <= bb.east and bb.south <= lat <= bb.north):
            raise ValueError(
                f"plan_all_from: ({lon:.4f},{lat:.4f}) is outside "
                f"grid bbox {bb}")
        self._start    = start_point
        self._planners = [cls(self) for cls in self._planner_classes]
        return self.plan_all()

    # ── Visualisation ──────────────────────────────────────────────────────────

    def plot(self, save_path: Path | str | None = None) -> None:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(13, 9))

        # Background map features
        for gdf in self._maps:
            if not gdf.empty:
                try:
                    gdf.plot(ax=ax, color="lightgray", linewidth=0.3, alpha=0.4)
                except Exception:
                    pass

        colors = ["steelblue", "crimson", "seagreen", "darkorange", "purple"]
        for i, planner in enumerate(self._planners):
            clr  = colors[i % len(colors)]
            name = type(planner).__name__
            _, edges_gdf = planner.to_gdfs()
            if not edges_gdf.empty:
                edges_gdf.plot(ax=ax, color=clr, linewidth=0.4, alpha=0.25)
            if planner._path:
                lons = [self.grid.graph.nodes[n]["lon"] for n in planner._path]
                lats = [self.grid.graph.nodes[n]["lat"] for n in planner._path]
                ax.plot(lons, lats, color=clr, linewidth=2.5, label=name, zorder=4)

        sp, ep = self._start.point, self._end.point
        ax.scatter([sp.x], [sp.y], c="lime",  s=120, zorder=6, label="Start")
        ax.scatter([ep.x], [ep.y], c="red",   s=120, zorder=6, label="End",
                   marker="*")
        ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
        ax.set_title("UAV Route Planning — all planners")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

        if save_path is not None:
            fig.savefig(str(save_path), dpi=150, bbox_inches="tight")
            logger.info("plot saved → %s", save_path)
        else:
            plt.show()
        plt.close(fig)

    # ── Refresh a raster layer (enables D* Lite dynamic replanning) ────────────

    def refresh_layer(self, key: str, new_path: Path | str) -> None:
        """Reload a raster layer from an updated file and notify D* Lite planners."""
        from src.route_planner import RoutePlannerDStarLite
        bb = self._layer_sources.get(key, (None, self.grid.bbox))[1]
        self._layer_sources[key] = (Path(new_path), bb)
        try:
            self.layers = LayerStore.load(
                {k: (p, b) for k, (p, b) in self._layer_sources.items()})
            logger.info("refresh_layer: reloaded '%s' from %s", key, new_path)
        except Exception as exc:
            logger.error("refresh_layer: reload failed: %s", exc)
            raise
        affected = list(self.grid.graph.nodes())
        for planner in self._planners:
            if isinstance(planner, RoutePlannerDStarLite):
                planner.update_edge_costs(affected)

    # ── Orderly teardown ───────────────────────────────────────────────────────

    def destroy(self) -> None:
        """Release all resources; safe to call multiple times."""
        try:
            if self.layers is not None:
                self.layers.close()
        except Exception as exc:
            logger.debug("destroy: layers.close() error: %s", exc)
        for attr in list(vars(self)):
            object.__setattr__(self, attr, None)
        logger.debug("PlanningSession destroyed")


# ── Private helpers ────────────────────────────────────────────────────────────

def _planner_plan(planner: "RoutePlanner") -> tuple[type, networkx.MultiDiGraph]:
    return type(planner), planner.plan()


def _normalise_nfz(
    zones: list[Any],
) -> list[BaseGeometry]:
    result: list[BaseGeometry] = []
    for z in zones:
        if isinstance(z, BaseGeometry):
            result.append(z)
        elif isinstance(z, gpd.GeoDataFrame):
            result.extend(z.geometry.tolist())
        else:
            logger.warning("_normalise_nfz: ignoring unsupported type %s", type(z))
    return result
