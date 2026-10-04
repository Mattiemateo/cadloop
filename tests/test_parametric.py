"""Required response gates: immutable contracts, measured variants, nominal export.

Geometry tests run in the isolated test container; trusted-native below describes
its internal subprocesses, not host execution permission.
"""
from copy import deepcopy
from pathlib import Path

import pytest

from cadloop.checks import required_check_ids, result
from cadloop.contracts import Requirements
from cadloop.errors import CadLoopError
from cadloop.loop import ReplayProvider, repair_loop
from cadloop.parametric import apply_gate, run_scenarios
from cadloop.project import Project
from cadloop.search import search_parameter
from cadloop.util import read_json, tree_hashes, write_json
from cadloop.worker import make_report

SOURCE = '''import cadquery as cq

def build(p):
    thickness = p["thickness"]
    offset = 10
    plate = cq.Workplane("XY").box(p["length"], 30, thickness, centered=(True, True, False))
    return {"plate": plate.faces(">Z").workplane().pushPoints([(-offset, 0), (offset, 0)]).hole(4)}
'''


def contract():
    checks = [
        {"id": "length", "description": "Length 50 mm", "kind": "dimension", "part": "plate", "axis": "x", "minimum": 49.99, "maximum": 50.01},
        {"id": "thickness", "description": "Thickness 8 mm", "kind": "dimension", "part": "plate", "axis": "z", "minimum": 7.99, "maximum": 8.01},
        {"id": "holes", "description": "Two protected through holes", "kind": "through_holes_z", "part": "plate", "holes": [{"x": -10, "y": 0, "radius": 2}, {"x": 10, "y": 0, "radius": 2}], "tolerance": .001},
    ]
    return {"name": "response plate", "description": "Reviewed plate", "expected_parts": ["plate"],
            "parameters": {"length": {"kind": "number", "unit": "mm", "minimum": 45, "maximum": 60, "description": "length"},
                           "thickness": {"kind": "number", "unit": "mm", "minimum": 5, "maximum": 12, "description": "thickness"}},
            "checks": checks, "engineering_blockers": ["Strength and manufacturing unverified."],
            "parametric_tests": [{"id": "thicker", "description": "10 mm thickness preserves holes and length", "parameters": {"thickness": 10},
                                  "overrides": [{**checks[1], "minimum": 9.99, "maximum": 10.01}]}]}


def create_project(tmp_path, source=SOURCE, data=None):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "model.py").write_text(source)
    write_json(source_dir / "parameters.json", {"length": 50, "thickness": 8})
    req_path = tmp_path / "approved.json"
    write_json(req_path, data or contract())
    return Project.create(tmp_path / "project", requirements=req_path, design_dir=source_dir)


def test_scenario_derivation_preserves_all_other_checks_and_nominal_contract():
    req = Requirements.model_validate(contract())
    before = req.model_dump()
    variant = req.for_scenario(req.parametric_tests[0])
    assert req.model_dump() == before
    assert variant.parametric_tests == []
    assert required_check_ids(variant) == required_check_ids(req)
    assert [c.model_dump() for c in variant.checks if c.id != "thickness"] == [c.model_dump() for c in req.checks if c.id != "thickness"]
    assert variant.checks[1].minimum == 9.99 and req.checks[1].minimum == 7.99


