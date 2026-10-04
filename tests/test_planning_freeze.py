import copy
from pathlib import Path
import subprocess
import sys

import pytest

from cadloop.errors import CadLoopError
from cadloop.planning.contracts import DesignContract
from cadloop.planning.store import PlanningProject
from cadloop.util import file_hash, read_json, tree_hashes
from planning_helpers import frozen, proposal, reviewable


def workspace(tmp_path):
    return PlanningProject.initialize(tmp_path / "plan", brief="Make a removable motor mount")


def test_freeze_with_critical_blocker_never_writes_acceptance(tmp_path):
    plan = workspace(tmp_path)
    state = plan.propose(proposal(plan))
    before = tree_hashes(plan.folder)
    result = plan.freeze(base=state["revision"])
    assert result["status"] == "NEEDS_INPUT" and result["frozen"] is False
    assert tree_hashes(plan.folder) == before


def test_freeze_requires_current_revision_and_current_render(tmp_path):
    plan = workspace(tmp_path)
    initial = plan.state()["revision"]
    state = reviewable(plan)
    with pytest.raises(CadLoopError) as exc:
        plan.freeze(base=initial)
    assert exc.value.code == "STALE_REVISION"
    with pytest.raises(CadLoopError) as exc:
        plan.freeze(base=state["revision"])
    assert exc.value.code == "PLANNING_RENDER_REQUIRED"


def test_render_is_repeatable_and_new_proposal_invalidates_old_render(tmp_path):
    plan = workspace(tmp_path)
    state = reviewable(plan)
    rendered = plan.render(base=state["revision"])
    directory = Path(rendered["render_directory"])
    previous = tree_hashes(directory)
    assert plan.render(base=state["revision"]) == rendered
    assert tree_hashes(directory) == previous
    packet = plan.context()["contract"]
    packet["intent"] += " with an accessible fastener."
    current = plan.propose({"base_revision": state["revision"], "reason": "Clarify access", "contract": packet})
    assert current["render_available"] is False
    assert tree_hashes(directory) == previous
    with pytest.raises(CadLoopError) as exc:
        plan.freeze(base=current["revision"])
    assert exc.value.code == "PLANNING_RENDER_REQUIRED"


def test_successful_freeze_is_immutable_hash_bound_and_review_bound(tmp_path):
    plan = workspace(tmp_path)
    state = reviewable(plan)
    reviewed = plan.render(base=state["revision"])
    result = plan.freeze(base=state["revision"])
    directory = Path(result["frozen_directory"])
    original = tree_hashes(directory)
    handoff = plan.handoff()
    manifest = read_json(directory / "manifest.json")
    assert result["status"] == handoff["status"] == "FROZEN"
    assert manifest["reviewed_revision"] == state["revision"]
    assert manifest["reviewed_render_hashes"] == reviewed["manifest"]["files"]
    assert manifest["planning_revision"] == result["revision"]
    assert manifest["contract_hash"] == handoff["design_contract_hash"]
    assert plan.handoff() == handoff and tree_hashes(directory) == original
    with pytest.raises(CadLoopError) as exc:
        plan.freeze(base=result["revision"])
    assert exc.value.code == "PLANNING_FROZEN"
    assert tree_hashes(directory) == original


def test_reopen_preserves_frozen_artifact_and_requires_new_review(tmp_path):
    plan = workspace(tmp_path)
    first = frozen(plan)
    old_directory = Path(first["frozen_directory"])
    old = tree_hashes(old_directory)
    old_log = (plan.folder / "decisions.jsonl").read_bytes()
    opened = plan.reopen(base=first["revision"], reason="Review a different orientation")
    assert opened["revision"] != first["revision"] and opened["status"] == "DRAFT"
    assert opened["frozen_revision"] is None and not opened["render_available"]
    assert opened["last_frozen_revision"] == first["revision"]
    assert tree_hashes(old_directory) == old
    assert (plan.folder / "decisions.jsonl").read_bytes().startswith(old_log)
    with pytest.raises(CadLoopError) as exc:
        plan.handoff()
    assert exc.value.code == "PLANNING_NOT_FROZEN"
    selected = plan.answer(base=opened["revision"], answers=[("orientation_question", "inward")])
    plan.render(base=selected["revision"])
    second = plan.freeze(base=selected["revision"])
    assert second["status"] == "FROZEN" and second["revision"] != first["revision"]
    assert tree_hashes(old_directory) == old
    assert plan.handoff()["contract"]["parameters"][0]["value"] == "inward"


@pytest.mark.parametrize("name", ["contract.json", "modeling_context.md", "requirements_adapter.json", "manifest.json"])
def test_tampered_frozen_artifact_cannot_be_handed_off(tmp_path, name):
    plan = workspace(tmp_path)
    result = frozen(plan)
    path = Path(result["frozen_directory"]) / name
    path.write_bytes(path.read_bytes() + b"\nchanged\n")
    with pytest.raises((CadLoopError, ValueError)):
        plan.handoff()


