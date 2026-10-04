"""Physical-geometry invariance and local through-bore regression coverage."""
import math
from pathlib import Path

import cadquery as cq
import pytest

from cadloop import kernel as k
from cadloop.checks import run_checks
from cadloop.contracts import Requirements
from cadloop.project import Project
from cadloop.util import read_json, write_json


def bore_requirements():
    return Requirements(
        name="Local through bore", description="Complete analytic Z bore",
        expected_parts=["plate"], parameters={},
        checks=[dict(id="bore", kind="through_holes_z", description="8 mm through bore",
                     part="plate", holes=[dict(x=0, y=0, radius=4)])],
        engineering_blockers=["Nominal geometry only"],
    )


def plate():
    return cq.Solid.makeBox(30, 20, 6, cq.Vector(-10, -10, 0))


def through_plate():
    return plate().cut(cq.Solid.makeCylinder(4, 8, cq.Vector(0, 0, -1)))


def check_result(parts, req, name):
    return next(check for check in run_checks(parts, req) if check["id"] == name)


@pytest.mark.parametrize("z", [-2, 6])
def test_remote_boss_does_not_change_throughness(z):
    baseline = through_plate()
    boss = cq.Solid.makeBox(5, 5, 2, cq.Vector(12, -2.5, z))
    shape = baseline.fuse(boss).clean().wrapped
    result = check_result({"plate": shape}, bore_requirements(), "bore")
    assert result["status"] == "pass"
    match = result["evidence"]["matches"][0]
    assert match["through"]
    assert all(rim["open"] for rim in match["opening_check"]["rims"])
    assert match["lumen_check"]["obstruction_mm3"] == 0
    assert match["lumen_check"]["z_span_mm"] == pytest.approx([min(z, 0), max(z + 2, 6)])


@pytest.mark.parametrize("bottom", [False, True])
def test_blind_bore_retains_rejection(bottom):
    z = -1 if bottom else 3
    shape = plate().cut(cq.Solid.makeCylinder(4, 4, cq.Vector(0, 0, z))).wrapped
    result = check_result({"plate": shape}, bore_requirements(), "bore")
    assert result["status"] == "fail"
    assert result["evidence"]["defects"][0]["reason"] == "BLIND_OR_PARTIAL_HOLE"
    rims = result["evidence"]["matches"][0]["opening_check"]["rims"]
    assert sum(rim["open"] for rim in rims) == 1


@pytest.mark.parametrize("kind", ["countersink", "counterbore", "open_slot", "top_notch"])
def test_partial_bore_geometry_remains_rejected(kind):
    if kind == "countersink":
        shape = plate().cut(cq.Solid.makeCylinder(4, 5, cq.Vector(0, 0, -1)))
        shape = shape.cut(cq.Solid.makeCone(4, 6, 2, cq.Vector(0, 0, 4)))
    elif kind == "counterbore":
        shape = through_plate().cut(cq.Solid.makeCylinder(6, 3, cq.Vector(0, 0, 4)))
    else:
        z, height = (-1, 8) if kind == "open_slot" else (4, 3)
        shape = through_plate().cut(cq.Solid.makeBox(25, 4, height, cq.Vector(0, -2, z)))
    result = check_result({"plate": shape.clean().wrapped}, bore_requirements(), "bore")
    assert result["status"] != "pass"


def test_middepth_side_pocket_policy_is_unchanged():
    # The existing contract checks open end rims and the lumen, not full-depth
    # bearing-wall support. Do not silently resolve that separate policy question.
    shape = through_plate().cut(cq.Solid.makeBox(25, 12, 2, cq.Vector(0, -6, 2)))
    assert check_result({"plate": shape.clean().wrapped}, bore_requirements(), "bore")["status"] == "pass"


@pytest.mark.parametrize("z,height", [(0, 1), (2.5, 1), (5, 1), (2.5, .01)])
def test_local_openings_do_not_bypass_obstruction(z, height):
    bridge = cq.Solid.makeBox(10, 1, height, cq.Vector(-5, -.5, z))
    shape = through_plate().fuse(bridge).clean().wrapped
    assert check_result({"plate": shape}, bore_requirements(), "bore")["status"] != "pass"