@pytest.mark.parametrize("mutation", [
    "duplicate_scenario", "duplicate_override", "unknown_parameter", "unknown_check", "unknown_kind", "unknown_field", "path_id", "empty_parameters", "empty_overrides", "unchanged_target", "widened_target", "inverted_target", "changed_axis", "changed_part", "too_many_scenarios", "boolean_number", "string_number", "nan_number", "outside_bounds", "unsupported_override",
])
def test_invalid_scenario_contracts_are_rejected(mutation):
    data = contract()
    scenario = data["parametric_tests"][0]
    override = scenario["overrides"][0]
    if mutation == "duplicate_scenario": data["parametric_tests"].append(deepcopy(scenario))
    elif mutation == "duplicate_override": scenario["overrides"].append(deepcopy(override))
    elif mutation == "unknown_parameter": scenario["parameters"] = {"bogus": 10}
    elif mutation == "unknown_check": override["id"] = "bogus"
    elif mutation == "unknown_kind": override["kind"] = "pretend_pass"
    elif mutation == "unknown_field": scenario["optional"] = True
    elif mutation == "path_id": scenario["id"] = "../outside"
    elif mutation == "empty_parameters": scenario["parameters"] = {}
    elif mutation == "empty_overrides": scenario["overrides"] = []
    elif mutation == "unchanged_target": override.update(minimum=7.99, maximum=8.01)
    elif mutation == "widened_target": override.update(minimum=9, maximum=11)
    elif mutation == "inverted_target": override.update(minimum=11, maximum=10)
    elif mutation == "changed_axis": override["axis"] = "y"
    elif mutation == "changed_part": override["part"] = "other"
    elif mutation == "too_many_scenarios": data["parametric_tests"] = [{**deepcopy(scenario), "id": f"case{i}"} for i in range(13)]
    elif mutation == "boolean_number": scenario["parameters"]["thickness"] = True
    elif mutation == "string_number": scenario["parameters"]["thickness"] = "10"
    elif mutation == "nan_number": scenario["parameters"]["thickness"] = float("nan")
    elif mutation == "outside_bounds": scenario["parameters"]["thickness"] = 13
    elif mutation == "unsupported_override": scenario["overrides"] = [{"id": "thickness", "kind": "clearance", "a": "plate", "b": "other", "minimum": 0, "description": "unsupported"}]
    with pytest.raises(ValueError):
        Requirements.model_validate(data)


@pytest.mark.parametrize("mutation", ["empty", "looser", "same"])
def test_hole_override_cannot_remove_all_targets_or_weaken_tolerance(mutation):
    data = contract()
    holes = deepcopy(data["checks"][2])
    data["parametric_tests"][0]["overrides"] = [holes]
    if mutation == "empty": holes["holes"] = []
    elif mutation == "looser": holes["tolerance"] = .01; holes["holes"][0]["radius"] = 3
    with pytest.raises(ValueError): Requirements.model_validate(data)


def test_changed_bore_target_is_supported_without_mutating_mount_positions():
    data = contract()
    holes = deepcopy(data["checks"][2])
    holes["holes"][0]["radius"] = 3
    data["parametric_tests"][0]["overrides"] = [holes]
    req = Requirements.model_validate(data)
    variant = req.for_scenario(req.parametric_tests[0])
    assert variant.checks[2].holes[0].radius == 3
    assert req.checks[2].holes[0].radius == 2
    assert variant.checks[2].holes[1] == req.checks[2].holes[1]


@pytest.mark.parametrize("kind", ["missing", "duplicate", "unknown", "failed", "indeterminate"])
def test_required_scenario_outcome_coverage_fails_closed(kind):
    req = Requirements.model_validate(contract())
    nominal = make_report("a" * 64, req, [result(i, "pass", "OK", "coverage") for i in required_check_ids(req)])
    outcome = {"id": "thicker", "geometry_accepted": True, "summary": {"indeterminate": 0}, "blocker_ids": [], "run_directory": "parametric_tests/thicker"}
    outcomes = [outcome]
    if kind == "missing": outcomes = []
    elif kind == "duplicate": outcomes.append(deepcopy(outcome))
    elif kind == "unknown": outcomes[0]["id"] = "unknown"
    elif kind == "failed": outcome.update(geometry_accepted=False, blocker_ids=["thickness"])
    elif kind == "indeterminate": outcome.update(geometry_accepted=False, summary={"indeterminate": 1})
    report = apply_gate(nominal, req, outcomes)
    assert report["geometry_accepted"] is True
    assert report["parametric_accepted"] is False and report["task_accepted"] is False
    assert report["status"] == "PARAMETRIC_REPAIR_REQUIRED"


def test_legacy_nominal_contract_has_no_claim_of_parametric_acceptance():
    req = Requirements.model_validate({**contract(), "parametric_tests": []})
    nominal = make_report("a" * 64, req, [result(i, "pass", "OK", "coverage") for i in required_check_ids(req)])
    report = apply_gate(nominal, req, [])
    assert report["task_accepted"] is True and report["parametric_accepted"] is None


