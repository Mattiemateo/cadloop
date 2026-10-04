import pytest

from cadloop.planning.contracts import DesignContract
from cadloop.planning.questions import question_score, rank_questions


def contract(candidates):
    return DesignContract.model_validate({
        "task_id": "mount", "revision": "r1", "brief": "Make a mount",
        "sources": [{"id": "user", "kind": "USER", "description": "Supplied requirement"}],
        "parameters": [{"id": "width", "name": "Width", "kind": "number", "mode": "FIXED", "unit": "mm",
                        "value": 42, "source_refs": ["user"]}],
        "requirements": [{"id": "hard_requirement", "text": "Keep width", "hard": True, "source_refs": ["user"]}],
        "decision_candidates": candidates,
    })


def question(identifier="choice", **changes):
    data = {"id": identifier, "question": "Choose the width", "confidence": .5, "impact": "CRITICAL",
            "change_cost": "HIGH", "affects": ["width"], "options": [
                {"id": "A", "label": "Supplied", "description": "Use supplied width", "recommended": True,
                 "updates": [{"path": "/parameters/width/value", "value": 42}]},
                {"id": "B", "label": "Narrow", "description": "Reduce width",
                 "updates": [{"path": "/parameters/width/value", "value": 40}]}]}
    data.update(changes)
    return data


def test_exact_scoring_and_low_uncertainty_suppression():
    data = contract([question(), question("minor", confidence=.95, impact="LOW", change_cost="LOW")])
    assert question_score(data.decision_candidates[0]) == .5
    assert question_score(data.decision_candidates[1]) == pytest.approx(.005)
    assert [q["id"] for q in rank_questions(data)] == ["choice"]


def test_threshold_inclusive():
    data = contract([question(confidence=.64, impact="MEDIUM")])
    assert question_score(data.decision_candidates[0]) == .18
    assert len(rank_questions(data)) == 1


def test_hard_source_conflict_overrides_score():
    data = contract([question(confidence=1.0, impact="LOW", change_cost="LOW", source_conflict=True,
                             affects=["hard_requirement", "width"])])
    ranked = rank_questions(data)
    assert len(ranked) == 1 and ranked[0]["score"] == 0
    assert ranked[0]["blocking_reasons"] == ["SOURCE_CONFLICT_HARD_REQUIREMENT"]


def test_three_question_limit_and_id_ties_are_deterministic():
    data = contract([question(identifier) for identifier in ("z", "c", "a", "b")])
    assert [q["id"] for q in rank_questions(data)] == ["a", "b", "c"]
    assert [q["id"] for q in rank_questions(data, limit=None)] == ["a", "b", "c", "z"]


@pytest.mark.parametrize("mode", ["FREE", "OPTIMIZED"])
def test_design_freedom_does_not_create_questions(mode):
    data = contract([question(confidence=0.0)])
    raw = data.model_dump()
    raw["parameters"][0].update(mode=mode, value=None, impact="LOW")
    if mode == "OPTIMIZED":
        raw["parameters"][0]["objective"] = "minimize"
    assert rank_questions(raw) == []


def test_critical_interface_always_asks_even_with_confident_model():
    raw = contract([]).model_dump()
    raw["components"] = [{"id": "motor", "name": "Motor", "role": "purchased"},
                         {"id": "mount", "name": "Mount", "role": "fabricated"}]
    raw["interfaces"] = [{"id": "interface", "component_a": "motor", "component_b": "mount",
                          "kind": "mating", "impact": "CRITICAL", "resolved": False, "source_refs": ["user"]}]
    raw["decision_candidates"] = [question(confidence=1.0, affects=["interface", "width"])]
    assert rank_questions(raw)[0]["blocking_reasons"] == ["CRITICAL_INTERFACE_UNKNOWN"]


def test_missing_user_sourced_mating_dimension_always_asks():
    raw = contract([]).model_dump()
    raw["parameters"][0].update(value=None, impact="CRITICAL")
    raw["components"] = [{"id": "motor", "name": "Motor", "role": "purchased"},
                         {"id": "mount", "name": "Mount", "role": "fabricated"}]
    raw["interfaces"] = [{"id": "interface", "component_a": "motor", "component_b": "mount",
                          "kind": "mating", "impact": "CRITICAL", "resolved": True,
                          "parameter_refs": ["width"], "required_parameter_refs": ["width"], "source_refs": ["user"]}]
    raw["decision_candidates"] = [question(confidence=1.0)]
    assert rank_questions(raw)[0]["blocking_reasons"] == ["CRITICAL_MATING_DIMENSION_UNKNOWN"]


def test_missing_critical_clearance_forces_question_despite_confidence():
    raw = contract([]).model_dump()
    raw["parameters"][0]["value"] = None
    raw["components"] = [{"id": "motor", "name": "Motor", "role": "purchased"},
                         {"id": "mount", "name": "Mount", "role": "fabricated"}]
    raw["constraints"] = [{"id": "gap", "kind": "minimum_clearance", "impact": "CRITICAL",
                           "component_refs": ["motor", "mount"], "parameter_refs": ["width"],
                           "source_refs": ["user"]}]
    raw["decision_candidates"] = [question(confidence=1.0)]
    assert rank_questions(raw)[0]["blocking_reasons"] == ["CRITICAL_CLEARANCE_UNKNOWN"]


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), -1, True])
def test_invalid_threshold_is_rejected(threshold):
    with pytest.raises(ValueError):
        rank_questions(contract([]), threshold=threshold)


@pytest.mark.parametrize("limit", [0, 4, True])
def test_review_round_limit_is_enforced(limit):
    with pytest.raises(ValueError):
        rank_questions(contract([]), limit=limit)
