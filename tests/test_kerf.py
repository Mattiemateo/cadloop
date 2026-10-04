"""Adapter boundaries plus independently measured import/repair regressions."""
import copy
import math
from pathlib import Path

import pytest

pytest.importorskip("kerf_schemas")

from cadloop.cli import main
from cadloop.contracts import Requirements
from cadloop.errors import CadLoopError
from cadloop.kerf import import_project, normalize_spec
from cadloop.util import file_hash, read_json, write_json

EXAMPLE = Path(__file__).parents[1] / "examples" / "kerf_carrier"


def inputs():
    return read_json(EXAMPLE / "spec.json"), Requirements.model_validate(read_json(EXAMPLE / "requirements.json"))


def create(root, code=None):
    return import_project(root, spec=EXAMPLE / "spec.json", code=code or EXAMPLE / "model.py",
                          requirements=EXAMPLE / "requirements.json", part="carrier")


def test_mm_inches_and_original_provenance(tmp_path):
    spec, req = inputs()
    imperial = copy.deepcopy(spec)
    imperial["part_spec"]["units"] = "in"
    for parameter in imperial["parameters"]:
        parameter["unit"] = "in"
        parameter["value"] /= 25.4
        for bound in ("min", "max"):
            parameter["constraints"][bound] /= 25.4
    assert normalize_spec(imperial, req) == pytest.approx(normalize_spec(spec, req))
    project = create(tmp_path / "imported")
    assert read_json(project.root / "requirements.json") == read_json(EXAMPLE / "requirements.json")
    assert (project.design / "kerf_model.py").read_text() == (EXAMPLE / "model.py").read_text()
    assert "original_spec" in project.inspect(source=True)["source"]


@pytest.mark.parametrize("fault", ["duplicate", "unknown_feature_parameter", "unit", "bounds", "expression", "nan", "boolean", "string", "version"])
def test_bad_spec_is_rejected(fault):
    spec, req = inputs()
    p = spec["parameters"][0]
    if fault == "duplicate": spec["parameters"].append(copy.deepcopy(p))
    elif fault == "unknown_feature_parameter": spec["feature_sequence"][0]["parameters"].append("missing")
    elif fault == "unit": p["unit"] = "furlong"
    elif fault == "bounds": p["constraints"]["min"] = 49
    elif fault == "expression": p["constraints"]["expression"] = "length > width"
    elif fault == "nan": p["value"] = float("nan")
    elif fault == "boolean": p["value"] = True
    elif fault == "string": p["value"] = "50"
    elif fault == "version": spec.pop("schema_version")
    with pytest.raises((ValueError, CadLoopError)):
        normalize_spec(spec, req)


def test_import_does_not_execute_and_cannot_overwrite(tmp_path):
    code = tmp_path / "untrusted.py"
    code.write_text("raise RuntimeError('Import must not execute this')\n")
    project = create(tmp_path / "new", code)
    before = project.revision()
    with pytest.raises(CadLoopError, match="overwrites"):
        create(project.root, code)
    assert project.revision() == before


def test_import_cli(tmp_path, capsys):
    assert main(["import-kerf", str(tmp_path / "cli"), "--spec", str(EXAMPLE / "spec.json"),
                 "--code", str(EXAMPLE / "model.py"), "--requirements", str(EXAMPLE / "requirements.json"),
                 "--part", "carrier"]) == 0
    assert '"status": "INITIALIZED"' in capsys.readouterr().out


def test_angles_and_integer_counts():
    spec, req = inputs()
    angle, count = spec["parameters"][:2]
    angle.update(value=math.pi / 2, unit="rad", constraints={"min": 0, "max": math.pi})
    count.update(value=4, unit="count", constraints={"min": 1, "max": 8})
    req.parameters["length"] = req.parameters["length"].model_copy(update={"unit": "deg", "minimum": 0, "maximum": 180})
    req.parameters["width"] = req.parameters["width"].model_copy(update={"kind": "integer", "unit": "count", "minimum": 1, "maximum": 8})
    values = normalize_spec(spec, req)
    assert values["length"] == pytest.approx(90)
    assert values["width"] == 4 and type(values["width"]) is int
    count["value"] = 4.5
    with pytest.raises(ValueError, match="integer"):
        normalize_spec(spec, req)


def test_missing_interface_parameter_needs_input():
    spec, req = inputs()
    spec["parameters"] = [p for p in spec["parameters"] if p["name"] != "mount_x"]
    with pytest.raises(CadLoopError) as error:
        normalize_spec(spec, req)
    assert error.value.code == "NEEDS_INPUT"