def test_responsive_geometry_and_coupled_change_preserve_invariants(tmp_path):
    data = contract()
    scenario = data["parametric_tests"][0]
    scenario["parameters"]["length"] = 54
    scenario["overrides"].append({**data["checks"][0], "minimum": 53.99, "maximum": 54.01})
    project = create_project(tmp_path, data=data)
    before = tree_hashes(project.design)
    requirements_bytes = (project.root / "requirements.json").read_bytes()
    feedback = project.evaluate(mode="trusted-native", render=False)
    assert feedback["geometry_accepted"] and feedback["parametric_accepted"] and feedback["task_accepted"]
    assert feedback["status"] == "PARAMETRIC_ACCEPTED"
    checks = {c["id"]: c for c in project.inspect(scenario="thicker")["report"]["checks"]}
    assert checks["thickness"]["evidence"]["measured_mm"] == pytest.approx(10)
    assert checks["length"]["evidence"]["measured_mm"] == pytest.approx(54)
    assert checks["holes"]["status"] == "pass"
    assert tree_hashes(project.design) == before
    assert (project.root / "requirements.json").read_bytes() == requirements_bytes
    assert read_json(project.control / "last_accepted.json")["run_id"] == feedback["run_id"]


@pytest.mark.parametrize("source,blocker", [
    (SOURCE.replace('thickness = p["thickness"]', "thickness = 8"), "thickness"),
    (SOURCE.replace("offset = 10", 'offset = 10 + p["thickness"] - 8'), "holes"),
    (SOURCE.replace('p["length"], 30, thickness', 'p["length"] * thickness / 8, 30, thickness'), "length"),
])
def test_valid_nominal_geometry_cannot_hide_failed_required_response(tmp_path, source, blocker):
    project = create_project(tmp_path, source)
    feedback = project.evaluate(mode="trusted-native", render=False)
    assert feedback["geometry_accepted"] is True
    assert feedback["task_accepted"] is False and feedback["parametric_accepted"] is False
    assert blocker in feedback["parametric_tests"][0]["blocker_ids"]
    assert not (project.control / "last_accepted.json").exists()
    cached = project.evaluate(mode="trusted-native", render=False)
    assert cached["cached"] and cached["run_id"] == feedback["run_id"]
    assert cached["geometry_accepted"] and not cached["task_accepted"]


def test_finish_exports_nominal_geometry_with_variant_evidence(tmp_path, monkeypatch):
    project = create_project(tmp_path)
    monkeypatch.setattr(project, "_render_preview", lambda *a, **kw: None)
    finished = project.finish(mode="trusted-native")
    assert finished["exported"] and finished["task_accepted"]
    export = Path(finished["export_directory"])
    nominal = read_json(export / "verification/metrics.json")["plate"]
    variant = read_json(export / finished["parametric_tests"][0]["run_directory"] / "verification/metrics.json")["plate"]
    assert nominal["bounds_mm"]["size"][2] == pytest.approx(8)
    assert variant["bounds_mm"]["size"][2] == pytest.approx(10)
    assert read_json(export / "input/design/parameters.json")["thickness"] == 8
    assert read_json(export / "export_manifest.json")["task_accepted"] is True


def test_finish_rebuilds_and_refuses_failed_response(tmp_path, monkeypatch):
    project = create_project(tmp_path, SOURCE.replace('thickness = p["thickness"]', "thickness = 8"))
    monkeypatch.setattr(project, "_render_preview", lambda *a, **kw: None)
    first = project.evaluate(mode="trusted-native", render=False)
    finished = project.finish(mode="trusted-native")
    assert finished["run_id"] != first["run_id"]
    assert finished["geometry_accepted"] and not finished["exported"]
    assert not (project.root / "exports").exists()


