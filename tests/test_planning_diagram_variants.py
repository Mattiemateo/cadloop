"""Geometry choices are explicit, validated layers, not substituted captions."""
import copy
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from pydantic import ValidationError

from cadloop.errors import CadLoopError
from cadloop.planning.audit import audit
from cadloop.planning.contracts import DesignContract
from cadloop.planning.diagrams import diagram_views, render_svgs
from cadloop.planning.store import PlanningProject
from cadloop.util import read_json

FIXTURE = Path(__file__).parents[1] / 'benchmarks/planning/fixtures/motor_mount'
CHOICES = ('shaft_outward', 'shaft_inward', 'shaft_vertical')


def fixture_data():
    return read_json(FIXTURE / 'gold_contract.json')


def geometry(svg):
    root = ET.fromstring(svg)
    # Revision, captions, component names and parameter text cannot satisfy this comparison.
    for parent in root.iter():
        for node in list(parent):
            if node.tag.rsplit('}', 1)[-1] in {'text', 'title'}:
                parent.remove(node)
    return ET.tostring(root)


def plan_with_proposal(path):
    plan = PlanningProject.initialize(path, brief=(FIXTURE / 'lazy_brief.txt').read_text().strip())
    context = plan.context()
    packet = read_json(FIXTURE / 'proposal.json')
    packet['base_revision'] = context['revision']
    packet['contract'].update(task_id=context['contract']['task_id'], revision=context['revision'])
    plan.propose(packet)
    return plan


def test_each_answer_changes_actual_geometry_in_every_view_and_freezes(tmp_path):
    renders = {}
    for choice in CHOICES:
        plan = plan_with_proposal(tmp_path / choice)
        before = plan.render()
        old_hashes = before['manifest']['files'].copy()
        answered = plan.answer(base=plan.state()['revision'], answers=[('motor_orientation_question', choice)])
        assert answered['status'] == 'REVIEWABLE'
        with pytest.raises(CadLoopError, match='Render and review'):
            plan.freeze(base=answered['revision'])
        rendered = plan.render(base=answered['revision'])
        renders[choice] = {view: (Path(rendered['render_directory']) / (view+'.svg')).read_text()
                           for view in ('front', 'side', 'top')}
        assert rendered['manifest']['files'] != old_hashes
        assert read_json(Path(before['render_directory']) / 'manifest.json')['files'] == old_hashes
        frozen = plan.freeze(base=answered['revision'])
        assert frozen['frozen'] is True
        assert plan.handoff()['manifest']['reviewed_render_hashes'] == rendered['manifest']['files']
    for view in ('front', 'side', 'top'):
        assert len({geometry(renders[choice][view]) for choice in CHOICES}) == 3


@pytest.mark.parametrize('choice', CHOICES)
def test_shaft_direction_is_geometric_and_matches_declared_projection(choice):
    data = fixture_data()
    next(p for p in data['parameters'] if p['id'] == 'motor_orientation')['value'] = choice
    contract = DesignContract.model_validate(data)
    views, issues = diagram_views(contract)
    assert not issues
    side = next(p for p in views['side'] if p.id.endswith('shaft_direction'))
    top = views['top']
    if choice == 'shaft_outward':
        assert side.x2 < side.x and side.y2 == side.y
        shaft = next(p for p in top if p.id.endswith('shaft_direction'))
        assert shaft.y2 < shaft.y and shaft.x2 == shaft.x
    elif choice == 'shaft_inward':
        assert side.x2 > side.x and side.y2 == side.y
        shaft = next(p for p in top if p.id.endswith('shaft_direction'))
        assert shaft.y2 > shaft.y and shaft.x2 == shaft.x
    else:
        assert side.y2 < side.y and side.x2 == side.x
        assert any(p.type == 'circle' and p.id.endswith('shaft_toward_viewer') for p in top)
    assert render_svgs(contract) == render_svgs(contract)


def test_unresolved_geometry_is_explicit_and_not_a_guessed_variant(tmp_path):
    plan = plan_with_proposal(tmp_path / 'unanswered')
    contract = DesignContract.model_validate(plan.context()['contract'])
    views, issues = diagram_views(contract)
    assert [issue['code'] for issue in issues] == ['DIAGRAM_VARIANT_UNRESOLVED']
    assert all(all(p.type == 'label' for p in items) for items in views.values())
    assert all('Concept geometry incomplete' in svg for svg in render_svgs(contract).values())
    assert 'DIAGRAM_VARIANT_UNRESOLVED' in {item['code'] for item in plan.audit()['blocking']}
    assert not plan.freeze(base=plan.state()['revision'])['frozen']


