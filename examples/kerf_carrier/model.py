"""Kerf's source convention: injected params, final shape named result."""
from build123d import Align, Box, Cylinder, Pos


def carrier(p):
    alignment = (Align.CENTER, Align.CENTER, Align.MIN)
    shape = Box(p["length"], p["width"], p["thickness"], align=alignment)
    shape -= Cylinder(p["bore_diameter"] / 2, p["thickness"], align=alignment)
    for x in (-p["mount_x"], p["mount_x"]):
        for y in (-p["mount_y"], p["mount_y"]):
            shape -= Pos(x, y) * Cylinder(p["mount_diameter"] / 2, p["thickness"], align=alignment)
    return shape


result = carrier(params)