@pytest.mark.parametrize("kind", ["raise", "timeout", "no_change"])
def test_scenario_failure_preserves_project_and_blocks_completion(tmp_path, monkeypatch, kind):
    data = contract()
    if kind == "no_change": data["parametric_tests"][0]["parameters"]["thickness"] = 8
    project = create_project(tmp_path, data=data)
    before = tree_hashes(project.design)
    revision = project.revision()
    def failed_stage(*args, **kwargs):
        if kind == "raise": raise RuntimeError("scenario worker unavailable")
        return {"exit_code": -9, "timed_out": True, "stage": "build"}
    monkeypatch.setattr("cadloop.parametric.run_stage", failed_stage)
    feedback = project.evaluate(mode="trusted-native", render=False)
    assert feedback["geometry_accepted"] and not feedback["task_accepted"]
    assert tree_hashes(project.design) == before and project.revision() == revision
    checks = project.inspect(scenario="thicker")["report"]["checks"]
    expected = "PARAMETRIC_NO_CHANGE" if kind == "no_change" else "PARAMETRIC_EXECUTION_FAILED"
    assert any(c["code"] == expected for c in checks)
    assert not (project.control / "last_accepted.json").exists()


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "unknown", "unknown_status", "stale"])
def test_scenario_verifier_evidence_cannot_omit_or_forge_checks(tmp_path, monkeypatch, corruption):
    req = Requirements.model_validate(contract())
    run = tmp_path / "run"
    write_json(run / "input/design/parameters.json", {"length": 50, "thickness": 8})
    def worker(stage, target, **kwargs):
        if stage == "verify":
            variant = Requirements.model_validate(read_json(target / "input/requirements.json"))
            revision = read_json(target / "input/meta.json")["revision"]
            report = make_report(revision, variant, [result(i, "pass", "OK", "fixture") for i in required_check_ids(variant)])
            if corruption == "missing": report["checks"].pop()
            elif corruption == "duplicate": report["checks"].append(deepcopy(report["checks"][0]))
            elif corruption == "unknown": report["checks"].append(result("bogus", "pass", "OK", "unknown"))
            elif corruption == "unknown_status": report["checks"][0]["status"] = "unknown"
            elif corruption == "stale": report["revision"] = "0" * 64
            write_json(target / "verification/report.json", report)
        return {"exit_code": 0, "timed_out": False, "stage": stage}
    monkeypatch.setattr("cadloop.parametric.run_stage", worker)
    outcomes = run_scenarios(run, req, "a" * 64, mode="trusted-native", timeout=45, runtime={"mode": "trusted-native"})
    assert outcomes[0]["geometry_accepted"] is False
    assert outcomes[0]["summary"]["indeterminate"] > 0


def test_scenario_receipt_tampering_is_rejected_before_cache_or_inspect(tmp_path):
    project = create_project(tmp_path)
    result = project.evaluate(mode="trusted-native", render=False)
    path = Path(result["run_directory"]) / result["parametric_tests"][0]["run_directory"] / "verification/report.json"
    data = read_json(path)
    data["geometry_accepted"] = False
    write_json(path, data)
    with pytest.raises(CadLoopError, match="changed"):
        project.evaluate(mode="trusted-native", render=False)
    with pytest.raises(CadLoopError): project.inspect(scenario="thicker")


def test_source_change_invalidates_scenario_inspection(tmp_path):
    project = create_project(tmp_path)
    project.evaluate(mode="trusted-native", render=False)
    project.propose({"base_revision": project.revision(), "reason": "Legal change invalidates evidence", "parameters": {"length": 51}})
    with pytest.raises(CadLoopError) as exc: project.inspect(scenario="thicker")
    assert exc.value.code == "STALE_REVISION"


def test_search_does_not_select_nominal_only_success(tmp_path, monkeypatch):
    project = create_project(tmp_path)
    attempts = []
    def evaluate(**kwargs):
        attempts.append(project.parameters()["length"])
        return {"geometry_accepted": True, "task_accepted": False, "run_id": str(len(attempts)), "revision": project.revision(), "status": "PARAMETRIC_REPAIR_REQUIRED", "summary": {}, "blocker_ids": ["AUTO_parametric_thicker"]}
    monkeypatch.setattr(project, "evaluate", evaluate)
    searched = search_parameter(project, "length", [51, 52], mode="trusted-native")
    assert searched["status"] == "NO_FEASIBLE_CANDIDATE" and searched["value"] is None
    assert attempts == [51, 52, 50]
    assert project.parameters()["length"] == 50


def test_loop_does_not_finish_on_nominal_only_success(tmp_path, monkeypatch):
    project = create_project(tmp_path)
    feedback = {"geometry_accepted": True, "task_accepted": False, "parametric_accepted": False, "status": "PARAMETRIC_REPAIR_REQUIRED", "progress_key": [0, 1, 0], "blocker_ids": ["AUTO_parametric_thicker"]}
    monkeypatch.setattr(project, "evaluate", lambda **kw: feedback)
    monkeypatch.setattr(project, "finish", lambda **kw: pytest.fail("Nominal-only pass cannot finish"))
    provider = ReplayProvider([{"kind": "stop", "reason": "Source repair required"}])
    state = repair_loop(project, provider, mode="trusted-native")
    assert provider.calls == 1 and state["status"] == "WORKER_STOPPED"


