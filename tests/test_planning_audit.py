import copy

from cadloop.planning.audit import audit
from cadloop.planning.contracts import DesignContract


def contract_data():
    return {
        "task_id": "motor_mount", "revision": "r1", "brief": "Mount the supplied motor.",
        "intent": "A removable printed motor mount.",
        "sources": [{"id": "user", "kind": "USER", "description": "Supplied dimensions"}],
        "components": [{"id": "motor", "name": "Motor", "role": "purchased", "source_refs": ["user"]},
                       {"id": "mount", "name": "Mount", "role": "fabricated", "source_refs": ["user"]}],
        "parameters": [{"id": "motor_width", "name": "Motor width", "kind": "number", "mode": "FIXED",
                        "value": 42, "unit": "mm", "impact": "CRITICAL", "source_refs": ["user"]},
                       {"id": "fillet", "name": "Fillet", "kind": "number", "mode": "FREE",
                        "unit": "mm", "impact": "LOW"}],
        "interfaces": [{"id": "motor_mount_interface", "component_a": "motor", "component_b": "mount",
                        "kind": "mating", "impact": "CRITICAL", "parameter_refs": ["motor_width"],
                        "required_parameter_refs": ["motor_width"], "source_refs": ["user"], "resolved": True}],
        "requirements": [{"id": "removable", "text": "Mount must be removable.", "hard": True,
                          "impact": "CRITICAL", "source_refs": ["user"]}],
        "diagram_spec": {"views": {view: [{"id": f"{view}_motor", "type": "label", "component_ref": "motor"}]
                                   for view in ("front", "side", "top")}},
    }


def codes(result):
    return {issue["code"] for issue in result["blocking"]}


def test_supplied_critical_dimension_and_free_cosmetic_pass():
    result = audit(contract_data())
    assert result["status"] == "REVIEWABLE" and result["blocking"] == []
    assert {issue["code"] for issue in result["warnings"]} == {
        "VERIFICATION_INTENT_MISSING", "MANUFACTURING_PROCESS_UNSPECIFIED"}


def test_unresolved_critical_interface_blocks():
    data = contract_data()
    data["interfaces"][0]["resolved"] = False
    result = audit(data)
    assert result["status"] == "NEEDS_INPUT"
    assert "CRITICAL_INTERFACE_UNKNOWN" in codes(result)


def test_unapproved_inferred_dimension_and_hard_requirement_block():
    data = contract_data()
    data["sources"][0]["kind"] = "MODEL_INFERRED"
    result = audit(data)
    inferred = [issue["id"] for issue in result["blocking"] if issue["code"] == "CRITICAL_INFERENCE_UNAPPROVED"]
    assert set(inferred) == {"motor_width", "removable", "motor_mount_interface"}
    assert result["status"] == "NEEDS_INPUT"


def test_missing_hard_requirement_provenance_blocks():
    data = contract_data()
    data["requirements"][0]["source_refs"] = []
    assert "HARD_REQUIREMENT_PROVENANCE_MISSING" in codes(audit(data))


def test_broken_diagram_reference_is_structured_schema_blocker():
    data = contract_data()
    data["diagram_spec"]["views"]["front"][0]["component_ref"] = "unknown"
    assert "PLANNING_SCHEMA_INVALID" in codes(audit(data))


def test_engineering_literal_cannot_replace_canonical_label():
    data = contract_data()
    data["diagram_spec"]["views"]["front"][0] = {"id": "front_width", "type": "label", "text": "42 mm"}
    assert "DIAGRAM_LITERAL_ENGINEERING_VALUE" in codes(audit(data))


def test_draft_requires_intent_components_and_all_nonempty_views():
    data = contract_data()
    data.update(intent="", components=[], interfaces=[])
    data["diagram_spec"] = {"views": {view: [] for view in ("front", "side", "top")}}
    result = audit(data)
    assert result["status"] == "REVIEW_REQUIRED"
    assert codes(result) == {"DESIGN_INTENT_MISSING", "COMPONENTS_MISSING", "DIAGRAM_VIEWS_MISSING"}


