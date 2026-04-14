"""waypoints_main.py — Smoke test + demo main() for the UAV route planner."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from datetime import datetime, timezone

# Ensure project root is on sys.path when run directly
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import geopandas as gpd
from shapely.geometry import Point

from src.cost_model import DefaultCostModel, LAYER_TERRAIN, LAYER_POPULATION, LAYER_SOLAR
from src.flight_point import FlightPoint
from src.planning_session import PlanningSession
from src.route_planner import (
    RoutePlannerDijkstra,
    RoutePlannerAStar,
    RoutePlannerARAStar,
    RoutePlannerDStarLite,
)
from src.uav_spec import UAVSpec
from src.uav_state import UAVState
from src.waypoints import graph_path_to_waypoints, save_waypoints, waypoints_to_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Mission constants ──────────────────────────────────────────────────────────

_NAV_ROOT  = Path(__file__).parent

START_LON, START_LAT = -122.29120393435966, 37.985653198087924
END_LON,   END_LAT   = -122.20658410469638, 37.87320207491443  # Mt Diablo peak: -121.60898943472321, 37.654702833452426

BBOX_WS84 = (-122.36581181660316, 37.74053331132046,   # west, south
             -121.76274978462865, 38.01772638122616)    # east, north

MAP_FGB   = _NAV_ROOT / "osm" / "norcal-260410.osm.pbf.fgb"
TERRAIN   = _NAV_ROOT / "top" / "norcal" / "output_SRTMGL1-pt_reyes-bakersfield.tif"
POPULATION = (_NAV_ROOT / "pop" / "get_wp_global" / "rasters" / "R2025A" / "2026"
              / "USA_States" / "CA" / "ca_pop_2026_CN_100m_R2025A_v1.tif")
SOLAR     = (_NAV_ROOT / "sol"
             / "World_PVOUT_GISdata_LTAy_AvgDailyTotals_GlobalSolarAtlas-v2_GEOTIFF"
             / "PVOUT.tif")

UAV_SPEC = UAVSpec(
    max_airspeed_mps=25.7,
    cruising_speed_mps=18.0,
    stall_speed_mps=9.0,
    min_turn_radius_m=120.0,
    max_bank_angle_deg=35.0,
    climb_rate_mps=4.0,
    descent_rate_mps=3.0,
    max_range_m=80_000,
    battery_capacity_wh=1_200.0,
    mass_kg=5.5,
    motor_efficiency=0.80,
    drag_coeff=0.035,
    has_vtol=True,
)


def _bbox_gs(west, south, east, north) -> gpd.GeoSeries:
    return gpd.GeoSeries(
        [Point(west, south), Point(east, north)], crs="EPSG:4326")


def main() -> None:
    logger.info("=== UAV Route Planner demo ===")

    # ── FlightPoints ───────────────────────────────────────────────────────────
    start_fp = FlightPoint.from_lonlat(
        START_LON, START_LAT, altitude_m=50.0, heading_deg=0.0, airspeed_mps=0.0)
    end_fp   = FlightPoint.from_lonlat(
        END_LON,   END_LAT,   altitude_m=100.0, heading_deg=180.0, airspeed_mps=0.0)

    # ── UAVState (full charge at start position) ───────────────────────────────
    uav_state = UAVState(flight_point=start_fp, battery_soc=1.0)

    # ── Verify resource files exist ────────────────────────────────────────────
    for name, p in [("Terrain", TERRAIN), ("Population", POPULATION),
                    ("Solar", SOLAR), ("Map FGB", MAP_FGB)]:
        if not p.exists():
            logger.warning("%s not found: %s  (skipping)", name, p)

    bbox_gs   = _bbox_gs(*BBOX_WS84)
    layer_cfg = {}
    if TERRAIN.exists():
        layer_cfg[LAYER_TERRAIN]    = (TERRAIN,    bbox_gs)
    if POPULATION.exists():
        layer_cfg[LAYER_POPULATION] = (POPULATION, bbox_gs)
    if SOLAR.exists():
        layer_cfg[LAYER_SOLAR]      = (SOLAR,       bbox_gs)

    maps_cfg = [(MAP_FGB, bbox_gs)] if MAP_FGB.exists() else []

    # ── Build session (coarser grid for demo speed) ────────────────────────────
    session = PlanningSession(
        # planner_classes   = [RoutePlannerDijkstra, RoutePlannerAStar,
        #                      RoutePlannerARAStar, RoutePlannerDStarLite],
        planner_classes   = [RoutePlannerDijkstra],
        start             = start_fp,
        end               = end_fp,
        cost_model        = DefaultCostModel(),
        layers            = layer_cfg,
        maps              = maps_cfg,
        uav_spec          = UAV_SPEC,
        uav_state         = uav_state,
        grid_resolution_m = 1_000.0,   # 1 km spacing → manageable node count
        max_grid_nodes    = 10_000,
        grid_margin_m     = 5_000.0,
    )

    # ── Run all planners ───────────────────────────────────────────────────────
    logger.info("Running plan_all() ...")
    try:
        results = session.plan_all()
    except Exception as exc:
        logger.error("plan_all failed: %s", exc, exc_info=True)
        session.destroy()
        return

    # ── Print and save waypoints for each planner ──────────────────────────────
    now_utc = datetime.now(timezone.utc)
    out_dir = _NAV_ROOT / "out"
    out_dir.mkdir(exist_ok=True)

    for planner_cls, graph in results.items():
        planner_name = planner_cls.__name__
        # Find the planner instance to get its path
        planner_inst = next(
            (p for p in session._planners if type(p) is planner_cls), None)
        path_nodes = planner_inst.get_path() if planner_inst else []

        if not path_nodes:
            logger.warning("%s: no path found", planner_name)
            continue

        waypoints = graph_path_to_waypoints(
            graph, path_nodes, planner_name, UAV_SPEC, uav_state, now_utc)

        logger.info("─── %s: %d waypoints, total cost %.4f Wh",
                    planner_name, len(waypoints),
                    waypoints[-1].path_aggregate_cost if waypoints else 0.0)
        print(f"\n{planner_name} waypoints ({len(waypoints)}):")
        print(waypoints_to_json(waypoints[:5]))  # first 5 for brevity
        if len(waypoints) > 5:
            print(f"  ... ({len(waypoints) - 5} more)")

        json_path = out_dir / f"{planner_name}_waypoints.json"
        save_waypoints(waypoints, json_path)
        logger.info("  saved → %s", json_path)

    # ── Plot all routes and save PNG ───────────────────────────────────────────
    png_path = out_dir / "routes.png"
    logger.info("Saving route plot → %s", png_path)
    try:
        session.plot(save_path=png_path)
    except Exception as exc:
        logger.warning("plot failed: %s", exc)

    session.destroy()
    logger.info("Done.")


if __name__ == "__main__":
    main()