def test_bore_can_be_thinner_than_feature_match_tolerance():
    shape = cq.Solid.makeBox(20, 20, .0005, cq.Vector(-10, -10, 0))
    shape = shape.cut(cq.Solid.makeCylinder(4, 2, cq.Vector(0, 0, -1))).wrapped
    assert check_result({"plate": shape}, bore_requirements(), "bore")["status"] == "pass"


def test_z_rotation_retains_bore_but_arbitrary_tilt_is_unsupported():
    shape = through_plate()
    rotated = shape.rotate((0, 0, 0), (0, 0, 1), 37).wrapped
    assert check_result({"plate": rotated}, bore_requirements(), "bore")["status"] == "pass"
    tilted = shape.rotate((0, 0, 0), (0, 1, 0), 5).wrapped
    result = check_result({"plate": tilted}, bore_requirements(), "bore")
    assert result["status"] == "indeterminate" and result["code"] == "FEATURE_UNSUPPORTED"


def coaxial_requirements(*, swapped=False, max_offset=.01, max_angle=.002):
    return Requirements(
        name="Axis invariance", description="Offsets refer to physical geometry",
        expected_parts=["a", "b"], parameters={},
        refs={"a_bore": dict(kind="cylinder", part="a", radius=4),
              "b_bore": dict(kind="cylinder", part="b", radius=4)},
        checks=[dict(id="aligned", kind="coaxial", description="Allowed axis offset and angle",
                     a="b_bore" if swapped else "a_bore", b="a_bore" if swapped else "b_bore",
                     max_offset=max_offset, max_angle_deg=max_angle)],
        engineering_blockers=["Nominal geometry only"],
    )


def coaxial_parts(origin=-1, *, angle=.001, x_offset=0, reverse=False):
    radians = math.radians(angle)
    axis = cq.Vector(math.sin(radians), 0, math.cos(radians))
    a = cq.Solid.makeBox(20, 20, 6, cq.Vector(-10, -10, 0))
    a = a.cut(cq.Solid.makeCylinder(4, 8, cq.Vector(0, 0, -1)))
    if reverse:
        start, direction, length = axis.multiply(20), axis.multiply(-1), 20 - origin
    else:
        start, direction, length = axis.multiply(origin), axis, 20 - origin
    start = start.add(cq.Vector(x_offset, 0, 0))
    b = cq.Solid.makeBox(20, 20, 6, cq.Vector(-10, -10, 10))
    b = b.cut(cq.Solid.makeCylinder(4, length, start, direction)).clean()
    return {"a": a.wrapped, "b": b.wrapped}


@pytest.mark.parametrize("origin", [-1, -1000, -10000])
@pytest.mark.parametrize("swapped", [False, True])
def test_coaxial_offset_is_independent_of_surface_origins_and_reference_order(origin, swapped):
    parts = coaxial_parts(origin)
    result = check_result(parts, coaxial_requirements(swapped=swapped), "aligned")
    assert result["status"] == "pass"
    evidence = result["evidence"]
    assert evidence["offset_mm"] == pytest.approx(16 * math.tan(math.radians(.001)), abs=1e-10)
    assert evidence["z_span_mm"] == pytest.approx([0, 16])
    assert evidence["endpoint_offsets_mm"] == pytest.approx([0, evidence["offset_mm"]], abs=1e-10)


def test_equivalent_brep_geometry_has_equivalent_coaxial_measurement():
    short, long = coaxial_parts(-1), coaxial_parts(-1000)
    assert k.difference_volume(short["b"], long["b"]) == 0
    assert k.difference_volume(long["b"], short["b"]) == 0
    a = check_result(short, coaxial_requirements(), "aligned")
    b = check_result(long, coaxial_requirements(), "aligned")
    assert a["status"] == b["status"] == "pass"
    assert a["evidence"]["offset_mm"] == pytest.approx(b["evidence"]["offset_mm"], abs=1e-10)


def test_coaxial_offset_is_invariant_to_reversed_direction_and_translation():
    parts = coaxial_parts(-1000, reverse=True)
    parts = {name: cq.Shape.cast(shape).translate((12, -7, 35)).wrapped for name, shape in parts.items()}
    result = check_result(parts, coaxial_requirements(), "aligned")
    assert result["status"] == "pass"
    assert result["evidence"]["offset_mm"] == pytest.approx(16 * math.tan(math.radians(.001)), abs=1e-10)


