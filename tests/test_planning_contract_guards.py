"""Planning authority must survive handoff and later model-authored proposals.

These tests use synthetic source imports only; no CAD worker is executed.
"""
from copy import deepcopy

import pytest

from cadloop.errors import CadLoopError
from cadloop.planning.store import PlanningProject
from cadloop.project import Project
from cadloop.util import tree_hashes, write_json


def plate_proposal(workspace):
    """Prepare an independent, reviewable packet using public planner context."""
    context = workspace.context()
    contract = deepcopy(context["contract"])
    contract.update(
        intent="A synthetic plate retaining the approved width",
        components=[{"id": "plate", "name": "Plate", "role": "fabricated part"}],
        parameters=[{
            "id": "width", "name": "Plate width", "kind": "number",
            "mode": "FIXED", "unit": "mm", "value": 42.0,
            "impact": "CRITICAL", "source_refs": ["src_user_1"],
        }],
        requirements=[{
            "id": "plate_width", "text": "Preserve the approved plate width",
            "hard": True, "impact": "CRITICAL", "source_refs": ["src_user_1"],
        }],
        verification_intent=[{
            "id": "width_check", "text": "Measure the approved plate width",
            "kind": "dimension", "axis": "x", "component_refs": ["plate"],
            "parameter_refs": ["width"], "requirement_refs": ["plate_width"],
            "geometry_required": True,
        }],
        diagram_spec={"views": {
            view: [{"id": view + "_plate", "type": "rectangle",
                    "width": 400.0, "height": 100.0, "component_ref": "plate"}]
            for view in ("front", "side", "top")
        }},
    )
    return {"base_revision": context["revision"], "reason": "Interpret approved plate intent",
            "contract": contract}


def frozen_plate(tmp_path, *, change=None, parameters=None):
    """Clone the integration preparation workflow without altering shared helpers."""
    workspace = PlanningProject.initialize(
        tmp_path / "plan", brief="A 42 mm plate with approved wall limits and verification intent")
    packet = plate_proposal(workspace)
    if change is not None:
        change(packet["contract"])
    state = workspace.propose(packet)
    assert workspace.audit()["blocking"] == []
    workspace.render()
    state = workspace.freeze(base=state["revision"])
    assert state["status"] == "FROZEN"
    design = tmp_path / "source"
    design.mkdir()
    write_json(design / "parameters.json", {"width": 42.0, **(parameters or {})})
    (design / "model.py").write_text(
        'import cadquery as cq\n'
        'from cadloop.authoring import Scene\n\n'
        'def build(p):\n'
        '    scene = Scene()\n'
        '    scene.add("plate", cq.Workplane("XY").box(p["width"], 10, 3).val())\n'
        '    return scene\n', encoding="utf-8")
    return workspace, state, design


