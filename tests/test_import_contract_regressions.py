"""Regression coverage for normalized imports, integer persistence and schema drift."""
from copy import deepcopy
import math
from pathlib import Path

import pytest

from cadloop.contracts import Requirements
from cadloop.errors import CadLoopError
from cadloop.kerf import normalize_spec
from cadloop.project import Project
from cadloop.util import read_json, write_json


def contract(*, kind="number", unit="mm", minimum=1, maximum=8):
    return {
        "name": "Parameter regression", "description": "Reviewed synthetic box",
        "expected_parts": ["block"],
        "parameters": {"size": {"kind": kind, "unit": unit, "minimum": minimum,
                                  "maximum": maximum, "description": "Box size"}},
        "checks": [{"id": "width", "kind": "dimension", "part": "block", "axis": "x",
                    "minimum": 1, "maximum": 8, "description": "Width in approved range"}],
        "engineering_blockers": ["Synthetic regression fixture; not for fabrication"],
    }


def spec(*, value=4, unit="mm", minimum=1, maximum=8):
    return {
        "schema_version": "1.0.0",
        "part_spec": {"name": "Box", "description": "Synthetic fixture", "units": "mm"},
        "parameters": [{"name": "size", "value": value, "unit": unit,
                        "description": "Box size", "constraints": {"min": minimum, "max": maximum}}],
        "feature_sequence": [{"type": "extrude", "parameters": ["size"], "rationale": "Make a box"}],
    }


@pytest.mark.parametrize("unit,scale", [("cm", 10.), ("m", 1000.), ("in", 25.4), ("ft", 304.8)])
def test_converted_bounds_preserve_equivalent_approved_limits(unit, scale):
    pytest.importorskip("kerf_schemas")
    req = Requirements.model_validate(contract(minimum=.1))
    converted = spec(value=4 / scale, unit=unit, minimum=.1 / scale, maximum=8 / scale)
    assert normalize_spec(converted, req)["size"] == pytest.approx(4)


@pytest.mark.parametrize("endpoint", [1., 8.])
def test_converted_inclusive_endpoint_is_snapped_to_approved_bound(endpoint):
    pytest.importorskip("kerf_schemas")
    req = Requirements.model_validate(contract(minimum=endpoint, maximum=endpoint))
    converted = spec(value=endpoint / 25.4, unit="in", minimum=endpoint / 25.4, maximum=endpoint / 25.4)
    assert normalize_spec(converted, req)["size"] == endpoint


def test_radian_roundtrip_preserves_inclusive_degree_endpoint():
    pytest.importorskip("kerf_schemas")
    req = Requirements.model_validate(contract(unit="deg", minimum=60, maximum=60))
    radians = math.radians(60)
    assert normalize_spec(spec(value=radians, unit="rad", minimum=radians, maximum=radians), req)["size"] == 60


@pytest.mark.parametrize("fault", ["value", "minimum", "maximum"])
def test_conversion_does_not_allow_materially_conflicting_inputs(fault):
    pytest.importorskip("kerf_schemas")
    req = Requirements.model_validate(contract())
    data = spec(value=4 / 25.4, unit="in", minimum=1 / 25.4, maximum=8 / 25.4)
    parameter = data["parameters"][0]
    if fault == "value": parameter["value"] = (8 + 1e-8) / 25.4
    elif fault == "minimum": parameter["constraints"]["min"] = (1 + 1e-8) / 25.4
    else: parameter["constraints"]["max"] = (8 - 1e-8) / 25.4
    with pytest.raises((ValueError, CadLoopError)):
        normalize_spec(data, req)


def test_direct_mm_input_does_not_gain_a_roundoff_tolerance():
    pytest.importorskip("kerf_schemas")
    req = Requirements.model_validate(contract())
    data = spec(maximum=math.nextafter(8., 0.))
    with pytest.raises(CadLoopError, match="bounds"):
        normalize_spec(data, req)


def count_project(tmp_path, *, value=2, scenarios=False):
    data = contract(kind="integer", unit="count")
    if scenarios:
        data["checks"][0].update(minimum=1.99, maximum=2.01)
        data["parametric_tests"] = [{
            "id": "three", "description": "Three count units make 3 mm width",
            "parameters": {"size": 3.0},
            "overrides": [{**data["checks"][0], "minimum": 2.99, "maximum": 3.01}],
        }]
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.py").write_text(
        'from build123d import Box\n\ndef build(params):\n'
        '    width = sum(1 for _ in range(params["size"]))\n'
        '    return {"block": Box(width, 10, 10)}\n')
    write_json(source / "parameters.json", {"size": value})
    write_json(tmp_path / "requirements.json", data)
    return Project.create(tmp_path / "project", requirements=tmp_path / "requirements.json", design_dir=source)