@pytest.mark.parametrize("swapped", [False, True])
def test_real_axis_offset_remains_rejected(swapped):
    result = check_result(coaxial_parts(-1000, angle=0, x_offset=.02),
                          coaxial_requirements(swapped=swapped), "aligned")
    assert result["status"] == "fail"
    assert result["evidence"]["offset_mm"] == pytest.approx(.02)


def test_angular_limit_is_preserved_independently_of_offset():
    result = check_result(coaxial_parts(-1000), coaxial_requirements(max_angle=.0005), "aligned")
    assert result["status"] == "fail"
    assert result["evidence"]["offset_mm"] < .01
    assert result["evidence"]["angle_deg"] > .0005


def test_axis_divergence_at_physical_ends_is_not_hidden_by_intersecting_lines():
    result = check_result(coaxial_parts(-1000), coaxial_requirements(max_offset=.0002), "aligned")
    assert result["status"] == "fail"
    assert result["evidence"]["endpoint_offsets_mm"][0] == pytest.approx(0, abs=1e-10)
    assert result["evidence"]["offset_mm"] > .0002


@pytest.mark.integration
def test_remote_boss_fresh_project_evaluation(tmp_path):
    reqfile = tmp_path / "requirements.json"
    write_json(reqfile, bore_requirements().model_dump())
    design = tmp_path / "design"
    design.mkdir()
    write_json(design / "parameters.json", {})
    (design / "model.py").write_text('''import cadquery as cq
from cadloop.authoring import Scene

def build(params):
    plate = cq.Solid.makeBox(30,20,6,cq.Vector(-10,-10,0))
    plate = plate.cut(cq.Solid.makeCylinder(4,8,cq.Vector(0,0,-1)))
    plate = plate.fuse(cq.Solid.makeBox(5,5,2,cq.Vector(12,-2.5,6))).clean()
    scene = Scene()
    scene.add("plate", plate)
    return scene
''')
    project = Project.create(tmp_path / "project", requirements=reqfile, design_dir=design)
    result = project.evaluate(mode="trusted-native", force=True, render=False)
    assert result["geometry_accepted"] and not result["cached"]
    run = Path(result["run_directory"])
    project.verify_receipt(run)
    report = read_json(run / "verification/report.json")
    assert all(check["status"] == "pass" for check in report["checks"])


@pytest.mark.integration
def test_coaxial_origin_change_survives_fresh_brep_and_step_verification(tmp_path):
    data = coaxial_requirements().model_dump()
    data["refs"]["a_bore"].update(center_xy=[0, 0], tolerance=1e-8)
    data["refs"]["b_bore"].update(center_xy=[13 * math.tan(math.radians(.001)), 0], tolerance=1e-8)
    data["parameters"] = {"origin": dict(kind="number", unit="mm", minimum=-1000,
                                         maximum=-1, description="Cylinder parameter origin")}
    reqfile = tmp_path / "requirements.json"
    write_json(reqfile, data)
    design = tmp_path / "design"
    design.mkdir()
    write_json(design / "parameters.json", {"origin": -1})
    (design / "model.py").write_text('''import math
import cadquery as cq
from cadloop.authoring import Scene

def build(params):
    angle = math.radians(.001)
    axis = cq.Vector(math.sin(angle), 0, math.cos(angle))
    a = cq.Solid.makeBox(20,20,6,cq.Vector(-10,-10,0))
    a = a.cut(cq.Solid.makeCylinder(4,8,cq.Vector(0,0,-1)))
    b = cq.Solid.makeBox(20,20,6,cq.Vector(-10,-10,10))
    origin = params["origin"]
    b = b.cut(cq.Solid.makeCylinder(4,20-origin,axis.multiply(origin),axis)).clean()
    scene = Scene()
    scene.add("a", a)
    scene.add("b", b)
    return scene
''')
    project = Project.create(tmp_path / "project", requirements=reqfile, design_dir=design)
    results, shapes = [], []
    for origin in (-1, -1000):
        if origin != -1:
            project.propose({"base_revision": project.revision(), "parameters": {"origin": origin},
                             "reason": "Change only the bore parameter origin"})
        feedback = project.evaluate(mode="trusted-native", force=True, render=False)
        assert feedback["geometry_accepted"] and not feedback["cached"]
        run = Path(feedback["run_directory"])
        project.verify_receipt(run)
        report = read_json(run / "verification/report.json")
        assert all(check["status"] == "pass" for check in report["checks"])
        results.append(next(check for check in report["checks"] if check["id"] == "aligned"))
        shapes.append(k.read_brep(run / "geometry/parts/b.brep"))
    assert results[0]["evidence"]["offset_mm"] == pytest.approx(results[1]["evidence"]["offset_mm"], abs=1e-10)
    assert k.difference_volume(shapes[0], shapes[1]) == 0
    assert k.difference_volume(shapes[1], shapes[0]) == 0


