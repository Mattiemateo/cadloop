"""Synthetic plate-stack fixture. All dimensions are in mm.

This is a validation demonstrator, not a production robot part. Named functions
keep edits local; the independent verifier reads only the exported solids.
"""
import cadquery as cq
from cadloop.authoring import Scene

MOUNT_HOLES = [(-28, -16), (-28, 16), (28, -16), (28, 16)]


def plate(thickness, bore_diameter):
    body = cq.Workplane("XY").box(80, 50, thickness, centered=(True, True, False)).val()
    central = cq.Solid.makeCylinder(bore_diameter / 2, thickness + 2,
                                    cq.Vector(0, 0, -1))
    body = body.cut(central)
    for x, y in MOUNT_HOLES:
        cutter = cq.Solid.makeCylinder(1.6, thickness + 2, cq.Vector(x, y, -1))
        body = body.cut(cutter)
    return body


def spacer(length):
    outer = cq.Solid.makeCylinder(9, length)
    bore = cq.Solid.makeCylinder(4, length + 2, cq.Vector(0, 0, -1))
    return outer.cut(bore)


def build(p):
    scene = Scene()
    t = p["plate_thickness_mm"]
    scene.add("lower_plate", plate(t, p["bore_diameter_mm"]), feature="lower_plate",
              parameters=("plate_thickness_mm", "bore_diameter_mm"))
    scene.add("upper_plate", plate(t, p["bore_diameter_mm"]).translate(
        (p["upper_dx_mm"], 0, t + p["gap_mm"])), feature="place_upper_plate",
        parameters=("plate_thickness_mm", "bore_diameter_mm", "upper_dx_mm", "gap_mm"))
    if p["include_spacer"]:
        scene.add("spacer", spacer(p["spacer_length_mm"]).translate((0, 0, t)),
                  feature="spacer_between_mounting_faces",
                  parameters=("spacer_length_mm", "plate_thickness_mm", "include_spacer"))
    return scene


_unobstructed_build = build

def build(p):
    scene = _unobstructed_build(p)
    # A real solid bar crosses the otherwise cylindrical lower-plate bore.
    bridge = cq.Solid.makeBox(10, 1, 1, cq.Vector(-5, -0.5, 2.5))
    lower = cq.Shape.cast(scene.parts["lower_plate"])
    scene.parts["lower_plate"] = lower.fuse(bridge).clean().wrapped
    return scene
