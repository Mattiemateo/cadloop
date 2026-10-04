"""Actual-solid mold check; run inside the validated restricted Docker profile.

This checks geometric paths and fit, not casting flow, sealing or print strength.
"""

import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "examples/biobuzz_shooter"))
import mold


def test_mold_solids_and_casting_paths():
    lower, upper = mold.mold_halves()
    core = mold.flywheel_core()
    mandrel = mold.shaft_mandrel()
    parts = (lower, upper, core, mandrel)
    for part in parts:
        assert part.isValid() and len(part.Solids()) == 1
    for index, first in enumerate(parts):
        for second in parts[index + 1:]:
            assert first.intersect(second).Volume() < 1e-6
    for part, zmin, zmax in ((lower, -26, 3), (upper, 0, 34)):
        bounds = part.BoundingBox()
        for actual, expected in ((bounds.xmin, -64), (bounds.xmax, 64),
                                 (bounds.ymin, -64), (bounds.ymax, 64),
                                 (bounds.zmin, zmin), (bounds.zmax, zmax)):
            assert abs(actual - expected) < 1e-6
    assert abs(mandrel.BoundingBox().zmin + 25) < 1e-6
    assert abs(mandrel.BoundingBox().zmax - 25) < 1e-6
    # Measure the bore/seat bracket with solids independent of the fitted mandrel.
    undersize = mold.hex_shaft(50.19, 5.09).translate((0, 0, -25.095))
    assert sum(part.intersect(undersize).Volume() for part in (lower, upper, core)) < 1e-6
    oversize = mold.hex_shaft(50.2, 5.11).translate((0, 0, -25.1))
    assert all(part.intersect(oversize).Volume() > 1e-4 for part in (lower, upper, core))
    # A full planar outer face supports cavity-up printing after a 180° flip.
    top_area = sum(face.Area() for face in upper.Faces()
                   if abs(face.BoundingBox().zmin - 34) < 1e-6
                   and abs(face.BoundingBox().zmax - 34) < 1e-6)
    expected_area = 128 ** 2 - math.pi * (4 * 1.7 ** 2 + 3 * 0.75 ** 2 + 6 ** 2)
    assert abs(top_area - expected_area) < 1e-5

    def assert_void(probe):
        assert sum(part.intersect(probe).Volume() for part in parts) < 1e-6

    # Continuous positive-area paths from inside the actual tire cavity to air.
    assert_void(mold.cylinder(2.99, -19.9, 53.9, mold.FILL_CENTER))
    assert_void(mold.cylinder(5.9, 33.9, 0.05, mold.FILL_CENTER))
    for center in mold.VENT_CENTERS:
        assert_void(mold.cylinder(0.74, -19.9, 53.95, center))

    for center in mold.CLAMP_CENTERS:
        assert_void(mold.cylinder(1.69, -26, 60, center))
        pocket = mold.box(5.59, 5.59, -25.99, 2.78, center)
        assert lower.intersect(pocket).Volume() < 1e-6
        # The square corner is solid again above the 2.8 mm deep pocket floor.
        material = mold.box(0.1, 0.1, -23.19, 0.1, (center[0] + 2.6, center[1] + 2.6))
        assert abs(lower.intersect(material).Volume() - material.Volume()) < 1e-8

    cap = lower.intersect(mold.box(128, 128, 0, 3))
    assert abs(cap.Volume() - 2 * math.pi * 2 ** 2 * 3) < 1e-6
    for center in mold.PIN_CENTERS:
        hole = mold.cylinder(2.09, 0, 3.19, center)
        assert upper.intersect(hole).Volume() < 1e-6
        blind_floor = mold.cylinder(2.09, 3.21, 0.1, center)
        assert abs(upper.intersect(blind_floor).Volume() - blind_floor.Volume()) < 1e-6

    small = mold.mold_halves(99)
    large = mold.mold_halves(102)
    # Actual removed volume must respond to diameter, with the core held fixed.
    expected_per_half = math.pi * ((102 / 2) ** 2 - (99 / 2) ** 2) * 20
    for before, after in zip(small, large):
        assert abs(before.Volume() - after.Volume() - expected_per_half) < 1e-5
    for invalid in (98.9, 102.1, math.nan, math.inf):
        try:
            mold.mold_halves(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid cavity dimension was accepted")
    print(json.dumps({"status": "GEOMETRY_CHECK_PASSED", "volumes_mm3": {
        "mold_lower": lower.Volume(), "mold_upper": upper.Volume(), "core_insert": core.Volume(),
        "shaft_mandrel_reference": mandrel.Volume()},
        "scope": "solid validity, nonoverlap, flat print face, mandrel fit, fill/vent paths, clamps, alignment and cavity response"}, indent=2))


if __name__ == "__main__":
    test_mold_solids_and_casting_paths()