@pytest.mark.parametrize("origin", [-1, -1000, -10000])
@pytest.mark.parametrize("reverse,shift", [(False, (0, 0, 0)), (True, (12, -7, 35))])
def test_center_selector_uses_physical_face_datum(origin, reverse, shift):
    parts = coaxial_parts(origin, reverse=reverse)
    parts = {name: cq.Shape.cast(shape).translate(shift).wrapped for name, shape in parts.items()}
    data = coaxial_requirements().model_dump()
    expected_centers = {"a_bore": [shift[0], shift[1]],
                        "b_bore": [shift[0] + 13 * math.tan(math.radians(.001)), shift[1]]}
    for name, center in expected_centers.items():
        data["refs"][name].update(center_xy=center, tolerance=1e-8)
    result = check_result(parts, Requirements.model_validate(data), "aligned")
    assert result["status"] == "pass"
    assert result["evidence"]["axis_b"]["reference_z_mm"] == pytest.approx(13 + shift[2])
    assert result["evidence"]["axis_b"]["reference_center_xy_mm"] == pytest.approx(expected_centers["b_bore"], abs=1e-10)


def test_physical_center_selector_still_rejects_a_different_bore_location():
    data = coaxial_requirements().model_dump()
    data["refs"]["b_bore"].update(center_xy=[0, 0])
    result = check_result(coaxial_parts(-1000, x_offset=.02), Requirements.model_validate(data), "aligned")
    assert result["status"] == "indeterminate" and result["code"] == "REF_MISSING"


@pytest.mark.parametrize("offset,status", [(.009998, "pass"), (.01, "indeterminate"), (.010002, "fail")])
@pytest.mark.parametrize("swapped", [False, True])
def test_coaxial_offset_boundary_and_order_remain_conservative(offset, status, swapped):
    result = check_result(coaxial_parts(-1000, angle=0, x_offset=offset),
                          coaxial_requirements(swapped=swapped), "aligned")
    assert result["status"] == status


def test_coaxial_angular_boundary_remains_indeterminate():
    result = check_result(coaxial_parts(-1000), coaxial_requirements(max_angle=.001), "aligned")
    assert result["status"] == "indeterminate"
    assert result["code"] == "NUMERICAL_BOUNDARY"


def test_coaxial_offset_is_invariant_to_rigid_z_rotation():
    parts = {name: cq.Shape.cast(shape).rotate((0, 0, 0), (0, 0, 1), 37).wrapped
             for name, shape in coaxial_parts(-1000).items()}
    for swapped in (False, True):
        result = check_result(parts, coaxial_requirements(swapped=swapped), "aligned")
        assert result["status"] == "pass"
        assert result["evidence"]["offset_mm"] == pytest.approx(16 * math.tan(math.radians(.001)), abs=1e-10)


@pytest.mark.parametrize("blind", [False, True])
def test_thin_bore_rims_do_not_confuse_opposite_openings(blind):
    height = .0005
    shape = cq.Solid.makeBox(20, 20, height, cq.Vector(-10, -10, 0))
    start = height / 2 if blind else -1
    shape = shape.cut(cq.Solid.makeCylinder(4, 2, cq.Vector(0, 0, start))).clean()
    # Give the legitimate through bore remote material above and below its rims.
    if not blind:
        shape = shape.fuse(cq.Solid.makeBox(2, 2, 2, cq.Vector(7, -1, -1))).clean()
    result = check_result({"plate": shape.wrapped}, bore_requirements(), "bore")
    assert result["status"] == ("fail" if blind else "pass")
    rims = result["evidence"]["matches"][0]["opening_check"]["rims"]
    assert sum(rim["open"] for rim in rims) == (1 if blind else 2)
