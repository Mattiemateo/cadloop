from pathlib import Path

from cadloop.contracts import Requirements
from cadloop.planning.contracts import DesignContract
from cadloop.planning.handoff import SECTIONS, compile_handoff, compile_requirements
from cadloop.util import read_json

FIXTURE = Path(__file__).parents[1] / "benchmarks/planning/fixtures/motor_mount/gold_contract.json"


def contract():
    return DesignContract.model_validate(read_json(FIXTURE))


def test_handoff_sections_order_canonical_values_and_design_freedom():
    text = compile_handoff(contract())
    assert text == compile_handoff(contract())
    positions = [text.index(f"## {section}\n") for section in SECTIONS]
    assert positions == sorted(positions)
    for label in ["motor_size_mm = 42 mm", "extrusion_size_mm = 15 mm",
                  "motor_pattern_mm = 31 mm", "shaft_clearance_mm = 24 mm"]:
        assert text.count(label) == 1
    assert "edge_fillet_mm: FREE" in text
    assert "overall_width_mm: OPTIMIZED" in text
    assert "UNSUPPORTED `shaft_clearance_review`" in text
    assert "independently verify exported BREP/STEP" in text
    assert "Never invent a dimension" in text
    # The conversation/initial brief is unnecessary and is not duplicated.
    assert contract().brief not in text


def test_bounded_and_derived_values_do_not_lose_their_semantics():
    data = contract().model_dump()
    wall = next(p for p in data["parameters"] if p["id"] == "wall_thickness_mm")
    wall.update(mode="BOUNDED", minimum=3.0, maximum=6.0, value=4.0)
    data["parameters"].append({"id": "shaft_axis_reference", "name": "Derived shaft axis", "kind": "number",
                               "mode": "DERIVED", "unit": "mm", "derived_from": ["shaft_clearance_mm"]})
    text = compile_handoff(DesignContract.model_validate(data))
    assert text.count("wall_thickness_mm = 4 mm") == 1
    assert "approved bounds (mm): minimum=3, maximum=6" in text
    assert "shaft_axis_reference: derived from shaft_clearance_mm" in text


def test_adapter_translates_only_explicit_targets_into_existing_requirements():
    output = compile_requirements(contract())
    requirements = Requirements.model_validate(output["requirements"])
    checks = {check.id: check for check in requirements.checks}
    assert checks["motor_width_check"].minimum == 41.99
    assert checks["motor_width_check"].maximum == 42.01
    assert checks["extrusion_width_check"].minimum == 14.99
    assert "motor_orientation" not in requirements.parameters  # Existing Param has no enum semantics.
    unsupported = {issue["id"]: issue for issue in output["unsupported"]}
    assert unsupported["shaft_clearance_review"]["critical"] is True
    assert unsupported["bolt_pattern_review"]["critical"] is True
    assert any("shaft_clearance_review" in blocker for blocker in requirements.engineering_blockers)


def test_stiffness_is_not_replaced_by_a_wall_dimension_check():
    data = contract().model_dump()
    data["requirements"].append({"id": "stiffness", "text": "The mount must be stiff.", "hard": True,
                                 "impact": "CRITICAL", "source_refs": ["src_user_1"]})
    data["verification_intent"].append({"id": "stiffness_review", "text": "Verify stiffness using physical loads.",
                                        "requirement_refs": ["stiffness"], "component_refs": ["mount"], "kind": "manual"})
    next(p for p in data["parameters"] if p["id"] == "wall_thickness_mm").update(mode="FIXED", value=6.0)
    output = compile_requirements(DesignContract.model_validate(data))
    requirements = Requirements.model_validate(output["requirements"])
    assert all(check.id != "stiffness_review" for check in requirements.checks)
    assert any(issue["id"] == "stiffness" for issue in output["unsupported"])
    assert "wall_thickness_mm" in requirements.parameters
    assert not any(check.kind == "dimension" and check.part == "mount" for check in requirements.checks)


def test_no_supported_checks_returns_none_without_invented_verification():
    data = contract().model_dump()
    data["verification_intent"] = [item for item in data["verification_intent"] if item["kind"] == "manual"]
    output = compile_requirements(DesignContract.model_validate(data))
    assert output["requirements"] is None
    assert any(issue["id"] == "shaft_clearance_review" and issue["critical"] for issue in output["unsupported"])


def test_clearance_and_z_holes_use_canonical_targets():
    data = contract().model_dump()
    data["parameters"].extend([
        {"id": "minimum_gap", "name": "Approved minimum gap", "kind": "number", "mode": "BOUNDED", "unit": "mm", "minimum": 0.5},
        {"id": "hole_x", "name": "Hole X", "kind": "number", "mode": "FIXED", "unit": "mm", "value": 0.0},
        {"id": "hole_radius", "name": "Approved bore radius", "kind": "number", "mode": "FIXED", "unit": "mm", "value": 12.0},
    ])
    data["verification_intent"].extend([
        {"id": "gap_check", "text": "Check an explicitly approved minimum gap.", "kind": "clearance",
         "component_refs": ["motor", "extrusion"], "parameter_refs": ["minimum_gap"]},
        {"id": "central_bore", "text": "Check an explicitly approved analytic Z bore.", "kind": "through_holes_z",
         "component_refs": ["mount"], "hole_refs": [{"x_parameter": "hole_x", "y_parameter": "hole_x", "radius_parameter": "hole_radius"}]},
    ])
    requirements = Requirements.model_validate(compile_requirements(DesignContract.model_validate(data))["requirements"])
    checks = {check.id: check for check in requirements.checks}
    assert checks["gap_check"].minimum == 0.5 and checks["gap_check"].maximum is None
    assert checks["central_bore"].holes[0].model_dump() == {"x": 0.0, "y": 0.0, "radius": 12.0}


def test_unapproved_assumptions_do_not_become_approved_handoff_claims():
    data = contract().model_dump()
    data["assumptions"] = [{"id": "tentative", "text": "Unreviewed claim", "accepted": False},
                           {"id": "approved", "text": "User approved prototype limitation", "accepted": True}]
    text = compile_handoff(DesignContract.model_validate(data))
    section = text.split("## APPROVED ASSUMPTIONS\n", 1)[1].split("## PROHIBITED INTERPRETATIONS", 1)[0]
    assert "User approved prototype limitation" in section
    assert "Unreviewed claim" not in section


def test_fixed_boolean_cannot_be_silently_adapted_as_an_unrestricted_boolean():
    data = contract().model_dump()
    data["parameters"].extend([
        {"id": "must_retain_motor", "name": "Retain supplied motor", "kind": "boolean", "mode": "FIXED",
         "unit": "boolean", "value": True, "impact": "CRITICAL", "source_refs": ["src_user_1"]},
        {"id": "cosmetic_ribs", "name": "Optional cosmetic ribs", "kind": "boolean", "mode": "FREE", "unit": "boolean"},
    ])
    output = compile_requirements(DesignContract.model_validate(data))
    requirements = Requirements.model_validate(output["requirements"])
    assert "must_retain_motor" not in requirements.parameters
    assert requirements.parameters["cosmetic_ribs"].kind == "boolean"
    issue = next(item for item in output["unsupported"] if item["id"] == "must_retain_motor")
    assert issue["code"] == "PLANNING_PARAMETER_UNSUPPORTED" and issue["critical"]
    assert "must_retain_motor = true" in compile_handoff(DesignContract.model_validate(data))
