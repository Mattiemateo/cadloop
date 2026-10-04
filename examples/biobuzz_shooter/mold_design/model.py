"""Two-piece insert mold for the BIOBUZZ flywheel's cast silicone tire.

All dimensions are millimeters. The fixed printed core is cast into the tire;
this mold does not make a separate ring. The wheel axis is Z, centered at Z=0.
Nominal cavity diameter has no assumed material shrink compensation. Verify the
selected silicone's shrinkage, release agent, print sealing and fill procedure.
Use a released, masked 50 mm long stock 5 mm hex mandrel during the pour. The
clearance around it is not a validated liquid seal; remove it after curing.
"""

import math

import cadquery as cq
from cadloop.authoring import Scene
from fabricated import flywheel_core, hex_shaft


CLAMP_CENTERS = tuple((x, y) for x in (-56, 56) for y in (-56, 56))
PIN_CENTERS = ((-56, 0), (56, 0))
FILL_CENTER = (0, 46)
VENT_CENTERS = ((46, 0), (0, -46), (-46, 0))


def cylinder(radius, z0, height, xy=(0, 0)):
    return cq.Solid.makeCylinder(radius, height, cq.Vector(*xy, z0))


def box(width, depth, z0, height, xy=(0, 0)):
    return cq.Workplane("XY").box(width, depth, height, centered=(True, True, False)).val().translate(
        (xy[0], xy[1], z0))


def shaft_mandrel():
    return hex_shaft(50).translate((0, 0, -25))


def mold_halves(cavity_diameter_mm=100):
    if not math.isfinite(cavity_diameter_mm) or not 99 <= cavity_diameter_mm <= 102:
        raise ValueError("Mold cavity diameter must be between 99 and 102 mm")
    # Core flats nominally contact Z=±20 floors. Hub-seat clearance is 0.1 mm;
    # the mandrel has 0.1 mm across-flats/axial clearance. Neither proves a liquid seal.
    cavity = cylinder(cavity_diameter_mm / 2, -20, 40).fuse(cylinder(9.1, -22.1, 44.2))
    cavity = cavity.fuse(hex_shaft(50.2, 5.1).translate((0, 0, -25.1)))
    lower = box(128, 128, -26, 26).cut(cavity)
    upper = box(128, 128, 0, 34).cut(cavity)

    for center in CLAMP_CENTERS:
        clamp_bore = cylinder(1.7, -27, 62, center)
        lower = lower.cut(clamp_bore).cut(box(5.6, 5.6, -26.1, 2.9, center))
        upper = upper.cut(clamp_bore)

    for center in PIN_CENTERS:
        lower = lower.fuse(cylinder(2, -1, 4, center))
        upper = upper.cut(cylinder(2.1, -0.1, 3.3, center))

    # At R46 the complete fill bore (R3) remains within even the Ø99 cavity,
    # outside the core's R40 flanges/keys. The same applies to all three vents.
    # Flat outer face at Z=34 prints on the bed; the funnel is recessed in the cap.
    upper = upper.cut(cylinder(3, 19.9, 6.2, FILL_CENTER))
    funnel = cq.Solid.makeCone(3, 6, 8, cq.Vector(*FILL_CENTER, 26))
    upper = upper.cut(funnel)
    for center in VENT_CENTERS:
        upper = upper.cut(cylinder(0.75, 19.9, 14.2, center))
    return lower.clean(), upper.clean()


def build(p):
    lower, upper = mold_halves(p.get("mold_cavity_diameter_mm", 100))
    scene = Scene()
    scene.add("mold_lower", lower, feature="lower_insert_mold_with_pins_and_square_nut_pockets",
              parameters=("mold_cavity_diameter_mm",))
    scene.add("mold_upper", upper, feature="upper_insert_mold_with_fill_funnel_and_vents",
              parameters=("mold_cavity_diameter_mm",))
    scene.add("core_insert", flywheel_core(), feature="reused_flywheel_core_cast_into_tire")
    scene.add("shaft_mandrel_reference", shaft_mandrel(), feature="stock_5mm_hex_mandrel_cut_to_50mm")
    return scene