def test_later_scenario_failure_cannot_be_hidden_by_earlier_pass(tmp_path, monkeypatch):
    data = contract()
    data["parametric_tests"].append({"id": "longer", "description": "54 mm length", "parameters": {"length": 54},
        "overrides": [{**data["checks"][0], "minimum": 53.99, "maximum": 54.01}]})
    req = Requirements.model_validate(data)
    run = tmp_path / "run"
    write_json(run / "input/design/parameters.json", {"length": 50, "thickness": 8})
    image = "sha256:" + "b" * 64
    calls = []
    def worker(stage, target, **kwargs):
        scenario_id = read_json(target / "input/meta.json")["scenario"]["id"]
        calls.append((scenario_id, stage, kwargs["image"]))
        if scenario_id == "longer": raise RuntimeError("later required scenario failed")
        if stage == "verify":
            variant = Requirements.model_validate(read_json(target / "input/requirements.json"))
            report = make_report(read_json(target / "input/meta.json")["revision"], variant,
                                 [result(i, "pass", "OK", "fixture") for i in required_check_ids(variant)])
            write_json(target / "verification/report.json", report)
        return {"exit_code": 0, "timed_out": False, "stage": stage}
    monkeypatch.setattr("cadloop.parametric.run_stage", worker)
    outcomes = run_scenarios(run, req, "a" * 64, mode="docker", timeout=45, runtime={"mode": "docker", "image_id": image})
    assert [item["geometry_accepted"] for item in outcomes] == [True, False]
    assert all(call[2] == image for call in calls)
    nominal = make_report("a" * 64, req, [result(i, "pass", "OK", "fixture") for i in required_check_ids(req)])
    assert apply_gate(nominal, req, outcomes)["task_accepted"] is False


def test_scenario_input_mutation_is_detected_before_verification(tmp_path, monkeypatch):
    req = Requirements.model_validate(contract())
    run = tmp_path / "run"
    write_json(run / "input/design/parameters.json", {"length": 50, "thickness": 8})
    calls = []
    def worker(stage, target, **kwargs):
        calls.append(stage)
        write_json(target / "input/design/parameters.json", {"length": 50, "thickness": 8})
        return {"exit_code": 0, "timed_out": False, "stage": stage}
    monkeypatch.setattr("cadloop.parametric.run_stage", worker)
    outcomes = run_scenarios(run, req, "a" * 64, mode="trusted-native", timeout=45, runtime={"mode": "trusted-native"})
    assert calls == ["build"] and not outcomes[0]["geometry_accepted"]
    report = read_json(run / outcomes[0]["run_directory"] / "verification/report.json")
    assert any(c["code"] == "INPUT_MUTATED" for c in report["checks"])


def test_interruption_during_variant_does_not_modify_original_design(tmp_path, monkeypatch):
    project = create_project(tmp_path)
    before = tree_hashes(project.design)
    def interrupted(*args, **kwargs): raise KeyboardInterrupt()
    monkeypatch.setattr("cadloop.parametric.run_stage", interrupted)
    with pytest.raises(KeyboardInterrupt): project.evaluate(mode="trusted-native", render=False)
    assert tree_hashes(project.design) == before
    assert project.parameters() == {"length": 50, "thickness": 8}
    assert not (project.control / "latest.json").exists()


def test_nominal_evidence_mutation_by_variant_cannot_be_sealed_as_pass(tmp_path, monkeypatch):
    project = create_project(tmp_path)
    def tamper(run, *args, **kwargs):
        with (run / "geometry/assembly.step").open("ab") as file:
            file.write(b"invalid added data")
        return []
    monkeypatch.setattr("cadloop.project.run_scenarios", tamper)
    result = project.evaluate(mode="trusted-native", render=False)
    assert not result["task_accepted"] and not result["geometry_accepted"]
    assert any(c["code"] == "INPUT_MUTATED" for c in project.inspect()["report"]["checks"])


def test_scenario_worker_directories_do_not_collide_across_runs(tmp_path, monkeypatch):
    data = contract()
    data["parametric_tests"][0]["id"] = "scenario_" + "a" * 55
    req = Requirements.model_validate(data)
    monkeypatch.setattr("cadloop.parametric.run_stage", lambda *a, **kw: {"stage": "build", "exit_code": 1, "timed_out": False})
    directories = []
    for name in ("run_one", "run_two"):
        run = tmp_path / name
        write_json(run / "input/design/parameters.json", {"length": 50, "thickness": 8})
        outcome = run_scenarios(run, req, "a" * 64, mode="trusted-native", timeout=45, runtime={"mode": "trusted-native"})[0]
        assert outcome["id"] == data["parametric_tests"][0]["id"]
        directories.append(Path(outcome["run_directory"]).name)
    assert directories[0] != directories[1]
    assert all(len(directory) <= 50 for directory in directories)
