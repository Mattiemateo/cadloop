from concurrent.futures import ThreadPoolExecutor

import pytest

from cadloop.checks import required_check_ids, result
from cadloop.contracts import Requirements
from cadloop.errors import CadLoopError
from cadloop.parametric import run_scenarios
from cadloop.planning.store import PlanningProject
from cadloop.util import digest, read_json, write_json
from cadloop.worker import make_report
from test_parametric import contract
from test_planning_integration import materialized


def test_provenance_read_cannot_mix_old_state_with_new_frozen_handoff(tmp_path, monkeypatch):
    plan, project, imported, _ = materialized(tmp_path)
    original_handoff = PlanningProject.handoff
    attempted = False
    transition = []

    def change_intent():
        try:
            current = plan.state()
            opened = plan.reopen(base=current["revision"], reason="User selects another orientation")
            selected = plan.answer(base=opened["revision"], answers=[("orientation_question", "inward")])
            plan.render()
            plan.freeze(base=selected["revision"])
            return "changed"
        except CadLoopError as exc:
            return exc.code

    def interleaved_handoff(workspace):
        nonlocal attempted
        if workspace.root == plan.root and not attempted:
            attempted = True
            with ThreadPoolExecutor(1) as pool:
                transition.append(pool.submit(change_intent).result(timeout=15))
        return original_handoff(workspace)

    monkeypatch.setattr(PlanningProject, "handoff", interleaved_handoff)
    try:
        binding = project.planning_provenance()
    except CadLoopError as exc:
        assert transition == ["changed"] and exc.code == "PLANNING_STALE"
    else:
        assert transition == ["PROJECT_BUSY"]
        assert binding["design_contract_revision"] == imported["design_contract_revision"]
        assert plan.state()["revision"] == imported["design_contract_revision"]


@pytest.mark.parametrize("planned", [False, True])
@pytest.mark.parametrize("fail_worker", [False, True])
def test_scenarios_preserve_plan_binding_and_legacy_inputs(tmp_path, monkeypatch, planned, fail_worker):
    requirements = Requirements.model_validate(contract())
    run = tmp_path / "run"
    write_json(run / "input/design/parameters.json", {"length": 50, "thickness": 8})
    binding = {}
    if planned:
        frozen = {"schema_version": 1, "task_id": "synthetic", "revision": "b" * 64,
                  "brief": "Use supplied dimensions", "status": "FROZEN"}
        binding = {"design_contract_hash": digest(frozen), "design_contract_revision": frozen["revision"]}
        write_json(run / "input/meta.json", {"schema_version": 1, "revision": "a" * 64, **binding})
        write_json(run / "input/design_contract.json", frozen)

    def worker(stage, target, **kwargs):
        if fail_worker:
            raise RuntimeError("Scenario worker unavailable")
        if stage == "verify":
            variant = Requirements.model_validate(read_json(target / "input/requirements.json"))
            revision = read_json(target / "input/meta.json")["revision"]
            report = make_report(revision, variant, [result(identifier, "pass", "OK", "Synthetic evidence")
                                                     for identifier in required_check_ids(variant)])
            write_json(target / "verification/report.json", report)
        return {"stage": stage, "exit_code": 0, "timed_out": False}

    monkeypatch.setattr("cadloop.parametric.run_stage", worker)
    outcomes = run_scenarios(run, requirements, "a" * 64, mode="trusted-native", timeout=45,
                            runtime={"mode": "trusted-native"})
    scenario = outcomes[0]
    directory = run / scenario["run_directory"]
    report = read_json(directory / "verification/report.json")
    meta = read_json(directory / "input/meta.json")
    assert scenario["geometry_accepted"] is (not fail_worker)
    for document in (scenario, report, meta):
        assert {key: document[key] for key in binding} == binding
        if not planned:
            assert "design_contract_hash" not in document and "design_contract_revision" not in document
    if planned:
        assert read_json(directory / "input/design_contract.json") == frozen
        assert digest(read_json(directory / "input/design_contract.json")) == meta["design_contract_hash"]