@pytest.mark.parametrize("kind", ["number", "integer"])
@pytest.mark.parametrize("impact", ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
@pytest.mark.parametrize("bound", ["minimum", "maximum"])
@pytest.mark.parametrize("supplied_requirements", [False, True])
def test_one_sided_approved_bounds_are_visible_and_cannot_be_weakened_at_import(
        tmp_path, kind, impact, bound, supplied_requirements):
    def add_wall(contract):
        contract["parameters"].append({
            "id": "wall", "name": "Wall thickness", "kind": kind,
            "mode": "BOUNDED", "unit": "mm", bound: 3.0,
            "impact": impact, "source_refs": ["src_user_1"],
        })

    # Values deliberately violate the approved limit while fitting the supplied
    # weakening bounds. Without supplied requirements the source omits wall, so
    # a failure cannot merely come from an unknown imported parameter.
    violating_value = 1 if bound == "minimum" else 8
    parameters = {"wall": violating_value} if supplied_requirements else {}
    workspace, state, design = frozen_plate(tmp_path, change=add_wall, parameters=parameters)
    handoff = workspace.handoff()
    adapter = handoff["requirements_adapter"]
    issues = [item for item in adapter["unsupported"] if item["id"] == "wall"]
    assert issues, "A one-sided approved parameter must not disappear from the adapter"
    assert issues[0]["code"] == "PLANNING_PARAMETER_UNSUPPORTED"
    assert "UNSUPPORTED `wall`" in handoff["modeling_context"]
    assert "wall" not in adapter["requirements"]["parameters"]
    wall = next(item for item in handoff["contract"]["parameters"] if item["id"] == "wall")
    assert wall[bound] == 3.0
    assert wall["maximum" if bound == "minimum" else "minimum"] is None

    requirements = None
    if supplied_requirements:
        data = deepcopy(adapter["requirements"])
        low, high = (0.0, 2.0) if bound == "minimum" else (7.0, 9.0)
        data["parameters"]["wall"] = {
            "kind": kind, "unit": "mm", "minimum": low, "maximum": high,
            "description": "A supplied limit that weakens frozen intent",
        }
        requirements = tmp_path / "weaker_requirements.json"
        write_json(requirements, data)

    before = tree_hashes(workspace.root)
    with pytest.raises(CadLoopError) as exc:
        workspace.materialize(base=state["revision"], design_dir=design, requirements=requirements)
    assert exc.value.code == "PLANNING_VERIFICATION_UNSUPPORTED"
    assert any(item["id"] == "wall" for item in exc.value.details["unsupported"])
    assert tree_hashes(workspace.root) == before
    assert workspace.state()["status"] == "FROZEN"


@pytest.mark.parametrize("kind", ["number", "integer"])
def test_approved_both_sided_bounds_still_materialize_without_invented_limits(tmp_path, kind):
    def add_wall(contract):
        contract["parameters"].append({
            "id": "wall", "name": "Wall thickness", "kind": kind,
            "mode": "BOUNDED", "unit": "mm", "minimum": 3.0, "maximum": 6.0,
            "impact": "CRITICAL", "source_refs": ["src_user_1"],
        })

    workspace, state, design = frozen_plate(tmp_path, change=add_wall, parameters={"wall": 4})
    adapter = workspace.handoff()["requirements_adapter"]
    assert not any(item["id"] == "wall" for item in adapter["unsupported"])
    assert adapter["requirements"]["parameters"]["wall"]["minimum"] == 3.0
    assert adapter["requirements"]["parameters"]["wall"]["maximum"] == 6.0
    result = workspace.materialize(base=state["revision"], design_dir=design)
    assert result["status"] == "MATERIALIZED"
    project = Project(workspace.root)
    assert project.parameters()["wall"] == 4
    assert project.requirements().parameters["wall"].minimum == 3.0
    assert project.requirements().parameters["wall"].maximum == 6.0


@pytest.mark.parametrize("impact", ["MEDIUM", "HIGH", "CRITICAL"])
@pytest.mark.parametrize("requirement_refs", [[], ["required_bore"]], ids=["no_refs", "linked_requirement"])
def test_unsupported_mandatory_geometry_blocks_every_impact_and_missing_refs(
        tmp_path, impact, requirement_refs):
    def require_bore(contract):
        contract["requirements"].append({
            "id": "required_bore", "text": "Plate must contain a through bore",
            "hard": True, "impact": impact, "source_refs": ["src_user_1"],
        })
        contract["verification_intent"].append({
            "id": "bore_review", "text": "Verify the required bore geometry",
            "kind": "manual", "component_refs": ["plate"],
            "requirement_refs": requirement_refs, "geometry_required": True,
        })

    workspace, state, design = frozen_plate(tmp_path, change=require_bore)
    adapter = workspace.handoff()["requirements_adapter"]
    assert any(item["id"] == "bore_review" for item in adapter["unsupported"])
    before = tree_hashes(workspace.root)
    with pytest.raises(CadLoopError) as exc:
        workspace.materialize(base=state["revision"], design_dir=design)
    assert exc.value.code == "PLANNING_VERIFICATION_UNSUPPORTED"
    assert any(item["id"] == "bore_review" for item in exc.value.details["unsupported"])
    assert tree_hashes(workspace.root) == before


def test_optional_manual_engineering_review_remains_visible_after_import(tmp_path):
    def add_engineering_review(contract):
        contract["verification_intent"].append({
            "id": "strength_review", "text": "Review strength against actual service loads",
            "kind": "manual", "component_refs": ["plate"], "geometry_required": False,
        })

    workspace, state, design = frozen_plate(tmp_path, change=add_engineering_review)
    issue = next(item for item in workspace.handoff()["requirements_adapter"]["unsupported"]
                 if item["id"] == "strength_review")
    assert issue["critical"] is False
    result = workspace.materialize(base=state["revision"], design_dir=design)
    assert result["status"] == "MATERIALIZED"
    assert any("strength_review" in blocker
               for blocker in Project(workspace.root).requirements().engineering_blockers)


def selected_height(tmp_path):
    workspace = PlanningProject.initialize(
        tmp_path / "plan", brief="Use a 42 mm plate width and ask me to select the fixed height")
    packet = plate_proposal(workspace)
    packet["contract"]["parameters"].append({
        "id": "height", "name": "Plate height", "kind": "number",
        "mode": "FIXED", "unit": "mm", "value": None, "impact": "CRITICAL",
    })
    packet["contract"]["decision_candidates"] = [{
        "id": "height_question", "question": "Choose the fixed plate height",
        "confidence": 0.5, "impact": "CRITICAL", "change_cost": "HIGH", "affects": ["height"],
        "options": [{
            "id": identifier, "label": identifier, "description": "Use this fixed height",
            "recommended": identifier == "three",
            "updates": [{"path": "/parameters/height/value", "value": value}],
        } for identifier, value in [("three", 3.0), ("six", 6.0)]],
    }]
    state = workspace.propose(packet)
    workspace.answer(base=state["revision"], answers=[("height_question", "three")])
    assert workspace.audit()["blocking"] == []
    return workspace


@pytest.mark.parametrize("change", [
    {"mode": "FREE"},
    {"mode": "OPTIMIZED", "objective": "minimize"},
    {"mode": "BOUNDED", "minimum": 0.1, "maximum": 10.0},
    {"kind": "integer"},
    {"unit": "deg"},
], ids=["free", "optimized", "bounded", "kind", "unit"])
def test_proposal_cannot_reinterpret_an_explicitly_selected_parameter(tmp_path, change):
    workspace = selected_height(tmp_path)
    context = workspace.context()
    contract = deepcopy(context["contract"])
    next(item for item in contract["parameters"] if item["id"] == "height").update(change)
    before = tree_hashes(workspace.root)
    with pytest.raises(CadLoopError) as exc:
        workspace.propose({"base_revision": context["revision"], "reason": "Reinterpret selected height",
                           "contract": contract})
    assert exc.value.code == "PLANNING_PROTECTED_STATE"
    assert tree_hashes(workspace.root) == before
    assert workspace.context()["contract"] == context["contract"]


@pytest.mark.parametrize("mode", ["FIXED", "FREE", "OPTIMIZED", "BOUNDED"])
def test_new_explicit_decision_can_legitimately_supersede_selected_mode_and_value(tmp_path, mode):
    workspace = selected_height(tmp_path)
    context = workspace.context()
    changes = {"mode": mode, "value": 6.0}
    if mode == "OPTIMIZED":
        changes["objective"] = "minimize"
    elif mode == "BOUNDED":
        changes.update(minimum=3.0, maximum=9.0)
    context["contract"]["decision_candidates"].append({
        "id": "height_revision", "question": "Approve this change to the selected height?",
        "confidence": 0.5, "impact": "CRITICAL", "change_cost": "HIGH", "affects": ["height"],
        "options": [
            {"id": "change", "label": "Change", "description": "Approve the new mode and value",
             "recommended": True, "updates": [
                 {"path": "/parameters/height/" + field, "value": value}
                 for field, value in changes.items()]},
            {"id": "keep", "label": "Keep", "description": "Keep the prior fixed height",
             "recommended": False, "updates": [{"path": "/parameters/height/value", "value": 3.0}]},
        ],
    })
    state = workspace.propose({"base_revision": context["revision"], "reason": "Ask about a new height decision",
                               "contract": context["contract"]})
    state = workspace.answer(base=state["revision"], answers=[("height_revision", "change")])
    assert state["status"] == "REVIEWABLE"
    assert workspace.audit()["blocking"] == []
    context = workspace.context()
    height = next(item for item in context["contract"]["parameters"] if item["id"] == "height")
    assert {field: height[field] for field in changes} == changes
    assert len(context["accepted_decisions"]) == 2
    # Future proposals may preserve the newly approved semantics; the first
    # answer must not lock the parameter to its original mode forever.
    context["contract"]["intent"] = "The plate uses the latest explicitly approved height choice"
    preserved = workspace.propose({"base_revision": context["revision"], "reason": "Clarify approved intent",
                                   "contract": context["contract"]})
    assert preserved["status"] == "REVIEWABLE"


@pytest.mark.parametrize('case', ['one_sided', 'mandatory_geometry'])
@pytest.mark.parametrize('supplied_requirements', [False, True])
def test_old_frozen_adapter_cannot_bypass_current_mandatory_guards(
        tmp_path, monkeypatch, case, supplied_requirements):
    import cadloop.planning.handoff as handoff_module
    current_compile = handoff_module.compile_requirements
    def previous_compile(contract):
        # Emulate the earlier compiler during the real freeze transaction;
        # immutable manifests and receipts are produced by the controller.
        adapter = current_compile(contract)
        if case == 'one_sided':
            adapter['unsupported'] = [item for item in adapter['unsupported'] if item['id'] != 'wall']
        else:
            for item in adapter['unsupported']:
                if item['id'] == 'required_bore':
                    item['critical'] = False
        return adapter
    def add_unsupported(contract):
        if case == 'one_sided':
            contract['parameters'].append({
                'id': 'wall', 'name': 'Wall thickness', 'kind': 'number',
                'mode': 'BOUNDED', 'unit': 'mm', 'minimum': 3.0,
                'impact': 'LOW', 'source_refs': ['src_user_1'],
            })
        else:
            contract['verification_intent'].append({
                'id': 'required_bore', 'text': 'Verify the mandatory bore',
                'kind': 'manual', 'geometry_required': True, 'component_refs': ['plate'],
            })
    with monkeypatch.context() as legacy:
        legacy.setattr(handoff_module, 'compile_requirements', previous_compile)
        workspace, state, design = frozen_plate(tmp_path, change=add_unsupported)
    saved = workspace.handoff()['requirements_adapter']
    assert not any(item['critical'] for item in saved['unsupported'])
    requirements = None
    if supplied_requirements:
        requirements = tmp_path / 'legacy_requirements.json'
        write_json(requirements, saved['requirements'])
    before = tree_hashes(workspace.root)
    with pytest.raises(CadLoopError) as exc:
        workspace.materialize(base=state['revision'], design_dir=design, requirements=requirements)
    assert exc.value.code == 'PLANNING_VERIFICATION_UNSUPPORTED'
    assert any(item['id'] == ('wall' if case == 'one_sided' else 'required_bore')
               for item in exc.value.details['unsupported'])
    assert tree_hashes(workspace.root) == before
    assert workspace.handoff()['requirements_adapter'] == saved


@pytest.mark.parametrize('case', ['one_sided', 'mandatory_geometry'])
@pytest.mark.parametrize('operation', ['propose', 'evaluate', 'finish'])
def test_previously_materialized_unsupported_plan_blocks_further_cad_work(
        tmp_path, monkeypatch, case, operation):
    import cadloop.planning.handoff as handoff_module
    current_compile = handoff_module.compile_requirements
    def previous_compile(contract):
        adapter = current_compile(contract)
        if case == 'one_sided':
            adapter['unsupported'] = [item for item in adapter['unsupported'] if item['id'] != 'wall']
        else:
            for item in adapter['unsupported']:
                if item['id'] == 'required_bore':
                    item['critical'] = False
        return adapter
    def add_unsupported(contract):
        if case == 'one_sided':
            contract['parameters'].append({
                'id': 'wall', 'name': 'Wall thickness', 'kind': 'number',
                'mode': 'BOUNDED', 'unit': 'mm', 'minimum': 3.0,
                'impact': 'LOW', 'source_refs': ['src_user_1'],
            })
        else:
            contract['verification_intent'].append({
                'id': 'required_bore', 'text': 'Verify the mandatory bore',
                'kind': 'manual', 'geometry_required': True, 'component_refs': ['plate'],
            })
    with monkeypatch.context() as legacy:
        legacy.setattr(handoff_module, 'compile_requirements', previous_compile)
        workspace, state, design = frozen_plate(tmp_path, change=add_unsupported)
        workspace.materialize(base=state['revision'], design_dir=design)
    project = Project(workspace.root)
    revision = project.revision()
    before = tree_hashes(workspace.root)
    with pytest.raises(CadLoopError) as exc:
        if operation == 'propose':
            project.propose({'base_revision': revision, 'parameters': {'width': 42.0},
                             'reason': 'Cannot repair geometry while upstream mandatory intent is unsupported'})
        else:
            getattr(project, operation)(mode='trusted-native')
    assert exc.value.code == 'PLANNING_VERIFICATION_UNSUPPORTED'
    assert any(item['id'] == ('wall' if case == 'one_sided' else 'required_bore')
               for item in exc.value.details['unsupported'])
    assert tree_hashes(workspace.root) == before
    assert workspace.handoff()['design_contract_revision'] == state['revision']
    assert not (project.control / 'runs').exists()
