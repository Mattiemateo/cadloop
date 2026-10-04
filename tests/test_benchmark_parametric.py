"""Check fixed benchmark accounting without running CAD or a model."""
import pytest

from cadloop.contracts import Requirements
from scripts import benchmark_parametric as bench


def test_fixture_and_all_attempt_accounting():
    spec, req, programs = bench.fixtures()
    assert next(p["value"] for p in spec["parameters"] if p["name"] == "bore_diameter") == 22
    assert set(programs) == set(bench.CASES)
    assert len(set(programs.values())) == len(programs)
    assert [x["id"] for x in req["parametric_tests"]] == ["length_54", "bore_24", "thickness_10"]
    assert req["parametric_tests"][1]["overrides"][0]["holes"][0]["radius"] == 12
    Requirements.model_validate(req)
    with pytest.raises(ValueError, match="Empty benchmark suite"):
        bench.summarize([])

    rows = [
        {"case": "responsive", "expected_valid": True, "geometry_accepted": True,
         "task_accepted": True, "error": None, "nominal_worker_seconds": 2., "total_wall_seconds": 5.},
        {"case": "ignored_bore", "expected_valid": False, "geometry_accepted": True,
         "task_accepted": False, "error": None, "nominal_worker_seconds": 2., "total_wall_seconds": 5.},
        {"case": "responsive", "expected_valid": True, "geometry_accepted": None,
         "task_accepted": None, "error": {"type": "RuntimeError"},
         "nominal_worker_seconds": None, "total_wall_seconds": 1.},
    ]
    summary = bench.summarize(rows)
    assert summary["attempts"] == 3 and summary["infrastructure_errors"] == 1
    assert summary["scenario_infrastructure_attempts"] == 0
    assert summary["legacy_geometry_only"] == {
        "correct": 1, "denominator": 3, "false_accepts": 1, "false_rejects": 1}
    assert summary["required_response"] == {
        "correct": 2, "denominator": 3, "false_accepts": 0, "false_rejects": 1}
    assert summary["nominal_worker_seconds"]["measured"] == 2
    assert summary["total_wall_seconds"]["p95_nearest_rank"] == 5.
