"""
flight_point.py — Minimal flight-state descriptor used as planning waypoints.

FlightPoint is the lightweight struct passed around as start/end locations,
candidate waypoints, and graph node payloads.  It is separate from UAVState
(which carries live sensor data) and UAVSpec (which carries static hardware
constants).
"""

from __future__ import annotations

from dataclasses import dataclass
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry


@dataclass
class FlightPoint:
    """
    Describes a single point in a planned or actual flight path.

    position may be any BaseGeometry (Polygon, MultiPoint, etc.) to represent
    a takeoff/landing *zone*; call .point to get the resolved Point for
    planning calculations.
    """
    _position: BaseGeometry    # WGS84; usually a Point, may be a zone shape
    _altitude_m: float         # metres AGL or AMSL (context-dependent; document at callsite)
    _heading_deg: float        # 0–360, true north
    _airspeed_mps: float       # metres per second

    # ── Accessors ─────────────────────────────────────────────────────────────

    @property
    def position(self) -> BaseGeometry:
        return self._position

    @position.setter
    def position(self, value: BaseGeometry) -> None:
        self._position = value

    @property
    def point(self) -> Point:
        """
        Always returns a Point regardless of the geometry type stored.
        For a Point, returns it directly.
        For anything else (Polygon, MultiPoint, …) returns the centroid.
        """
        if isinstance(self._position, Point):
            return self._position
        return self._position.centroid

    @property
    def altitude_m(self) -> float:
        return self._altitude_m

    @altitude_m.setter
    def altitude_m(self, value: float) -> None:
        self._altitude_m = value

    @property
    def heading_deg(self) -> float:
        return self._heading_deg

    @heading_deg.setter
    def heading_deg(self, value: float) -> None:
        self._heading_deg = float(value) % 360.0

    @property
    def airspeed_mps(self) -> float:
        return self._airspeed_mps

    @airspeed_mps.setter
    def airspeed_mps(self, value: float) -> None:
        self._airspeed_mps = value

    # ── Convenience constructors ───────────────────────────────────────────────

    @classmethod
    def from_lonlat(
        cls,
        lon: float,
        lat: float,
        altitude_m: float = 0.0,
        heading_deg: float = 0.0,
        airspeed_mps: float = 0.0,
    ) -> "FlightPoint":
        return cls(
            _position=Point(lon, lat),
            _altitude_m=altitude_m,
            _heading_deg=heading_deg,
            _airspeed_mps=airspeed_mps,
        )

    @classmethod
    def from_geometry(
        cls,
        geom: BaseGeometry,
        altitude_m: float = 0.0,
        heading_deg: float = 0.0,
        airspeed_mps: float = 0.0,
    ) -> "FlightPoint":
        """Accept any geometry; planning will use .point (centroid) automatically."""
        return cls(
            _position=geom,
            _altitude_m=altitude_m,
            _heading_deg=heading_deg,
            _airspeed_mps=airspeed_mps,
        )

    def __repr__(self) -> str:
        p = self.point
        return (
            f"FlightPoint(lon={p.x:.6f}, lat={p.y:.6f}, "
            f"alt={self._altitude_m:.1f}m, hdg={self._heading_deg:.1f}°, "
            f"spd={self._airspeed_mps:.1f}m/s)"
        )
