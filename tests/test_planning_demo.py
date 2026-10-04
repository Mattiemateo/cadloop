import json
from pathlib import Path
import subprocess
import sys

import pytest

from cadloop.errors import CadLoopError
from cadloop.planning.store import PlanningProject
from cadloop.util import digest, file_hash, read_json, tree_hashes
from scripts.demo_design_planning import CANONICAL_DIMENSIONS, FIXTURE, run_demo


def test_exact_motor_mount_fixture_vertical_slice(tmp_path):
    result = run_demo(tmp_path / "motor-mount")
    assert result["statuses"] == {"initial": "DRAFT", "proposed": "NEEDS_INPUT", "answered": "REVIEWABLE", "frozen": "FROZEN"}
    assert result["question_count"] == 1
    assert result["questions"][0]["id"] == "motor_orientation_question"
    assert result["answers"] == {"motor_orientation_question": "shaft_outward"}
    assert result["audit"]["blocking"] == []
    assert set(result["svg_files"]) == {"front.svg", "side.svg", "top.svg"}
    for name, path in result["svg_files"].items():
        assert Path(path).is_file()
        assert file_hash(Path(path)) == result["render_hashes"][name]
    frozen = read_json(Path(result["contract_file"]))
    assert frozen["status"] == "FROZEN"
    assert digest(frozen) == result["contract_hash"]
    assert frozen["brief"] == (FIXTURE / "lazy_brief.txt").read_text().strip()
    gold = read_json(FIXTURE / "gold_contract.json")
    for field in gold.keys() - {"task_id", "revision", "status", "accepted_decisions"}:
        assert frozen[field] == gold[field]
    assert result["canonical_dimensions"] == {
        "motor_size_mm": {"value": 42, "unit": "mm"},
        "extrusion_size_mm": {"value": 15, "unit": "mm"},
        "motor_pattern_mm": {"value": 31, "unit": "mm"},
        "shaft_clearance_mm": {"value": 24, "unit": "mm"},
    }
    context = Path(result["modeling_context"]).read_text()
    for identifier in CANONICAL_DIMENSIONS:
        parameter = result["canonical_dimensions"][identifier]
        assert context.count(f"{identifier} = {parameter['value']:g} mm") == 1
    plan = PlanningProject(result["workspace"])
    assert plan.state()["status"] == "FROZEN"
    assert plan.questions()["questions"] == []
    manifest = read_json(Path(result["manifest_file"]))
    assert manifest["reviewed_revision"] == result["reviewed_revision"]
    assert manifest["planning_revision"] == result["revision"]
    assert read_json(Path(result["workspace"]) / "planning_demo_result.json") == result
    assert result["engineering_approval"] is False and result["model_quality_benchmark"] is False


def test_demo_never_overwrites_existing_workspace(tmp_path):
    directory = tmp_path / "demo"
    run_demo(directory)
    before = tree_hashes(directory)
    with pytest.raises(CadLoopError) as exc:
        run_demo(directory)
    assert exc.value.code == "DIRECTORY_NOT_EMPTY"
    assert tree_hashes(directory) == before


def test_planning_demo_script_emits_json(tmp_path):
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run([sys.executable, str(root / "scripts/demo_design_planning.py"),
                                "--directory", str(tmp_path / "demo")],
                               cwd=root, text=True, capture_output=True)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "FROZEN" and result["question_count"] == 1