def test_create_normalizes_integer_values_without_changing_input(tmp_path):
    project = count_project(tmp_path, value=2.0)
    assert type(read_json(project.design / "parameters.json")["size"]) is int
    assert type(read_json(tmp_path / "source/parameters.json")["size"]) is float


def test_proposal_persists_integral_float_as_integer(tmp_path):
    project = count_project(tmp_path)
    project.propose({"base_revision": project.revision(), "parameters": {"size": 3.0}, "reason": "Count normalization"})
    assert read_json(project.design / "parameters.json") == {"size": 3}
    assert type(project.parameters()["size"]) is int


def test_integer_only_correction_of_legacy_float_is_not_a_noop(tmp_path):
    project = count_project(tmp_path)
    write_json(project.design / "parameters.json", {"size": 3.0})
    before = project.revision()
    result = project.propose({"base_revision": before, "parameters": {"size": 3}, "reason": "Repair legacy float count"})
    assert result["revision"] != before
    assert type(project.parameters()["size"]) is int


@pytest.mark.parametrize("value", [3.5, True, "3", float("nan"), float("inf")])
def test_integer_normalization_does_not_accept_invalid_values(tmp_path, value):
    project = count_project(tmp_path)
    before = project.revision()
    with pytest.raises(ValueError):
        project.propose({"base_revision": before, "parameters": {"size": value}, "reason": "Must reject invalid count"})
    assert project.revision() == before


def test_scenario_contract_normalizes_integer_count_without_mutating_input():
    data = contract(kind="integer", unit="count")
    data["checks"][0].update(minimum=1.99, maximum=2.01)
    data["parametric_tests"] = [{
        "id": "three", "description": "Count grows to three", "parameters": {"size": 3.0},
        "overrides": [{**data["checks"][0], "minimum": 2.99, "maximum": 3.01}],
    }]
    original = deepcopy(data)
    req = Requirements.model_validate(data)
    assert type(req.parametric_tests[0].parameters["size"]) is int
    assert data == original and type(data["parametric_tests"][0]["parameters"]["size"]) is float


def test_equivalent_number_parameter_types_remain_a_noop(project):
    current = project.parameters()["gap_mm"]
    with pytest.raises(CadLoopError) as error:
        project.propose({"base_revision": project.revision(), "parameters": {"gap_mm": float(current)},
                         "reason": "Equivalent noninteger parameter value"})
    assert error.value.code == "NO_CHANGE"


def test_search_returns_canonical_integer_candidate(tmp_path, monkeypatch):
    from cadloop.search import search_parameter
    project = count_project(tmp_path)
    monkeypatch.setattr(project, "evaluate", lambda **kwargs: {
        "geometry_accepted": True, "task_accepted": True, "run_id": "candidate",
        "revision": project.revision(), "status": "GEOMETRY_ACCEPTED",
        "summary": {}, "blocker_ids": [],
    })
    searched = search_parameter(project, "size", [3.0], mode="trusted-native")
    assert searched["status"] == "FEASIBLE_CANDIDATE_FOUND"
    assert type(searched["value"]) is int
    assert type(searched["attempts"][0]["value"]) is int
    assert type(project.parameters()["size"]) is int


@pytest.mark.parametrize("timeout", [True, False, "45", None, float("nan"), float("inf")])
def test_evaluation_rejects_invalid_timeout_types_before_writing_a_run(project, timeout):
    with pytest.raises(CadLoopError) as error:
        project.evaluate(mode="trusted-native", timeout=timeout)
    assert error.value.code == "INVALID_TIMEOUT"
    assert not (project.control / "runs").exists()


@pytest.mark.integration
def test_integral_float_proposal_builds_using_integer_count(tmp_path):
    pytest.importorskip("build123d")
    project = count_project(tmp_path)
    assert project.evaluate(mode="trusted-native", render=False)["task_accepted"]
    project.propose({"base_revision": project.revision(), "parameters": {"size": 3.0}, "reason": "Count increases"})
    assert project.evaluate(mode="trusted-native", render=False)["task_accepted"]


@pytest.mark.integration
def test_integer_scenario_builds_with_normalized_count(tmp_path):
    pytest.importorskip("build123d")
    project = count_project(tmp_path, scenarios=True)
    result = project.evaluate(mode="trusted-native", render=False)
    assert result["task_accepted"] and result["parametric_accepted"]
    assert type(result["parametric_tests"][0]["parameters"]["size"]) is int


def test_published_requirements_schema_matches_runtime_contract():
    published = read_json(Path(__file__).parents[1] / "docs/requirements.schema.json")
    assert published == Requirements.model_json_schema()
    assert "parametric_tests" in published["properties"]
    assert "ParametricTest" in published["$defs"]
