"""Measure the reusable part solids, rather than trusting their input values."""

from math import pi, sqrt

import cadquery as cq
import pytest

from parts.standard_parts import (
    bearing608_reference,
    bearing_carrier_608,
    bearing_retainer_608,
    flanged_hex_sleeve_608,
)


def _material_at(shape, x, y, z):
    probe = cq.Solid.makeBox(0.02, 0.02, 0.02, cq.Vector(x - 0.01, y - 0.01, z - 0.01))
    return shape.intersect(probe).Volume() > 1e-6


def _bounds(shape, expected):
    assert isinstance(shape, cq.Solid)
    assert shape.isValid()
    assert len(shape.Solids()) == 1
    box = shape.BoundingBox()
    assert (box.xlen, box.ylen, box.zlen) == pytest.approx(expected, abs=1e-6)
    assert (box.zmin, box.xmin, box.ymin) == pytest.approx((0, -expected[0] / 2, -expected[1] / 2), abs=1e-6)


def test_carrier_seat_shoulder_and_independent_clearance():
    carrier = bearing_carrier_608()
    _bounds(carrier, (42, 42, 10.15))
    expected = 42**2 * 10.15 - pi * (9.6**2 * 10.15 + (11.075**2 - 9.6**2) * 7.15 + 4 * 1.7**2 * 10.15)
    assert carrier.Volume() == pytest.approx(expected, abs=1e-4)
    assert _material_at(carrier, 10.5, 0, 1.5)
    assert not _material_at(carrier, 10.5, 0, 5)
    assert not _material_at(carrier, 0, 0, 1)
    assert not _material_at(carrier, 15, 15, 1)

    larger_seat = bearing_carrier_608(0.25)
    assert not _material_at(larger_seat, 11.10, 0, 5)
    assert _material_at(carrier, 11.10, 0, 5)
    assert carrier.Volume() == pytest.approx(expected, abs=1e-4)


def test_retainer_square_nut_pockets_open_top_exactly():
    retainer = bearing_retainer_608()
    _bounds(retainer, (42, 42, 3.4))
    expected = 42**2 * 3.4 - pi * (9.6**2 + 4 * 1.7**2) * 3.4 - 4 * (5.6**2 - pi * 1.7**2) * 2.8
    assert retainer.Volume() == pytest.approx(expected, abs=1e-4)
    assert not _material_at(retainer, 17.75, 17.75, 3.0)
    assert _material_at(retainer, 17.85, 17.75, 3.0)
    assert _material_at(retainer, 17.75, 17.75, 0.59)
    assert not _material_at(retainer, 17.75, 17.75, 0.61)
    assert not _material_at(retainer, -15, -15, 0.3)


def test_hex_sleeve_flange_and_bore():
    sleeve = flanged_hex_sleeve_608()
    _bounds(sleeve, (11, 11, 8.1))
    expected = pi * (3.975**2 * 6.9 + 5.5**2 * 1.2) - sqrt(3) / 2 * 5.1**2 * 8.1
    assert sleeve.Volume() == pytest.approx(expected, abs=1e-4)
    assert not _material_at(sleeve, 0, 2.50, 2)
    assert _material_at(sleeve, 0, 2.60, 2)
    assert not _material_at(sleeve, 2.92, 0, 2)
    assert _material_at(sleeve, 2.97, 0, 2)
    assert not _material_at(sleeve, 5, 0, 6)
    assert _material_at(sleeve, 5, 0, 7.5)


def test_bearing_is_labeled_nominal_external_envelope():
    bearing = bearing608_reference()
    _bounds(bearing, (22, 22, 7))
    assert bearing.Volume() == pytest.approx(pi * (11**2 - 4**2) * 7, abs=1e-4)
    assert not _material_at(bearing, 0, 0, 3)