def test_free_parameter_is_not_known_critical_mating_dimension():
    data = contract_data()
    data["interfaces"][0]["parameter_refs"] = ["fillet"]
    data["interfaces"][0]["required_parameter_refs"] = ["fillet"]
    assert "CRITICAL_MATING_DIMENSION_UNKNOWN" in codes(audit(data))


def test_derived_dimension_inherits_supplied_provenance():
    data = contract_data()
    data["parameters"].append({"id": "shaft_center", "name": "Derived shaft center", "kind": "number",
                               "mode": "DERIVED", "unit": "mm", "derived_from": ["motor_width"],
                               "impact": "CRITICAL"})
    assert audit(data)["status"] == "REVIEWABLE"


def test_audit_checks_questions_beyond_first_round():
    data = contract_data()
    data["decision_candidates"] = [
        {"id": f"question_{i}", "question": "Which mount width?", "confidence": 0.5,
         "impact": "HIGH", "change_cost": "HIGH", "affects": ["motor_width"],
         "options": [{"id": "wide", "label": "Wide", "description": "Use supplied width", "recommended": True,
                      "updates": [{"path": "/parameters/motor_width/value", "value": 42}]},
                     {"id": "narrow", "label": "Narrow", "description": "Review a narrower width",
                      "updates": [{"path": "/parameters/motor_width/value", "value": 40}]}]}
        for i in range(4)]
    result = audit(data)
    assert len([issue for issue in result["blocking"] if issue["code"] == "UNANSWERED_DECISION"]) == 4


def test_accepted_option_history_and_canonical_value_must_match():
    data = contract_data()
    option = {"id": "yes", "label": "Keep", "description": "Keep supplied width", "recommended": True,
              "updates": [{"op": "set", "path": "/parameters/motor_width/value", "value": 42}]}
    data["decision_candidates"] = [{"id": "width_question", "question": "Keep width?", "confidence": .5,
        "impact": "CRITICAL", "change_cost": "HIGH", "affects": ["motor_width"], "options": [option,
        {"id": "no", "label": "Change", "description": "Use a narrower mount", "recommended": False,
         "updates": [{"path": "/parameters/motor_width/value", "value": 40}]}]}]
    before = DesignContract.model_validate(copy.deepcopy(data))
    data["accepted_decisions"] = [{"id": "accepted_width", "question_id": "width_question", "option_id": "yes",
        "updates": option["updates"], "previous_revision": "r1", "timestamp": "2026-10-04T00:00:00Z"}]
    assert audit(data, {"r1": before})["status"] == "REVIEWABLE"
    data["parameters"][0]["value"] = 43
    assert "ACCEPTED_DECISION_CHANGED" in codes(audit(data, {"r1": before}))
    data["accepted_decisions"][0]["option_id"] = "missing"
    assert "ACCEPTED_DECISION_HISTORY_INVALID" in codes(audit(data, {"r1": before}))


def test_critical_unimplemented_geometric_check_is_explicit():
    data = contract_data()
    data["verification_intent"] = [{"id": "removability_verification", "text": "Verify assembly removability",
                                    "requirement_refs": ["removable"], "geometry_required": True, "kind": "manual"}]
    result = audit(data)
    assert result["status"] == "REVIEWABLE"
    assert result["warnings"][0]["code"] == "CRITICAL_VERIFICATION_UNSUPPORTED"


def test_external_reference_requires_explicit_user_approval():
    data = contract_data()
    data["sources"].append({"id": "external", "kind": "EXTERNAL_REFERENCE", "description": "Unreviewed motor drawing",
                            "reference": "https://example.com/motor"})
    data["parameters"][0]["source_refs"] = ["external"]
    assert "CRITICAL_INFERENCE_UNAPPROVED" in codes(audit(data))
    option = {"id": "approve", "label": "Use drawing", "description": "Approve this drawing as the source",
              "recommended": True, "approved_source_refs": ["external"],
              "updates": [{"op": "set", "path": "/parameters/motor_width/value", "value": 42}]}
    data["decision_candidates"] = [{"id": "source_question", "question": "Use this motor drawing?", "confidence": .5,
        "impact": "CRITICAL", "change_cost": "HIGH", "affects": ["motor_width"], "options": [option,
        {"id": "other", "label": "Use other motor", "description": "Use a different supplied width", "recommended": False,
         "updates": [{"path": "/parameters/motor_width/value", "value": 40}]}]}]
    before = DesignContract.model_validate(copy.deepcopy(data))
    data["accepted_decisions"] = [{"id": "accepted_source", "question_id": "source_question", "option_id": "approve",
        "source_refs": ["external"], "updates": option["updates"], "previous_revision": "r1",
        "timestamp": "2026-10-04T00:00:00Z"}]
    assert audit(data, {"r1": before})["status"] == "REVIEWABLE"


