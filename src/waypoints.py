"""waypoints.py — Waypoint dataclass, planning-node schemas, and serialisation helpers."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import pyproj

if TYPE_CHECKING:
    import networkx
    from src.uav_spec import UAVSpec
    from src.uav_state import UAVState


# ── Exceptions ─────────────────────────────────────────────────────────────────

class NoPathFoundError(RuntimeError):
    """Planner exhausted the search space; no route exists between start and end."""


# ── Planning node schemas ──────────────────────────────────────────────────────
# Dataclasses define the attribute schema planners write into the graph.
# Actual values are stored directly in networkx node attribute dicts.

@dataclass
class PlanNodeBase:
    lon: float
    lat: float
    cost: float = 0.0               # edge energy arriving at this node (Wh)
    path_aggregate_cost: float = 0.0  # cumulative cost from start → this node

    def as_attrs(self) -> dict:
        return {"cost": self.cost, "path_aggregate_cost": self.path_aggregate_cost}


@dataclass
class PlanNodeDijkstra(PlanNodeBase):
    pass


@dataclass
class PlanNodeAStar(PlanNodeBase):
    h: float = 0.0          # heuristic to goal (stored for diagnostics)


@dataclass
class PlanNodeARAStar(PlanNodeBase):
    epsilon: float = 1.0    # ε inflation at which this node was last expanded


@dataclass
class PlanNodeDStarLite(PlanNodeBase):
    g:   float = math.inf   # D* Lite cost estimate (node → goal)
    rhs: float = math.inf   # D* Lite one-step lookahead value


# ── Waypoint ───────────────────────────────────────────────────────────────────

@dataclass
class Waypoint:
    id:                   int
    planner:              str
    longitude:            float
    latitude:             float
    altitude_m:           float
    airspeed_mps:         float
    heading_deg:          float
    action:               str   # takeoff|cruise|loiter|holding|turning|recharge_stop|rtl|land
    eta_unix_ms:          int
    battery_soc_est:      float
    cost:                 float
    path_aggregate_cost:  float

    def to_dict(self) -> dict:
        return {
            "id":                  self.id,
            "planner":             self.planner,
            "longitude":           self.longitude,
            "latitude":            self.latitude,
            "altitude_m":          self.altitude_m,
            "airspeed_mps":        self.airspeed_mps,
            "heading_deg":         self.heading_deg,
            "action":              self.action,
            "eta_unix_ms":         self.eta_unix_ms,
            "battery_soc_est":     self.battery_soc_est,
            "cost":                self.cost,
            "path_aggregate_cost": self.path_aggregate_cost,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def save_as(self, path: Path | str) -> None:
        Path(path).write_text(self.to_json())


def waypoints_to_json(waypoints: list[Waypoint]) -> str:
    return json.dumps([w.to_dict() for w in waypoints], indent=2)


def save_waypoints(waypoints: list[Waypoint], path: Path | str) -> None:
    Path(path).write_text(waypoints_to_json(waypoints))


# ── Geometry helpers ───────────────────────────────────────────────────────────

def _bearing_deg(lon0: float, lat0: float, lon1: float, lat1: float) -> float:
    """Initial bearing (degrees true) from (lon0,lat0) to (lon1,lat1)."""
    lat0r = math.radians(lat0);  lat1r = math.radians(lat1)
    dlon  = math.radians(lon1 - lon0)
    x = math.sin(dlon) * math.cos(lat1r)
    y = math.cos(lat0r) * math.sin(lat1r) - math.sin(lat0r) * math.cos(lat1r) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


# ── Path → Waypoint extraction ─────────────────────────────────────────────────

def graph_path_to_waypoints(
    graph:           "networkx.MultiDiGraph",
    path_nodes:      list[int],
    planner_name:    str,
    uav_spec:        "UAVSpec",
    uav_state:       "UAVState",
    start_time_utc:  datetime | None = None,
) -> list[Waypoint]:
    if not path_nodes:
        return []
    if start_time_utc is None:
        start_time_utc = datetime.now(timezone.utc)

    geod  = pyproj.Geod(ellps="WGS84")
    t_ms  = int(start_time_utc.timestamp() * 1000)
    soc   = uav_state.battery_soc
    result: list[Waypoint] = []

    for idx, nid in enumerate(path_nodes):
        nd  = graph.nodes[nid]
        lon = float(nd["lon"])
        lat = float(nd["lat"])

        dist_m = 0.0
        if idx > 0:
            pnd = graph.nodes[path_nodes[idx - 1]]
            _, _, dist_m = geod.inv(pnd["lon"], pnd["lat"], lon, lat)
            dist_m = abs(dist_m)
            t_ms  += int(dist_m / max(uav_spec.cruising_speed_mps, 1.0) * 1000)
            soc   -= uav_spec.battery_fraction_for_range(dist_m)
            soc    = max(0.0, round(soc, 6))

        # Heading toward next node (last node inherits previous bearing)
        if idx + 1 < len(path_nodes):
            nxt = graph.nodes[path_nodes[idx + 1]]
            hdg = _bearing_deg(lon, lat, nxt["lon"], nxt["lat"])
        elif idx > 0:
            prv = graph.nodes[path_nodes[idx - 1]]
            hdg = _bearing_deg(prv["lon"], prv["lat"], lon, lat)
        else:
            hdg = 0.0

        if idx == 0:
            action = "takeoff"
        elif idx == len(path_nodes) - 1:
            action = "land"
        else:
            action = "cruise"

        result.append(Waypoint(
            id=nid,
            planner=planner_name,
            longitude=lon,
            latitude=lat,
            altitude_m=float(nd.get("altitude_m", uav_state.altitude_m)),
            airspeed_mps=uav_spec.cruising_speed_mps,
            heading_deg=round(hdg, 2),
            action=action,
            eta_unix_ms=t_ms,
            battery_soc_est=round(soc, 4),
            cost=float(nd.get("cost", 0.0)),
            path_aggregate_cost=float(nd.get("path_aggregate_cost", 0.0)),
        ))

    return result
