"""Provisional BIOBUZZ shooter flight calculation; SI units throughout.

X points toward the HIVE, Z up, Y across its mouth. The wheel shaft is X=0.
The ball follows the underside of the wheel counterclockwise in an X/Z plot:
theta=-180 degrees at the gravity-fed inlet, theta=alpha-90 at the exit.
The HIVE lower lip is (range_m, 0, 1.359); its upper edge leans away from us.

The gable is an ideal, zero-thickness opening. This calculation does not certify
basket-depth clearance, deformable-ball contact, tire traction, motor loading,
Magnus lift, or scoring. Cd scenarios are assumptions, not measured bounds.
"""

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path


G = 9.80665
AIR_DENSITY = 1.225
BALL_MASS_KG = 0.025
FREE_WHEEL_RPM = 6000.0  # REV's documented zero-stage 1:1 output; 10T:10T chain
TILT = math.radians(30)
SIN_TILT, COS_TILT = math.sin(TILT), math.cos(TILT)
MOUTH_HEIGHT_M = 0.3556
MOUTH_HALF_WIDTH_M = 0.254
STRAIGHT_SIDE_M = 7.61 * 0.0254
GABLE = ((-MOUTH_HALF_WIDTH_M, 0), (MOUTH_HALF_WIDTH_M, 0),
         (MOUTH_HALF_WIDTH_M, STRAIGHT_SIDE_M), (0, MOUTH_HEIGHT_M),
         (-MOUTH_HALF_WIDTH_M, STRAIGHT_SIDE_M))


@dataclass(frozen=True)
class Shooter:
    deck_m: float = 0.180
    shaft_above_deck_m: float = 0.140
    wheel_radius_m: float = 0.050
    hood_radius_m: float = 0.11812  # 50 + nominal 71.12 - interference 3 mm
    ball_diameter_m: float = 0.07366  # drawing maximum, not nominal
    lip_height_m: float = 1.359
    efficiency: float = 1.0

    def __post_init__(self):
        values = vars(self)
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("All inputs must be finite")
        if not (0 < self.efficiency <= 1):
            raise ValueError("Measured speed efficiency must be in (0, 1]")
        if self.deck_m < 0 or any(values[key] <= 0 for key in values if key != "deck_m"):
            raise ValueError("Dimensions must be positive; deck height may be zero")
        if self.hood_radius_m <= max(self.wheel_radius_m, self.ball_diameter_m / 2):
            raise ValueError("Hood radius must exceed tire and ball radii")

    def release(self, angle_deg):
        if not math.isfinite(angle_deg) or not 0 < angle_deg < 90:
            raise ValueError("Exit angle must be strictly between 0 and 90 degrees")
        theta = math.radians(angle_deg - 90)
        radius = self.hood_radius_m - self.ball_diameter_m / 2
        return (radius * math.cos(theta),
                self.deck_m + self.shaft_above_deck_m + radius * math.sin(theta),
                -math.sin(theta), math.cos(theta))

    def rpm(self, speed_m_s):
        # A rolling ball between moving tire and stationary hood has v=omega*R/2.
        return 60 * speed_m_s / (math.pi * self.wheel_radius_m * self.efficiency)


def flight(shooter, angle_deg, speed_m_s, end_x_m, cd=0.0, dx=0.002):
    """RK4 integrated in X: rows are (x, z, vx, vz, time), in SI units."""
    if not all(math.isfinite(v) for v in (speed_m_s, end_x_m, cd, dx)):
        raise ValueError("Flight inputs must be finite")
    if speed_m_s <= 0 or cd < 0 or dx <= 0:
        raise ValueError("Speed and step must be positive; Cd must be nonnegative")
    x, z, tx, tz = shooter.release(angle_deg)
    if end_x_m <= x:
        raise ValueError("Flight endpoint must be beyond the release")
    state = (z, speed_m_s * tx, speed_m_s * tz, 0.0)
    drag = AIR_DENSITY * cd * math.pi * (shooter.ball_diameter_m / 2) ** 2 / (2 * BALL_MASS_KG)

    def derivative(value):
        _, vx, vz, _ = value
        if vx <= 0.001:
            raise ValueError("Ball has insufficient forward velocity")
        speed = math.hypot(vx, vz)
        return vz / vx, -drag * speed, -G / vx - drag * speed * vz / vx, 1 / vx

    rows = [(x, *state)]
    while x < end_x_m - 1e-12:
        step = min(dx, end_x_m - x)
        k1 = derivative(state)
        k2 = derivative(tuple(v + step * k / 2 for v, k in zip(state, k1)))
        k3 = derivative(tuple(v + step * k / 2 for v, k in zip(state, k2)))
        k4 = derivative(tuple(v + step * k for v, k in zip(state, k3)))
        state = tuple(v + step * (a + 2 * b + 2 * c + d) / 6
                      for v, a, b, c, d in zip(state, k1, k2, k3, k4))
        x += step
        rows.append((x, *state))
    return rows