def test_tampered_decision_log_invalidates_frozen_handoff(tmp_path):
    plan = workspace(tmp_path)
    frozen(plan)
    (plan.folder / "decisions.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(CadLoopError) as exc:
        plan.handoff()
    assert exc.value.code == "PLANNING_TAMPERED"


def test_tampered_current_svg_blocks_freeze(tmp_path):
    plan = workspace(tmp_path)
    state = reviewable(plan)
    rendered = plan.render()
    (Path(rendered["render_directory"]) / "front.svg").write_text("<svg/>\n", encoding="utf-8")
    with pytest.raises(CadLoopError) as exc:
        plan.freeze(base=state["revision"])
    assert exc.value.code == "PLANNING_RENDER_TAMPERED"
    assert not (plan.folder / "frozen").exists()


def test_failed_freeze_commit_restores_all_current_evidence(tmp_path, monkeypatch):
    plan = workspace(tmp_path)
    state = reviewable(plan)
    plan.render()
    before = tree_hashes(plan.folder)
    import cadloop.planning.store as store
    real_write = store.write_json

    def fail_commit(path, value):
        if path.name == "state.json":
            raise OSError("Simulated freeze commit failure")
        return real_write(path, value)

    monkeypatch.setattr(store, "write_json", fail_commit)
    with pytest.raises(OSError):
        plan.freeze(base=state["revision"])
    assert tree_hashes(plan.folder) == before
    assert plan.state()["revision"] == state["revision"]
    assert plan.state()["status"] == "REVIEWABLE"


def test_post_commit_cleanup_failure_preserves_frozen_artifacts(tmp_path, monkeypatch):
    plan=workspace(tmp_path)
    state=reviewable(plan)
    plan.render()
    real_unlink=Path.unlink
    failed=False
    def fail_once(path,*args,**kwargs):
        nonlocal failed
        if path.name=='transaction.json' and not failed:
            failed=True
            raise OSError('Simulated journal cleanup failure')
        return real_unlink(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',fail_once)
    result=plan.freeze(base=state['revision'])
    assert failed and result['status']=='FROZEN'
    assert plan.handoff()['design_contract_revision']==result['revision']


def test_rejected_freeze_preserves_preexisting_artifact(tmp_path, monkeypatch):
    plan = workspace(tmp_path)
    state = reviewable(plan)
    plan.render()
    _, previous, current = plan._load()
    data = current.model_dump()
    data["status"] = "FROZEN"
    record = plan._make_record(DesignContract.model_validate(data), previous, "User confirmed rendered design intent")
    target = plan.folder / "frozen" / record["revision"]
    target.mkdir(parents=True)
    keep = target / "preserve.txt"
    keep.write_text("Existing immutable artifact", encoding="utf-8")
    expected_hash = file_hash(keep)
    monkeypatch.setattr(plan, "_make_record", lambda *args, **kwargs: record)
    with pytest.raises(CadLoopError) as exc:
        plan.freeze(base=state["revision"])
    assert exc.value.code == "PLANNING_HISTORY_EXISTS"
    assert keep.exists() and file_hash(keep) == expected_hash
    assert plan.state()["revision"] == state["revision"]


def test_after_two_rounds_remaining_critical_question_still_blocks(tmp_path):
    plan = workspace(tmp_path)
    packet = proposal(plan)
    seed = packet["contract"]
    parameter, interface, question = seed["parameters"][0], seed["interfaces"][0], seed["decision_candidates"][0]
    seed.update(parameters=[], interfaces=[], decision_candidates=[])
    for index in range(7):
        p, i, q = copy.deepcopy(parameter), copy.deepcopy(interface), copy.deepcopy(question)
        p["id"], i["id"], q["id"] = f"orientation_{index}", f"mounting_{index}", f"question_{index}"
        i["parameter_refs"] = i["required_parameter_refs"] = [p["id"]]
        q["affects"] = [p["id"], i["id"]]
        for option in q["options"]:
            option["updates"][0]["path"] = f"/parameters/{p['id']}/value"
            option["updates"][1]["path"] = f"/interfaces/{i['id']}/resolved"
        seed["parameters"].append(p)
        seed["interfaces"].append(i)
        seed["decision_candidates"].append(q)
    state = plan.propose(packet)
    for _ in range(2):
        state = plan.answer(base=state["revision"], answers=[(q["id"], "outward") for q in state["questions"]])
    assert state["review_rounds"] == 2 and len(state["questions"]) == 1
    assert state["status"] == "NEEDS_INPUT"
    result = plan.freeze(base=state["revision"])
    assert result["status"] == "NEEDS_INPUT" and result["frozen"] is False
    assert any(issue["code"] == "UNANSWERED_DECISION" for issue in result["blocking"])


@pytest.mark.parametrize("commit_first", [False, True])
def test_killed_controller_recovers_old_or_committed_freeze(tmp_path, commit_first):
    plan = workspace(tmp_path)
    old_state = reviewable(plan)
    plan.render()
    before = tree_hashes(plan.folder)
    code = """
import os
import sys
from cadloop.planning.store import PlanningProject
import cadloop.planning.store as store
real_write = store.write_json
def interrupted(path, value):
    if path.name == 'state.json':
        if sys.argv[3] == 'after':
            real_write(path, value)
        os._exit(91)
    return real_write(path, value)
store.write_json = interrupted
PlanningProject(sys.argv[1]).freeze(base=sys.argv[2])
"""
    result = subprocess.run([sys.executable, "-c", code, str(plan.root), old_state["revision"],
                             "after" if commit_first else "before"], capture_output=True, text=True)
    assert result.returncode == 91, result.stderr
    assert (plan.folder / "transaction.json").exists()
    current = plan.state()
    assert not (plan.folder / "transaction.json").exists()
    if commit_first:
        assert current["status"] == "FROZEN" and current["revision"] != old_state["revision"]
        assert plan.handoff()["design_contract_revision"] == current["revision"]
    else:
        assert current["revision"] == old_state["revision"] and current["status"] == "REVIEWABLE"
        assert tree_hashes(plan.folder) == before
