"""Equivalent build123d authoring fixture; optional runtime (not tested here).

The verification/registry contract is identical to the CadQuery fixture.
"""
from build123d import Box, Cylinder, Pos, Align
from cadloop.authoring import Scene

MOUNT_HOLES = [(-28, -16), (-28, 16), (28, -16), (28, 16)]
BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)


def plate(thickness, bore_diameter):
    body = Box(80, 50, thickness, align=BOTTOM)
    body -= Pos(0, 0, -1) * Cylinder(bore_diameter / 2, thickness + 2, align=BOTTOM)
    for x, y in MOUNT_HOLES:
        body -= Pos(x, y, -1) * Cylinder(1.6, thickness + 2, align=BOTTOM)
    return body


def spacer(length):
    return Cylinder(9, length, align=BOTTOM) - Pos(0, 0, -1) * Cylinder(4, length + 2, align=BOTTOM)


def build(p):
    scene = Scene()
    t = p["plate_thickness_mm"]
    scene.add("lower_plate", plate(t, p["bore_diameter_mm"]), feature="lower_plate",
              parameters=("plate_thickness_mm", "bore_diameter_mm"))
    scene.add("upper_plate", Pos(p["upper_dx_mm"], 0, t + p["gap_mm"]) * plate(t, p["bore_diameter_mm"]),
              feature="place_upper_plate",
              parameters=("plate_thickness_mm", "bore_diameter_mm", "upper_dx_mm", "gap_mm"))
    if p["include_spacer"]:
        scene.add("spacer", Pos(0, 0, t) * spacer(p["spacer_length_mm"]),
                  feature="spacer_between_mounting_faces",
                  parameters=("spacer_length_mm", "plate_thickness_mm", "include_spacer"))
    return scene