def aimed_speed(shooter, angle_deg, range_m, cd):
    """Aim at the middle of the tilted face's full height, on its centerline."""
    target_x = range_m + MOUTH_HEIGHT_M / 2 * SIN_TILT
    target_z = shooter.lip_height_m + MOUTH_HEIGHT_M / 2 * COS_TILT
    x0, z0, tx, tz = shooter.release(angle_deg)
    distance = target_x - x0
    denominator = 2 * tx ** 2 * (distance * tz / tx - (target_z - z0))
    if distance <= 0 or denominator <= 0:
        raise ValueError("Target is outside this angle's ballistic reach")
    vacuum_speed = math.sqrt(G * distance ** 2 / denominator)
    if cd == 0:
        return vacuum_speed
    low, high = vacuum_speed, vacuum_speed * 4
    if flight(shooter, angle_deg, high, target_x, cd, dx=0.01)[-1][1] < target_z:
        raise ValueError("Drag scenario exceeds the speed search bracket")
    for _ in range(32):
        middle = (low + high) / 2
        z = flight(shooter, angle_deg, middle, target_x, cd, dx=0.01)[-1][1]
        if z < target_z:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def mouth_coordinates(row, range_m, lip_height_m):
    x, z = row[:2]
    return (-COS_TILT * (x - range_m) + SIN_TILT * (z - lip_height_m),
            SIN_TILT * (x - range_m) + COS_TILT * (z - lip_height_m))


def motor_clearance(shooter, angle_deg, rows, lateral_m=0.0):
    """Swept 3D sphere versus the relocated Ø43.74 × 90 mm motor envelope.

    The Y-axis motor is 76.2 mm from the wheel at +60 degrees in X/Z. Signed
    distance to its capped cylinder includes both its barrel and its end faces.
    Between samples, distance is 1-Lipschitz, so half a segment's arc-length bound
    covers the sampling gap. There is also an analytic bound: gravity and drag
    without lift keep the flight below its release tangent, while the motor is
    above it. That separating half-plane bounds the entire flight, at any speed.
    """
    if not rows or not math.isfinite(lateral_m):
        raise ValueError("Motor clearance needs a flight path and finite lateral position")
    motor_x = 0.0762 * math.cos(math.radians(60))
    motor_z = shooter.deck_m + shooter.shaft_above_deck_m + 0.0762 * math.sin(math.radians(60))
    motor_radius, y_min, y_max = 0.02187, -0.046, 0.044
    radius = shooter.ball_diameter_m / 2
    x0, z0, tx, tz = shooter.release(angle_deg)
    tangent_bound = tx * (motor_z - z0) - tz * (motor_x - x0) - motor_radius - radius
    closest, sampled_bound, previous = None, math.inf, None
    for row in rows:
        x, z, vx, vz, _ = row
        radial = math.hypot(x - motor_x, z - motor_z) - motor_radius
        axial = max(y_min - lateral_m, lateral_m - y_max)
        distance = math.hypot(max(radial, 0), max(axial, 0)) + min(max(radial, axial), 0) - radius
        if closest is None or distance < closest[0]:
            closest = (distance, x, lateral_m, z)
        if previous is not None:
            old_row, old_distance = previous
            arc_bound = (x - old_row[0]) * max(math.hypot(1, old_row[3] / old_row[2]),
                                                math.hypot(1, vz / vx))
            sampled_bound = min(sampled_bound, min(old_distance, distance) - arc_bound / 2)
        previous = row, distance
    if len(rows) == 1:
        sampled_bound = closest[0]
    continuous_bound = max(tangent_bound, sampled_bound)
    return {"motor_axis_x_z_m": [motor_x, motor_z], "motor_y_span_m": [y_min, y_max],
            "motor_radius_m": motor_radius, "ball_center_y_m": lateral_m,
            "closest_sampled_ball_center_x_y_z_m": list(closest[1:]),
            "sampled_sphere_clearance_mm": closest[0] * 1000,
            "tangent_halfplane_clearance_lower_bound_mm": tangent_bound * 1000,
            "continuous_clearance_lower_bound_mm": continuous_bound * 1000,
            "exceeds_3mm_clearance": continuous_bound > 0.003}


