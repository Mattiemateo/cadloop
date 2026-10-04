import copy

import pytest
from pydantic import ValidationError

from cadloop.planning.contracts import DesignContract, PlanningProposal, SetUpdate, apply_updates


def contract_data():
    return {
        "task_id": "motor_mount", "revision": "r0", "brief": "Make a removable motor mount.",
        "sources": [{"id": "user_brief", "kind": "USER", "description": "Supplied motor geometry"}],
        "components": [{"id": "motor", "name": "Motor", "role": "mounted hardware", "source_refs": ["user_brief"]},
                       {"id": "mount", "name": "Mount", "role": "fabricated mount"}],
        "parameters": [
            {"id": "motor_width", "name": "Motor width", "kind": "number", "mode": "FIXED", "unit": "mm", "value": 42,
             "impact": "CRITICAL", "source_refs": ["user_brief"]},
            {"id": "motor_orientation", "name": "Motor orientation", "kind": "enum", "mode": "FIXED", "unit": "text",
             "enum_values": ["shaft_outward", "shaft_inward"], "impact": "CRITICAL"}],
        "decision_candidates": [{"id": "orientation", "question": "Which motor orientation?", "confidence": 0.5,
            "impact": "CRITICAL", "change_cost": "HIGH", "affects": ["motor_orientation"], "options": [
                {"id": "A", "label": "Shaft outward", "description": "The shaft faces outward.", "recommended": True,
                 "updates": [{"path": "/parameters/motor_orientation/value", "value": "shaft_outward"}]},
                {"id": "B", "label": "Shaft inward", "description": "The shaft faces inward.",
                 "updates": [{"path": "/parameters/motor_orientation/value", "value": "shaft_inward"}]}]}],
    }


def test_planning_contract_strict_packet_and_update():
    contract = DesignContract.model_validate(contract_data())
    proposal = PlanningProposal(base_revision="r0", reason="Interpret brief", contract=contract)
    changed = apply_updates(contract, proposal.contract.decision_candidates[0].options[0].updates)
    assert changed.parameters[1].value == "shaft_outward"
    assert contract.parameters[1].value is None
    assert contract == DesignContract.model_validate(contract.model_dump())


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(unexpected=True),
    lambda d: d["parameters"][0].update(unexpected=True),
    lambda d: d["parameters"].append(copy.deepcopy(d["parameters"][0])),
    lambda d: d["parameters"][0].update(id="motor"),
    lambda d: d["parameters"][0].update(value=float("nan")),
    lambda d: d["parameters"][0].update(value=float("inf")),
    lambda d: d["parameters"][0].update(value=True),
    lambda d: d["parameters"][0].update(value="42"),
    lambda d: d["parameters"][0].update(unit="inch"),
    lambda d: d["parameters"][0].update(mode="MISSING"),
    lambda d: d["parameters"][0].update(source_refs=["unknown"]),
    lambda d: d["parameters"][0].update(minimum=50, maximum=40),
    lambda d: d["decision_candidates"][0].update(confidence=float("nan")),
    lambda d: d["decision_candidates"][0].update(confidence=1.1),
    lambda d: d["decision_candidates"][0].update(confidence="0.5"),
    lambda d: d["decision_candidates"][0].update(affects=["unknown"]),
    lambda d: d["decision_candidates"][0]["options"][1].update(recommended=True),
    lambda d: d["decision_candidates"][0]["options"][0]["updates"][0].update(path="/status"),
    lambda d: d["decision_candidates"][0]["options"][0]["updates"][0].update(path="/parameters/0/value"),
    lambda d: d["decision_candidates"][0]["options"][0]["updates"][0].update(path="/parameters/motor_orientation/source_refs"),
    lambda d: d["decision_candidates"][0]["options"][0]["updates"][0].update(value="invented_orientation"),
])
def test_bad_planning_contracts_rejected(mutation):
    data = contract_data()
    mutation(data)
    with pytest.raises(ValidationError):
        DesignContract.model_validate(data)


def test_planning_proposal_base_and_duplicate_packet_must_agree():
    contract = DesignContract.model_validate(contract_data())
    with pytest.raises(ValidationError):
        PlanningProposal(base_revision="stale", reason="test", contract=contract)
    with pytest.raises(ValidationError):
        PlanningProposal(base_revision="r0", reason="test", contract=contract, decision_candidates=[])


def test_transactional_updates_revalidate_types_and_reject_conflicts():
    contract = DesignContract.model_validate(contract_data())
    with pytest.raises(ValueError):
        apply_updates(contract, [SetUpdate(path="/parameters/motor_width/value", value=True)])
    update = SetUpdate(path="/parameters/motor_width/value", value=40)
    with pytest.raises(ValueError):
        apply_updates(contract, [update, update])
    assert contract.parameters[0].value == 42


def test_diagram_references_are_canonical_and_layout_is_separate():
    data = contract_data()
    data["diagram_spec"] = {"views": {"front": [{"id": "width_dimension", "type": "dimension", "x": 10,
        "y": 20, "x2": 100, "y2": 20, "parameter_ref": "motor_width"}]}}
    DesignContract.model_validate(data)
    data["diagram_spec"]["views"]["front"][0]["parameter_ref"] = "missing"
    with pytest.raises(ValidationError):
        DesignContract.model_validate(data)


@pytest.mark.parametrize("parameter", [
    {"mode": "BOUNDED", "minimum": 3},
    {"mode": "FREE"},
    {"mode": "OPTIMIZED", "objective": "minimize"},
])
def test_design_freedom_is_valid_without_value(parameter):
    data = contract_data()
    data["parameters"][0].update(value=None, **parameter)
    DesignContract.model_validate(data)


def test_derived_parameter_and_coordinate_frame_cycles_rejected():
    data = contract_data()
    data["parameters"][0].update(mode="DERIVED", derived_from=["motor_orientation"])
    data["parameters"][1].update(mode="DERIVED", derived_from=["motor_width"])
    with pytest.raises(ValidationError, match="Cyclic parameter"):
        DesignContract.model_validate(data)
    data = contract_data()
    data["coordinate_frames"] = [{"id": "frame_a", "description": "A", "parent_ref": "frame_b"},
                                 {"id": "frame_b", "description": "B", "parent_ref": "frame_a"}]
    with pytest.raises(ValidationError, match="Cyclic coordinate"):
        DesignContract.model_validate(data)


def test_option_updates_form_one_typed_transaction():
    data = contract_data()
    data["parameters"][0].update(minimum=40, maximum=50)
    data["decision_candidates"][0]["affects"] = ["motor_width", "motor_orientation"]
    data["decision_candidates"][0]["options"][0]["updates"] = [
        {"path": "/parameters/motor_width/value", "value": 60},
        {"path": "/parameters/motor_width/maximum", "value": 70},
    ]
    contract = DesignContract.model_validate(data)
    result = apply_updates(contract, contract.decision_candidates[0].options[0].updates)
    assert result.parameters[0].value == 60
    assert result.parameters[0].maximum == 70


def test_source_approval_references_resolve_and_updates_are_safe_alone():
    data = contract_data()
    data["decision_candidates"][0]["options"][0]["approved_source_refs"] = ["unknown"]
    with pytest.raises(ValidationError):
        DesignContract.model_validate(data)
    with pytest.raises(ValidationError):
        SetUpdate(path="/parameters/0/value", value=42)
    with pytest.raises(ValidationError):
        SetUpdate(path="/accepted_decisions/trusted/value", value=True)
