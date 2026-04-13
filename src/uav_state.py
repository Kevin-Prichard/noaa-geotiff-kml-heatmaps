"""
uav_state.py — Live vehicle state snapshot for UAV route planning.

UAVState is mutable and updated continuously during flight.  It is separate
from UAVSpec (static hardware constants, src/uav_spec.py) and FlightPoint
(planning waypoint descriptor, src/flight_point.py).

UAVState composes a FlightPoint for the kinematic variables so planners can
extract a FlightPoint directly from live state without field duplication.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pyproj
from shapely.geometry import Point

from flight_point import FlightPoint

if TYPE_CHECKING:
    from uav_spec import UAVSpec


@dataclass
class UAVState:
    """
    Live snapshot of vehicle state.  Updated each telemetry tick.

    Compose into PlanningSession and pass to CostModel.edge_cost / is_flyable.

    Fields
    ------
    flight_point        Current kinematic state (position, alt, heading, airspeed).
    battery_soc         State of charge 0.0–1.0.
    solar_charge_rate_w Current solar PV input watts (0 if night / overcast).
    ambient_temp_c      OAT — affects battery capacity and icing risk.
    pitot_wind_mps      Headwind (+) / tailwind (−) along current heading from pitot.
    wind_vector_mps     3-D wind (east, north, up) m/s from GRIB upper-air layer.
    turbulence_index    0.0–1.0 EDR proxy; affects structural load + drain rate.
    icing_risk          0.0–1.0; values > threshold treated as hard constraint.
    timestamp_utc       Telemetry timestamp; used for solar angle calculation.
    dist_to_next_recharge_m  Updated by mission sequencer each step.
    """

    # ── Kinematics (via FlightPoint) ──────────────────────────────────────────
    flight_point: FlightPoint

    # ── Power ─────────────────────────────────────────────────────────────────
    battery_soc: float              # 0.0–1.0
    solar_charge_rate_w: float = 0.0

    # ── Atmospheric / sensor readings ─────────────────────────────────────────
    ambient_temp_c: float = 15.0
    pitot_wind_mps: float = 0.0                           # + headwind, − tailwind
    wind_vector_mps: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (E, N, Up) m/s
    turbulence_index: float = 0.0                         # 0.0–1.0
    icing_risk: float = 0.0                               # 0.0–1.0

    # ── Mission context ───────────────────────────────────────────────────────
    timestamp_utc: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    dist_to_next_recharge_m: float = math.inf

    # ── Convenience pass-throughs from FlightPoint ────────────────────────────

    @property
    def position(self) -> Point:
        return self.flight_point.point

    @property
    def altitude_m(self) -> float:
        return self.flight_point.altitude_m

    @property
    def heading_deg(self) -> float:
        return self.flight_point.heading_deg

    @property
    def airspeed_mps(self) -> float:
        return self.flight_point.airspeed_mps

    # ── Derived / computed ────────────────────────────────────────────────────

    def effective_wind_component_mps(self) -> float:
        """
        Wind component along the current heading (m/s).
        Positive = tailwind, negative = headwind.
        Uses GRIB wind_vector if available, falls back to pitot reading.
        """
        if any(v != 0.0 for v in self.wind_vector_mps):
            hdg_rad = math.radians(self.heading_deg)
            unit = (math.sin(hdg_rad), math.cos(hdg_rad))   # (east, north)
            return self.wind_vector_mps[0] * unit[0] + self.wind_vector_mps[1] * unit[1]
        return -self.pitot_wind_mps  # pitot sign convention: + = headwind

    def estimated_range_remaining_m(self, uav_spec: "UAVSpec") -> float:
        """
        Remaining flyable distance on current battery SOC at cruising speed.
        Does not account for wind or altitude change.
        """
        usable_wh = self.battery_soc * uav_spec.battery_capacity_wh
        wh_per_m = uav_spec.cruise_energy_wh_per_m(uav_spec.cruising_speed_mps)
        if wh_per_m <= 0:
            return math.inf
        return usable_wh / wh_per_m

    def reach_probability(
        self, target: FlightPoint, uav_spec: "UAVSpec"
    ) -> float:
        """
        Rough probability (0.0–1.0) that current battery charge is sufficient
        to reach target, assuming level cruise at current airspeed + wind.
        Returns 1.0 if range estimate comfortably exceeds distance; 0.0 if not.
        """

        # Great-circle distance approximation via pyproj
        geod = pyproj.Geod(ellps="WGS84")
        lon0, lat0 = self.position.x, self.position.y
        lon1, lat1 = target.point.x, target.point.y
        _, _, dist_m = geod.inv(lon0, lat0, lon1, lat1)

        wind = self.effective_wind_component_mps()
        wh_per_m = uav_spec.cruise_energy_wh_per_m(self.airspeed_mps, wind)
        required_wh = dist_m * wh_per_m
        available_wh = self.battery_soc * uav_spec.battery_capacity_wh

        if available_wh <= 0:
            return 0.0
        ratio = available_wh / max(required_wh, 1e-9)
        # Sigmoid-like: confident above 1.2×, uncertain between 0.8–1.2×, zero below 0.8×
        return float(min(1.0, max(0.0, (ratio - 0.8) / 0.4)))

    def is_icing_risk(self, threshold: float = 0.5) -> bool:
        """Hard safety check: True if icing conditions exceed threshold."""
        return self.icing_risk >= threshold

    def updated(self, **kwargs) -> "UAVState":
        """Return a new UAVState with selected fields replaced (immutable-style update)."""
        import dataclasses
        return dataclasses.replace(self, **kwargs)