@pytest.mark.integration
@pytest.mark.parametrize("context_manager", [False, True])
def test_ignored_parameter_does_not_clear_failed_interface(tmp_path, context_manager):
    pytest.importorskip("build123d")
    source = (EXAMPLE / "model.py").read_text().replace('p["bore_diameter"] / 2', '10')
    if context_manager:
        source = source.replace("result = carrier(params)",
                                "from build123d import BuildPart, add\nshape = carrier(params)\nwith BuildPart() as part:\n    add(shape)")
    code = tmp_path / "ignores_bore.py"
    code.write_text(source)
    project = create(tmp_path / "ignores_bore", code)
    project.propose({"base_revision": project.revision(), "parameters": {"bore_diameter": 22},
                     "reason": "A nominal parameter change cannot hide an unchanged undersized bore"})
    report = project.evaluate(mode="trusted-native", render=False)
    assert report["blocker_ids"] == ["interfaces"]
    assert not report["geometry_accepted"]
    revision = project.revision()
    approved = file_hash(project.root / "requirements.json")
    scope = project.inspect(source=True, path="kerf_model.py")
    assert "Cylinder(10," in scope["source"]
    with pytest.raises(SyntaxError):
        project.propose({"base_revision": revision, "reason": "Invalid repair rolls back",
                         "edits": [{"path": "kerf_model.py", "old": "def carrier(p):", "new": "def carrier(p)"}]})
    assert project.revision() == revision
    project.propose({"base_revision": revision, "reason": "Repair only the ignored bore parameter",
                     "edits": [{"path": "kerf_model.py", "old": "Cylinder(10,", "new": 'Cylinder(p["bore_diameter"] / 2,'}]})
    with pytest.raises(CadLoopError, match="different design revision"):
        project.propose({"base_revision": revision, "reason": "Stale repair must fail", "parameters": {"thickness": 10}})
    assert project.evaluate(mode="trusted-native", render=False)["geometry_accepted"]
    assert file_hash(project.root / "requirements.json") == approved


@pytest.mark.integration
def test_inches_rebuild_equivalent_geometry(tmp_path):
    pytest.importorskip("build123d")
    spec, _ = inputs()
    imperial = copy.deepcopy(spec)
    imperial["part_spec"]["units"] = "in"
    for parameter in imperial["parameters"]:
        parameter["unit"] = "in"
        parameter["value"] /= 25.4
        for bound in ("min", "max"):
            parameter["constraints"][bound] /= 25.4
    spec_path = tmp_path / "imperial.json"
    write_json(spec_path, imperial)
    metric = create(tmp_path / "metric")
    inches = import_project(tmp_path / "inches", spec=spec_path, code=EXAMPLE / "model.py",
                            requirements=EXAMPLE / "requirements.json", part="carrier")
    for project in (metric, inches):
        project.propose({"base_revision": project.revision(), "parameters": {"bore_diameter": 22}, "reason": "Correct the fixture bore"})
        assert project.evaluate(mode="trusted-native", render=False)["geometry_accepted"]
    from cadloop import kernel
    a = kernel.read_brep(metric.latest()[0] / "geometry/assembly.brep")
    b = kernel.read_brep(inches.latest()[0] / "geometry/assembly.brep")
    assert kernel.difference_volume(a, b) + kernel.difference_volume(b, a) < 1e-5


@pytest.mark.integration
def test_import_repair_export_and_parameter_response(tmp_path):
    pytest.importorskip("build123d")
    project = create(tmp_path / "carrier")
    state = project.state()
    bad = project.evaluate(mode="trusted-native", render=False)
    assert not bad["geometry_accepted"] and "interfaces" in bad["blocker_ids"]
    assert project.inspect(check="interfaces")["check"]["status"] == "fail"
    project.propose({"base_revision": state["revision"], "parameters": {"bore_diameter": 22}, "reason": "Repair measured bore"})
    final = project.finish(mode="trusted-native")
    assert final["geometry_accepted"] and final["exported"] and not final["engineering_approved"]
    assert Path(final["export_directory"], "geometry", "assembly.step").is_file()
    original = project.inspect(part="carrier")["metrics"]
    project.propose({"base_revision": project.revision(), "parameters": {"thickness": 10}, "reason": "Test independent thickness response"})
    changed = project.evaluate(mode="trusted-native", render=False)
    # The variant correctly fails the fixed 8 mm delivery target. Its other
    # interfaces must still pass, and its measured thickness must really change.
    assert changed["blocker_ids"] == ["thickness"]
    assert project.inspect(check="interfaces")["check"]["status"] == "pass"
    measured = project.inspect(part="carrier")["metrics"]
    assert measured["bounds_mm"]["size"] == pytest.approx([50, 40, 10])
    assert measured["volume_mm3"] / original["volume_mm3"] == pytest.approx(10 / 8)


def test_equal_mass_wrong_pattern_is_rejected():
    import cadquery as cq
    from cadloop.checks import check_one
    from cadloop.contracts import HolesCheck, Hole
    from cadloop import kernel

    def plate(spacing):
        points = [(x, y) for x in (-spacing, spacing) for y in (-7, 7)]
        return cq.Workplane("XY").box(40, 30, 6).faces(">Z").workplane().pushPoints(points).hole(4).val().wrapped

    reference, wrong = plate(10), plate(14)
    a, b = kernel.metrics(reference), kernel.metrics(wrong)
    assert a["bounds_mm"]["size"] == pytest.approx(b["bounds_mm"]["size"])
    assert a["volume_mm3"] == pytest.approx(b["volume_mm3"])
    assert kernel.difference_volume(reference, wrong) + kernel.difference_volume(wrong, reference) == pytest.approx(603.185789, abs=1e-5)
    check = HolesCheck(id="pattern", kind="through_holes_z", part="carrier", description="Approved mounting pattern",
                       holes=[Hole(x=x, y=y, radius=2) for x in (-10, 10) for y in (-7, 7)])
    _, req = inputs()
    assert check_one(check, {"carrier": reference}, req)["status"] == "pass"
    assert check_one(check, {"carrier": wrong}, req)["status"] == "fail"
