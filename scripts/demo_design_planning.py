#!/usr/bin/env python3
"""Replay the synthetic planning fixture, without a model provider or CAD execution."""
from __future__ import annotations

import argparse
from pathlib import Path

from cadloop.errors import CadLoopError
from cadloop.planning.contracts import DesignContract
from cadloop.planning.diagrams import parameter_label
from cadloop.planning.store import PlanningProject
from cadloop.util import canonical, file_hash, read_json, write_json

FIXTURE = Path(__file__).resolve().parents[1] / "benchmarks/planning/fixtures/motor_mount"
CANONICAL_DIMENSIONS = ("motor_size_mm", "extrusion_size_mm", "motor_pattern_mm", "shaft_clearance_mm")


def run_demo(directory: str | Path, fixture: str | Path = FIXTURE) -> dict:
    """Exercise the same reviewed tools an external account-authenticated agent uses."""
    fixture = Path(fixture)
    brief = (fixture / "lazy_brief.txt").read_text(encoding="utf-8").strip()
    packet = read_json(fixture / "proposal.json")
    oracle = read_json(fixture / "question_oracle.json")
    plan = PlanningProject.initialize(directory, brief=brief)
    context = plan.context()
    packet["base_revision"] = context["revision"]
    packet["contract"].update(task_id=context["contract"]["task_id"], revision=context["revision"],
                               status=context["contract"]["status"])
    proposed = plan.propose(packet)
    questions = plan.questions()["questions"]
    assert [q["id"] for q in questions] == oracle["expected_question_ids"]
    assert len(questions) == oracle["maximum_questions"] == 1
    question = questions[0]
    selected = oracle["answers"][question["id"]]
    assert selected == "shaft_outward"
    assert next(option for option in question["options"] if option["id"] == selected)["recommended"]
    answered = plan.answer(base=proposed["revision"], answers=list(oracle["answers"].items()))
    assert answered["status"] == "REVIEWABLE"
    audited = plan.audit()
    assert audited["blocking"] == []
    rendered = plan.render(base=answered["revision"])
    assert set(rendered["manifest"]["files"]) == {"front.svg", "side.svg", "top.svg"}
    frozen = plan.freeze(base=answered["revision"])
    assert frozen["status"] == "FROZEN" and frozen["frozen"]
    handoff = plan.handoff()
    contract = DesignContract.model_validate(handoff["contract"])
    dimensions = {p.id: {"value": p.value, "unit": p.unit} for p in contract.parameters if p.id in CANONICAL_DIMENSIONS}
    for parameter in contract.parameters:
        if parameter.id in CANONICAL_DIMENSIONS:
            assert handoff["modeling_context"].count(parameter_label(parameter)) == 1
    frozen_directory = Path(handoff["directory"])
    render_directory = Path(frozen["render_directory"])
    summary = {
        "schema_version": 1,
        "workspace": str(plan.root),
        "fixture": str(fixture.resolve()),
        "fixture_hashes": {name: file_hash(fixture / name) for name in
                           ("lazy_brief.txt", "proposal.json", "question_oracle.json")},
        "statuses": {"initial": context["contract"]["status"], "proposed": proposed["status"],
                     "answered": answered["status"], "frozen": frozen["status"]},
        "status": frozen["status"],
        "questions": questions,
        "question_count": len(questions),
        "answers": oracle["answers"],
        "audit": audited,
        "reviewed_revision": answered["revision"],
        "revision": handoff["design_contract_revision"],
        "contract_hash": handoff["design_contract_hash"],
        "canonical_dimensions": dimensions,
        "reviewed_render_directory": rendered["render_directory"],
        "render_directory": str(render_directory),
        "svg_files": {name: str(render_directory / name) for name in rendered["manifest"]["files"]},
        "render_hashes": handoff["manifest"]["render_hashes"],
        "frozen_directory": str(frozen_directory),
        "contract_file": str(frozen_directory / "contract.json"),
        "manifest_file": str(frozen_directory / "manifest.json"),
        "modeling_context": str(frozen_directory / "modeling_context.md"),
        "handoff_hash": file_hash(frozen_directory / "modeling_context.md"),
        "unsupported_verification": handoff["requirements_adapter"]["unsupported"],
        "engineering_approval": False,
        "model_quality_benchmark": False,
    }
    write_json(plan.root / "planning_demo_result.json", summary)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path, help="New planning workspace")
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    arguments = parser.parse_args(argv)
    try:
        result = run_demo(arguments.directory, arguments.fixture)
    except CadLoopError as exc:
        print(canonical(exc.as_dict()).decode())
        return 2
    print(canonical(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
