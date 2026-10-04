"""Regression coverage for scenario progress and final search transactions."""
from copy import deepcopy

import pytest

from cadloop.checks import result
from cadloop.errors import CadLoopError
from cadloop.feedback import progress_key
from cadloop.loop import ReplayProvider, repair_loop
from cadloop.project import Project
from cadloop.search import search_parameter
from cadloop.util import read_json, write_json


def test_progress_key_includes_scenario_measurements_and_blocker_counts():
    report = {
        'checks': [result('AUTO_parametric_thicker', 'fail', 'PARAMETRIC_RESPONSE_FAILED', 'Variant')],
        'parametric_tests': [{'id': 'thicker', 'progress_key': [0, 2, .2]}],
    }
    assert progress_key(report) == [0, 2, .2]
    better = deepcopy(report)
    better['parametric_tests'][0]['progress_key'] = [0, 2, .1]
    assert progress_key(better) < progress_key(report)
    better['parametric_tests'][0]['progress_key'] = [1, 2, .1]
    assert progress_key(better) > progress_key(report)


@pytest.mark.integration
def test_improving_required_response_does_not_prematurely_stop_loop(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'model.py').write_text('''import cadquery as cq

def build(p):
    length = 50 + (p["thickness"] - 8) * p["slope"]
    return {"plate": cq.Workplane("XY").box(length, 30, p["thickness"])}
''')
    write_json(source / 'parameters.json', {'thickness': 8, 'slope': 0})
    length = {'id': 'length', 'kind': 'dimension', 'part': 'plate', 'axis': 'x',
              'description': 'Length', 'minimum': 49.99, 'maximum': 50.01}
    thickness = {'id': 'thickness', 'kind': 'dimension', 'part': 'plate', 'axis': 'z',
                 'description': 'Thickness', 'minimum': 7.99, 'maximum': 8.01}
    requirements = {
        'name': 'Response progress', 'description': 'A thickness change increases length',
        'expected_parts': ['plate'], 'engineering_blockers': ['Synthetic test only'],
        'parameters': {
            'thickness': {'kind': 'number', 'unit': 'mm', 'minimum': 5, 'maximum': 12,
                          'description': 'Thickness'},
            'slope': {'kind': 'number', 'unit': 'count', 'minimum': 0, 'maximum': 2,
                      'description': 'Length change per thickness change'},
        },
        'checks': [length, thickness],
        'parametric_tests': [{
            'id': 'thicker', 'description': '10 mm thickness requires 54 mm length',
            'parameters': {'thickness': 10},
            'overrides': [{**length, 'minimum': 53.99, 'maximum': 54.01},
                          {**thickness, 'minimum': 9.99, 'maximum': 10.01}],
        }],
    }
    write_json(tmp_path / 'requirements.json', requirements)
    project = Project.create(tmp_path / 'project', requirements=tmp_path / 'requirements.json',
                             design_dir=source)
    monkeypatch.setattr(project, '_render_preview', lambda *a, **kw: None)
    provider = ReplayProvider([{
        'kind': 'propose',
        'proposal': {'base_revision': '$CURRENT_REVISION', 'parameters': {'slope': slope},
                     'reason': 'Improve the measured variant length'},
    } for slope in [.5, 1, 2]])
    state = repair_loop(project, provider, mode='trusted-native', max_steps=5)
    assert state['status'] == 'PARAMETRIC_ACCEPTED'
    assert provider.calls == 3
    assert state['final_feedback']['task_accepted'] and state['final_feedback']['exported']
    assert project.parameters() == {'thickness': 8, 'slope': 2}


def test_failed_fresh_search_restores_and_rechecks_original(project, monkeypatch):
    before = project.parameters()
    calls = []
    def evaluate(**kwargs):
        calls.append((project.parameters(), kwargs))
        passed = len(calls) != 2
        return {'geometry_accepted': passed, 'task_accepted': passed,
                'run_id': str(len(calls)), 'revision': project.revision(),
                'status': 'GEOMETRY_ACCEPTED' if passed else 'REPAIR_REQUIRED',
                'summary': {}, 'blocker_ids': [] if passed else ['AUTO_execution']}
    monkeypatch.setattr(project, 'evaluate', evaluate)
    searched = search_parameter(project, 'gap_mm', [12], mode='trusted-native',
                                fixed={'include_spacer': True})
    assert searched['status'] == 'FINAL_VALIDATION_FAILED' and searched['value'] is None
    assert project.parameters() == before
    assert [params['gap_mm'] for params, _ in calls] == [12, 12, before['gap_mm']]
    assert calls[1][1]['force'] and calls[2][1]['force']
    assert not searched['final']['task_accepted']
    assert searched['restored_final']['task_accepted']
    assert searched['restored_final']['revision'] == project.revision()