def test_missing_selected_case_cannot_render_or_freeze(tmp_path):
    plan = plan_with_proposal(tmp_path / 'unsupported')
    packet = {'base_revision': plan.state()['revision'], 'reason': 'Remove unsupported variant',
              'contract': plan.context()['contract']}
    del packet['contract']['diagram_spec']['variant_sets'][0]['cases']['shaft_vertical']
    plan.propose(packet)
    state = plan.answer(base=plan.state()['revision'], answers=[('motor_orientation_question', 'shaft_vertical')])
    assert state['status'] == 'REVIEW_REQUIRED'
    assert 'DIAGRAM_VARIANT_UNSUPPORTED' in {item['code'] for item in plan.audit()['blocking']}
    with pytest.raises(CadLoopError) as error:
        plan.render()
    assert error.value.code == 'PLANNING_DIAGRAM_VARIANT_UNSUPPORTED'
    assert not plan.freeze(base=state['revision'])['frozen']


@pytest.mark.parametrize('mutation, message', [
    (lambda d, v: v.update(parameter_ref='absent'), 'known enum'),
    (lambda d, v: v.update(parameter_ref='motor_size_mm'), 'known enum'),
    (lambda d, v: v['cases'].update(unknown=v['cases'].pop('shaft_vertical')), 'declared enum'),
    (lambda d, v: v['cases']['shaft_vertical'].pop('top'), 'nonempty front'),
    (lambda d, v: v['cases']['shaft_vertical'].update(top=[]), 'nonempty front'),
    (lambda d, v: v['cases']['shaft_vertical']['top'][0].update(component_ref='absent'), 'Unresolved diagram'),
    (lambda d, v: v['cases']['shaft_vertical']['top'][0].update(parameter_ref='absent'), 'Unresolved diagram'),
    (lambda d, v: v['cases']['shaft_vertical']['top'][0].update(id='motor'), 'globally unique'),
    (lambda d, v: d['diagram_spec']['variant_sets'].append({**v, 'id':'duplicate_binding', 'cases':{}}), 'at least 1'),
])
def test_invalid_variant_schema_fails_closed(mutation, message):
    data = fixture_data()
    mutation(data, data['diagram_spec']['variant_sets'][0])
    with pytest.raises(ValidationError, match=message):
        DesignContract.model_validate(data)


def test_label_only_differences_and_unused_coordinates_are_not_geometric_changes():
    data = fixture_data()
    variants = data['diagram_spec']['variant_sets'][0]
    other = copy.deepcopy(variants['cases']['shaft_outward'])
    for view in other.values():
        for p in view:
            p['id'] += '_different'
            p['text'] = 'A different caption'
            if p['type'] == 'circle':
                p['width'] = 42.0  # Ignored by circle rendering; cannot count as changed geometry.
    variants['cases']['shaft_inward'] = other
    with pytest.raises(ValidationError, match='distinct geometry'):
        DesignContract.model_validate(data)


def test_variant_binding_is_generic_not_motor_or_option_id_specific():
    data = fixture_data()
    data['accepted_decisions'] = []
    data['decision_candidates'] = []
    data['interfaces'] = []
    data['constraints'] = []
    parameter = next(p for p in data['parameters'] if p['id'] == 'motor_orientation')
    parameter.update(id='assembly_direction', enum_values=['left', 'right', 'up'], value='up')
    variants = data['diagram_spec']['variant_sets'][0]
    variants['parameter_ref'] = 'assembly_direction'
    variants['cases'] = dict(zip(['left', 'right', 'up'], variants['cases'].values()))
    for primitives in data['diagram_spec']['views'].values():
        for primitive in primitives:
            if primitive['parameter_ref'] == 'motor_orientation':
                primitive['parameter_ref'] = 'assembly_direction'
    views, issues = diagram_views(DesignContract.model_validate(data))
    assert not issues
    assert next(p for p in views['side'] if p.id.endswith('shaft_direction')).y2 == 200.0


def test_variant_literals_are_audited_even_in_unselected_cases():
    data = fixture_data()
    primitive = data['diagram_spec']['variant_sets'][0]['cases']['shaft_vertical']['top'][0]
    primitive.update(text='motor width 99 mm')
    assert 'DIAGRAM_LITERAL_ENGINEERING_VALUE' in {item['code'] for item in audit(data)['blocking']}


def test_static_schema_serialization_preserves_legacy_contract_bytes():
    data = fixture_data()
    data['diagram_spec'].pop('variant_sets')
    assert DesignContract.model_validate(data).model_dump() == data
    data['diagram_spec']['variant_sets'] = []
    serialized = DesignContract.model_validate(data).model_dump_json()
    assert 'variant_sets' not in json.loads(serialized)['diagram_spec']


def test_pre_variant_frozen_workspace_still_reads_renders_and_hands_off(tmp_path):
    from zipfile import ZipFile
    from cadloop.util import tree_hashes

    fixture = Path(__file__).parent / 'fixtures/planning/static_frozen_v1.zip'
    with ZipFile(fixture) as archive:
        archive.extractall(tmp_path)
    plan = PlanningProject(tmp_path)
    assert plan.state()['status'] == 'FROZEN'
    before = tree_hashes(tmp_path)
    contract = plan.context()['contract']
    assert 'variant_sets' not in contract['diagram_spec']
    rendered = plan.render()
    handoff = plan.handoff()
    assert handoff['contract']['status'] == 'FROZEN'
    assert rendered['manifest']['files'] == handoff['manifest']['render_hashes']
    assert tree_hashes(tmp_path) == before