def aperture_clearance(rows, range_m, lip_height_m, ball_radius_m, lateral_m=0.0):
    """Bound swept-sphere clearance from the plane outside its convex gable.

    Distance to that solid is hypot(normal_distance, max(in-plane_margin, 0)).
    Subtract the sphere radius, then half the largest segment arc-length bound
    to cover gaps between samples. Gravity makes vz/vx monotonic, so endpoint
    slopes bound arc length for this no-lift drag model. Rim thickness and the
    interior basket are deliberately excluded.
    """
    # ponytail: thin aperture only; add measured rim/basket solids when available.
    clearance, gap_bound, crossing = math.inf, 0.0, None
    previous = None
    fully_entered = False
    for row in rows:
        normal, height = mouth_coordinates(row, range_m, lip_height_m)
        margins = []
        for (y0, h0), (y1, h1) in zip(GABLE, GABLE[1:] + GABLE[:1]):
            dy, dh = y1 - y0, h1 - h0
            margins.append((dy * (height - h0) - dh * (lateral_m - y0)) / math.hypot(dy, dh))
        clearance = min(clearance, math.hypot(normal, max(min(margins), 0)) - ball_radius_m)
        if previous is not None:
            old_normal, _ = mouth_coordinates(previous, range_m, lip_height_m)
            slope_bound = max(math.hypot(1, previous[3] / previous[2]),
                              math.hypot(1, row[3] / row[2]))
            gap_bound = max(gap_bound, (row[0] - previous[0]) * slope_bound / 2)
            if old_normal >= 0 > normal and crossing is None:
                fraction = old_normal / (old_normal - normal)
                crossing = tuple(a + fraction * (b - a) for a, b in zip(previous, row))
        if crossing is not None and normal < -ball_radius_m:
            fully_entered = True
            break
        previous = row
    return {
        "swept_sphere_clearance_lower_bound_mm": 1000 * (clearance - gap_bound),
        "sampling_allowance_mm": 1000 * gap_bound,
        "center_crossing_x_z_m": list(crossing[:2]) if crossing else None,
        "entry_angle_deg": math.degrees(math.atan2(crossing[3], crossing[2])) if crossing else None,
        "descending_entry": crossing is not None and crossing[3] < 0,
        "entire_ball_crossed_plane": fully_entered,
        "aperture_plane_clear": fully_entered and clearance > gap_bound,
    }