@pytest.mark.parametrize('exception', [OSError, KeyboardInterrupt, SystemExit])
def test_final_search_exception_or_interrupt_restores_original(project, monkeypatch, exception):
    before = project.parameters()
    calls = []
    def evaluate(**kwargs):
        calls.append(project.parameters())
        if len(calls) == 2:
            raise exception('Injected final validation failure')
        return {'geometry_accepted': True, 'run_id': 'candidate', 'revision': project.revision(),
                'status': 'GEOMETRY_ACCEPTED', 'summary': {}, 'blocker_ids': []}
    monkeypatch.setattr(project, 'evaluate', evaluate)
    with pytest.raises(exception):
        search_parameter(project, 'gap_mm', [12], mode='trusted-native',
                         fixed={'include_spacer': True})
    assert project.parameters() == before
    # Both controller locks must also be released after the rollback.
    project.propose({'base_revision': project.revision(), 'parameters': {'gap_mm': 10},
                     'reason': 'Controller remains usable after interruption'})


@pytest.mark.parametrize('timeout', [0, -1, 301, float('nan'), float('inf'), True, '45', None])
def test_invalid_loop_timeout_does_not_create_or_poison_session(project, timeout):
    with pytest.raises(CadLoopError) as error:
        repair_loop(project, ReplayProvider([]), mode='trusted-native', timeout=timeout)
    assert error.value.code == 'INVALID_TIMEOUT'
    assert not (project.control / 'sessions').exists()


def test_loop_can_start_after_rejected_timeout(project, monkeypatch):
    provider = ReplayProvider([])
    with pytest.raises(CadLoopError, match='timeout'):
        repair_loop(project, provider, mode='trusted-native', timeout=0)
    monkeypatch.setattr(project, 'evaluate', lambda **kwargs: {
        'geometry_accepted': False, 'task_accepted': False, 'progress_key': [0, 1, 0],
        'status': 'REPAIR_REQUIRED',
    })
    state = repair_loop(project, provider, mode='trusted-native', timeout=45)
    assert state['status'] == 'WORKER_STOPPED'
    assert provider.calls == 1


@pytest.mark.parametrize('options,code', [
    ({'mode': 'invalid'}, 'EXECUTION_MODE_REQUIRED'),
    ({'max_steps': 1.5}, 'STEP_LIMIT'),
    ({'max_steps': True}, 'STEP_LIMIT'),
    ({'max_steps': None}, 'STEP_LIMIT'),
])
def test_invalid_loop_options_do_not_create_a_session(project, options, code):
    with pytest.raises(CadLoopError) as error:
        repair_loop(project, ReplayProvider([]), **{'mode': 'trusted-native', **options})
    assert error.value.code == code
    assert not (project.control / 'sessions').exists()


@pytest.mark.parametrize('exception', [OSError, KeyboardInterrupt, SystemExit])
def test_initial_loop_evaluation_failure_finalizes_session(project, monkeypatch, exception):
    def evaluate(**kwargs):
        raise exception('Injected initial evaluation failure')
    monkeypatch.setattr(project, 'evaluate', evaluate)
    provider = ReplayProvider([])
    if issubclass(exception, Exception):
        state = repair_loop(project, provider, mode='trusted-native')
        assert state['status'] == 'LOOP_ERROR'
    else:
        with pytest.raises(exception):
            repair_loop(project, provider, mode='trusted-native')
    saved = read_json(project.control / 'sessions/loop.json')
    assert saved['status'] == ('LOOP_ERROR' if issubclass(exception, Exception) else 'INTERRUPTED')
    assert saved['final_feedback'] is None
    assert saved['steps'] == [] and provider.calls == 0
    assert saved['error'] == 'Injected initial evaluation failure'
    project.propose({'base_revision': project.revision(), 'parameters': {'gap_mm': 10},
                     'reason': 'Controller lock is released after loop initialization fails'})


@pytest.mark.integration
def test_failed_fresh_cad_worker_restores_starting_design(project, monkeypatch):
    import cadloop.project as project_module
    before = project.parameters()
    actual_run_stage = project_module.run_stage
    builds = 0
    def run_stage(stage, run, **kwargs):
        nonlocal builds
        if stage == 'build':
            builds += 1
            if builds == 2:
                return {'stage': stage, 'exit_code': -9, 'timed_out': True}
        return actual_run_stage(stage, run, **kwargs)
    monkeypatch.setattr(project_module, 'run_stage', run_stage)
    searched = search_parameter(project, 'gap_mm', [12], mode='trusted-native',
                                fixed={'include_spacer': True})
    assert searched['status'] == 'FINAL_VALIDATION_FAILED'
    assert searched['attempts'][0]['status'] == 'GEOMETRY_ACCEPTED'
    assert project.parameters() == before and builds == 3
    assert not searched['final']['task_accepted']
    assert searched['restored_final']['revision'] == project.revision()
    assert project.latest()[1]['revision'] == project.revision()