def test_critical_clearance_needs_a_limit_not_free_cosmetic_variable():
    data = contract_data()
    data["constraints"] = [{"id": "minimum_gap", "kind": "minimum_clearance", "impact": "CRITICAL",
                             "component_refs": ["motor", "mount"], "source_refs": ["user"],
                             "parameter_refs": ["fillet"]}]
    assert "CRITICAL_CLEARANCE_UNKNOWN" in codes(audit(data))
    data["parameters"][1].update(mode="BOUNDED", minimum=3.0, source_refs=["user"])
    assert "CRITICAL_CLEARANCE_UNKNOWN" not in codes(audit(data))


def test_critical_constraint_requires_approved_relationship_provenance():
    data = contract_data()
    data["sources"].append({"id": "guess", "kind": "MODEL_INFERRED", "description": "Proposed relationship"})
    data["constraints"] = [{"id": "axes", "kind": "concentric", "impact": "CRITICAL",
                             "component_refs": ["motor", "mount"], "source_refs": ["guess"]}]
    assert "CRITICAL_INFERENCE_UNAPPROVED" in codes(audit(data))


def bounds_decision_data(*, mode="BOUNDED", approve_all=True):
    data = contract_data()
    data["sources"].append({"id": "guess", "kind": "MODEL_INFERRED", "description": "Unapproved width hypothesis"})
    data["parameters"][0].update(mode=mode, source_refs=["guess"], minimum=40.0, maximum=44.0,
                                  value=42 if mode == "FIXED" else None)
    selected = [{"op": "set", "path": "/parameters/motor_width/minimum", "value": 40.0}]
    if approve_all:
        selected.append({"op": "set", "path": "/parameters/motor_width/maximum", "value": 44.0})
    data["decision_candidates"] = [{"id": "bounds_question", "question": "Use this width range?", "confidence": 1.0,
        "impact": "CRITICAL", "change_cost": "HIGH", "affects": ["motor_width"], "options": [
        {"id": "accept", "label": "Keep range", "description": "Explicitly accept these bounds", "recommended": True,
         "updates": selected},
        {"id": "change", "label": "Use other range", "description": "Explicitly accept another range", "recommended": False,
         "updates": [{"path": "/parameters/motor_width/minimum", "value": 39.0},
                     {"path": "/parameters/motor_width/maximum", "value": 43.0}]}]}]
    before = DesignContract.model_validate(copy.deepcopy(data))
    data["accepted_decisions"] = [{"id": "accepted_bounds", "question_id": "bounds_question", "option_id": "accept",
        "updates": selected, "previous_revision": "r1", "timestamp": "2026-10-04T00:00:00Z"}]
    return data, {"r1": before}


def test_user_can_approve_all_canonical_bounds_without_approving_inferred_source():
    data, history = bounds_decision_data()
    result = audit(data, history)
    assert result["status"] == "REVIEWABLE"
    assert not any(issue["id"] == "motor_width" for issue in result["warnings"])


def test_approving_one_bound_does_not_approve_the_other_bound():
    data, history = bounds_decision_data(approve_all=False)
    assert "CRITICAL_INFERENCE_UNAPPROVED" in codes(audit(data, history))


def test_approving_fixed_parameter_bounds_does_not_approve_its_actual_value():
    data, history = bounds_decision_data(mode="FIXED")
    assert "CRITICAL_INFERENCE_UNAPPROVED" in codes(audit(data, history))