def report(shooter, angles=(60, 65, 70), ranges=(1.5, 2, 2.5), cds=(0, 0.5, 1.0)):
    cases = []
    for angle in angles:
        for distance in ranges:
            vacuum_speed = aimed_speed(shooter, angle, distance, 0)
            for cd in cds:
                speed = aimed_speed(shooter, angle, distance, cd)
                sensitivity = []
                motor_sensitivity = []
                for factor in (0.95, 1, 1.05):
                    rows = flight(shooter, angle, speed * factor, distance + 0.55, cd)
                    motor_sensitivity.append({"speed_factor": factor, **motor_clearance(shooter, angle, rows)})
                    for lip_shift in (-0.025, 0, 0.025):
                        check = aperture_clearance(rows, distance, shooter.lip_height_m + lip_shift,
                                                   shooter.ball_diameter_m / 2)
                        sensitivity.append({"speed_factor": factor, "lip_height_shift_mm": 1000 * lip_shift,
                                            **check})
                nominal = next(item for item in sensitivity
                               if item["speed_factor"] == 1 and item["lip_height_shift_mm"] == 0)
                vacuum_command = aperture_clearance(
                    flight(shooter, angle, vacuum_speed, distance + 0.55, cd),
                    distance, shooter.lip_height_m, shooter.ball_diameter_m / 2)
                cases.append({"angle_deg": angle, "shaft_to_lower_lip_range_m": distance, "cd": cd,
                              "aimed_speed_m_s": speed, "required_wheel_rpm": shooter.rpm(speed),
                              "below_free_rpm_ceiling": shooter.rpm(speed) <= FREE_WHEEL_RPM,
                              "nominal": nominal, "sensitivity": sensitivity,
                              "motor_speed_sensitivity": motor_sensitivity,
                              "vacuum_speed_held_under_this_drag": {
                                  "speed_m_s": vacuum_speed, **vacuum_command},
                              "all_sampled_conditions_clear_and_descending": all(
                                  item["aperture_plane_clear"] and item["descending_entry"]
                                  for item in sensitivity)})
    return {
        "status": "PROVISIONAL_CALCULATION_NOT_SHOT_VALIDATION",
        "model": vars(shooter), "free_wheel_rpm_ceiling": FREE_WHEEL_RPM,
        "fixed_starting_height": {
            "layout_top_above_deck_m": 0.264, "height_limit_m": 0.4572,
            "maximum_deck_m": 0.4572 - 0.264,
            "selected_total_height_m": shooter.deck_m + 0.264,
            "within_height_bound": shooter.deck_m + 0.264 <= 0.4572,
            "evidence": "Provisional CAD layout height; verify against exported assembly bounds"},
        "coordinates": "X forward, Z up; range measured from wheel shaft to lower lip; Y=0 centered aim",
        "aperture": {"tilt_from_vertical_deg": 30, "height_m": MOUTH_HEIGHT_M,
                     "width_m": 2 * MOUTH_HALF_WIDTH_M, "straight_side_height_m": STRAIGHT_SIDE_M},
        "release": [{"angle_deg": angle, "x_z_m": list(shooter.release(angle)[:2]),
                     "tangent_x_z": list(shooter.release(angle)[2:]), "ccw_wrap_deg": 90 + angle}
                    for angle in angles],
        "limitations": [
            "Cd=0, 0.5, 1.0 are sensitivity assumptions, not bounds on an irregular spinning POLLEN.",
            "Each Cd is aimed separately; speed ±5% and vertical lip ±25 mm then hold that aim fixed.",
            "The separate vacuum-command check holds launch speed fixed while Cd changes.",
            "The field tolerance sweep covers vertical lip displacement only, not every field dimension.",
            "Free motor speed is an upper ceiling, not a loaded operating point; measure RPM and speed efficiency.",
            "Only the zero-thickness gable plane is checked; basket roof, depth, rim thickness and bounce remain open.",
            "25A Shore hardness does not determine grip, recovery, deformation, casting strength or fatigue.",
            "No wind, Magnus force, ball-shape variation, lateral aim error, or robot motion is modeled.",
            "Motor clearance covers its stated cylindrical body only, not wiring, chain, guard or mounting hardware.",
        ], "cases": cases,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck-mm", type=float, default=180)
    parser.add_argument("--compression-mm", type=float, default=3)
    parser.add_argument("--efficiency", type=float, default=1)
    parser.add_argument("--angles", type=float, nargs="+", default=[60, 65, 70])
    parser.add_argument("--ranges", type=float, nargs="+", default=[1.5, 2, 2.5])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not math.isfinite(args.compression_mm) or not 0 <= args.compression_mm <= 10:
        parser.error("compression must be between 0 and 10 mm")
    try:
        shooter = Shooter(deck_m=args.deck_mm / 1000, efficiency=args.efficiency,
                          hood_radius_m=(50 + 71.12 - args.compression_mm) / 1000)
        result = report(shooter, args.angles, args.ranges)
    except ValueError as error:
        parser.error(str(error))
    encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
        print(args.output)
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
