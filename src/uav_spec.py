"""
uav_spec.py — Static vehicle specification for UAV route planning.

UAVSpec is frozen (immutable) — it describes hardware constants that do not
change during a mission. Pass one instance to PlanningSession and it flows
through to cost functions and feasibility checks automatically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class UAVSpec:
    """
    Static (hardware-constant) characteristics of the UAV.

    All speeds in m/s, distances in metres, angles in degrees,
    energy in watt-hours, mass in kg.

    Example — fixed-wing pusher-prop with VTOL, 50 kt max:
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
    """

    # ── Airspeed ──────────────────────────────────────────────────────────────
    max_airspeed_mps: float        # absolute ceiling (50 kts ≈ 25.7 m/s)
    cruising_speed_mps: float      # nominal efficient cruise speed
    stall_speed_mps: float         # minimum safe airspeed (hard lower bound)

    # ── Kinematics ────────────────────────────────────────────────────────────
    min_turn_radius_m: float       # at cruising speed + max bank angle
    max_bank_angle_deg: float      # determines turn radius at a given speed
    climb_rate_mps: float          # maximum sustained climb rate
    descent_rate_mps: float        # maximum sustained descent rate

    # ── Range / energy ────────────────────────────────────────────────────────
    max_range_m: float             # on a full charge at cruising speed, no wind
    battery_capacity_wh: float     # total usable battery energy
    mass_kg: float                 # all-up mass (affects climb energy cost)
    motor_efficiency: float        # 0.0–1.0; used in climb energy calculation
    drag_coeff: float              # dimensionless; used in wind energy model

    # ── Capability flags ──────────────────────────────────────────────────────
    has_vtol: bool = True          # if True, takeoff/landing don't need runways

    # ── Derived / computed methods ────────────────────────────────────────────

    def turn_radius_at(self, airspeed_mps: float) -> float:
        """
        Minimum turn radius (m) at a given airspeed using coordinated-turn model:
            r = v² / (g × tan(bank_angle))
        Clamps airspeed to [stall_speed_mps, max_airspeed_mps].
        """
        v = max(self.stall_speed_mps, min(airspeed_mps, self.max_airspeed_mps))
        bank_rad = math.radians(self.max_bank_angle_deg)
        return (v ** 2) / (9.81 * math.tan(bank_rad))

    def climb_energy_wh(self, delta_alt_m: float) -> float:
        """
        Energy (Wh) required to climb delta_alt_m metres.
        Descent is modelled as zero cost (glide; motor off).
        E = m·g·Δh / (η × 3600)
        """
        if delta_alt_m <= 0:
            return 0.0
        joules = self.mass_kg * 9.81 * delta_alt_m / self.motor_efficiency
        return joules / 3600.0

    def cruise_energy_wh_per_m(
        self, airspeed_mps: float, wind_component_mps: float = 0.0
    ) -> float:
        """
        Energy (Wh) per metre of level flight.
        wind_component_mps: positive = tailwind (reduces cost),
                            negative = headwind (increases cost).
        Simplified drag model: power ∝ effective_airspeed².
        """
        effective    = max(self.stall_speed_mps, airspeed_mps - wind_component_mps)
        ground_speed = max(0.5, airspeed_mps + wind_component_mps)

        # Power ratio: how much harder is the motor working vs. cruising speed?
        # drag_coeff × v² is the simplified drag-force model; the coefficient
        # cancels in the ratio, so only the speed ratio matters.
        reference_power = self.drag_coeff * self.cruising_speed_mps ** 2
        actual_power    = self.drag_coeff * effective ** 2
        power_ratio     = actual_power / reference_power   # = (effective / cruising_speed)²

        # Anchor to a real-world energy rate: Wh consumed per metre at cruise,
        # no wind, level flight — derived directly from the spec.
        baseline_wh_per_m = self.battery_capacity_wh / self.max_range_m

        # Scale by power ratio (how hard the motor works) and
        # ground-speed ratio (how far we travel per unit of time).
        # At cruise, no wind: power_ratio=1, ground_speed=cruising_speed → baseline_wh_per_m ✓
        # Headwind:  effective↑ (more drag) + ground_speed↓ (slow progress) → cost rises ✓
        # Tailwind:  effective↓ (less drag) + ground_speed↑ (fast progress) → cost falls ✓
        return baseline_wh_per_m * power_ratio * (self.cruising_speed_mps / ground_speed)

    def battery_fraction_for_range(self, distance_m: float) -> float:
        """
        Fraction of battery (0.0–1.0) consumed flying distance_m at cruising speed,
        no wind, level flight.  Quick feasibility check.
        """
        cost_wh = distance_m * self.cruise_energy_wh_per_m(self.cruising_speed_mps)
        return cost_wh / self.battery_capacity_wh
