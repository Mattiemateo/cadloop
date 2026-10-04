"""Independent checks for the provisional, CAD-independent shooter calculation."""

import importlib.util
import math
from pathlib import Path
import sys

SPEC = importlib.util.spec_from_file_location(
    "shooter_trajectory", Path(__file__).parents[1] / "examples/biobuzz_shooter/trajectory.py")
trajectory = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = trajectory
SPEC.loader.exec_module(trajectory)


def test_exit_ballistics_and_whole_ball_clearance():
    shooter = trajectory.Shooter()
    for angle in (60, 65, 70):
        x, z, tx, tz = shooter.release(angle)
        assert tx > 0 and tz > 0  # prevents reversed-wheel/floor-launch regression
        assert math.isclose(tx, math.cos(math.radians(angle)))
        assert math.isclose(tz, math.sin(math.radians(angle)))
        radial_x, radial_z = x, z - shooter.deck_m - shooter.shaft_above_deck_m
        assert abs(radial_x * tx + radial_z * tz) < 1e-12
        assert radial_x * tz - radial_z * tx > 0  # CCW in the X/Z plane

    angle, distance = 65, 2.0
    speed = trajectory.aimed_speed(shooter, angle, distance, 0)
    rows = trajectory.flight(shooter, angle, speed, distance + 0.55)
    x0, z0, tx, tz = shooter.release(angle)
    for x, z, vx, vz, time in rows[::30]:
        expected_z = z0 + (x - x0) * tz / tx - trajectory.G * (x - x0) ** 2 / (2 * (speed * tx) ** 2)
        assert abs(z - expected_z) < 1e-9
        assert abs(vz - (speed * tz - trajectory.G * time)) < 1e-9
    check = trajectory.aperture_clearance(rows, distance, shooter.lip_height_m,
                                         shooter.ball_diameter_m / 2)
    assert check["descending_entry"] and check["aperture_plane_clear"]
    assert check["swept_sphere_clearance_lower_bound_mm"] > 50
    # A center near the side wall crosses the polygon, but the full ball clips it.
    clipped = trajectory.aperture_clearance(rows, distance, shooter.lip_height_m,
                                           shooter.ball_diameter_m / 2, lateral_m=0.245)
    assert clipped["entire_ball_crossed_plane"] and not clipped["aperture_plane_clear"]
    assert clipped["swept_sphere_clearance_lower_bound_mm"] < 0
    assert trajectory.aimed_speed(shooter, angle, distance, 1) > speed
    assert math.isclose(shooter.rpm(5), 60 * 5 / (math.pi * 0.05))
    # Drag integration must converge at the aperture, where clearance matters.
    drag_speed = trajectory.aimed_speed(shooter, angle, distance, 1)
    coarse = trajectory.flight(shooter, angle, drag_speed, 2.0889, 1, dx=0.004)[-1]
    fine = trajectory.flight(shooter, angle, drag_speed, 2.0889, 1, dx=0.002)[-1]
    assert abs(coarse[1] - fine[1]) < 1e-7

    # Check the entire specified hood range, not just the three exported variants.
    minimum_motor_clearance = math.inf
    for angle in range(55, 73):
        for cd in (0, 1):
            speed = trajectory.aimed_speed(shooter, angle, 2.5, cd)
            rows = trajectory.flight(shooter, angle, speed, 3.05, cd)
            motor = trajectory.motor_clearance(shooter, angle, rows)
            assert motor["exceeds_3mm_clearance"]
            assert motor["sampled_sphere_clearance_mm"] >= motor["continuous_clearance_lower_bound_mm"]
            minimum_motor_clearance = min(minimum_motor_clearance,
                                          motor["continuous_clearance_lower_bound_mm"])
    assert minimum_motor_clearance > 6.7
    # The former forward, same-height motor location actually obstructed the shot.
    rows = trajectory.flight(shooter, 65, 6, 0.3, 0, dx=0.001)
    former_clearance = min(math.hypot(row[0] - 0.0762,
                                     row[1] - shooter.deck_m - shooter.shaft_above_deck_m)
                           - 0.02187 - shooter.ball_diameter_m / 2 for row in rows)
    assert former_clearance < 0


if __name__ == "__main__":
    test_exit_ballistics_and_whole_ball_clearance()
    print("Shooter trajectory check passed")
