import json
from pathlib import Path
import pytest
from cadloop.errors import CadLoopError
from cadloop.planning.store import PlanningProject
from cadloop.project import Project
from cadloop.util import digest, file_hash, package_digest, read_json, versions, write_json
from planning_helpers import proposal


def prepared(tmp_path):
    workspace = PlanningProject.initialize(tmp_path / 'plan', brief='Make a removable mount for a 42 mm synthetic motor')
    packet = proposal(workspace)
    packet['contract']['parameters'].append({'id':'motor_width','name':'Motor width','kind':'number',
        'mode':'FIXED','unit':'mm','value':42.0,'impact':'CRITICAL','source_refs':['src_user_1']})
    packet['contract']['verification_intent']=[{'id':'motor_width_check','text':'Preserve supplied motor width',
        'kind':'dimension','axis':'x','component_refs':['motor'],'parameter_refs':['motor_width'],
        'geometry_required':True}]
    state=workspace.propose(packet)
    state=workspace.answer(base=state['revision'],answers=[('orientation_question','outward')])
    workspace.render()
    state=workspace.freeze(base=state['revision'])
    design=tmp_path/'source';design.mkdir()
    write_json(design/'parameters.json',{'motor_width':42.0})
    (design/'model.py').write_text('''import cadquery as cq
from cadloop.authoring import Scene

def build(p):
    scene = Scene()
    scene.add("motor", cq.Workplane("XY").box(p["motor_width"], 42, 42).val())
    scene.add("mount", cq.Workplane("XY").box(10, 10, 10).val().translate((100, 0, 0)))
    return scene
''')
    return workspace,state,design


def materialized(tmp_path):
    workspace,state,design=prepared(tmp_path)
    result=workspace.materialize(base=state['revision'],design_dir=design)
    return workspace,Project(workspace.root),result,design


def test_legacy_revision_payload_is_unchanged(project):
    from cadloop.util import tree_hashes
    expected=digest({'design':tree_hashes(project.design),'requirements':file_hash(project.root/'requirements.json'),
                     'environment':versions(),'controller':package_digest()})
    assert project.revision()==expected
    assert project.planning_provenance() is None
    assert 'planning' not in project.state()


def test_materialization_attaches_frozen_intent(tmp_path):
    workspace,project,result,design=materialized(tmp_path)
    assert result['status']=='MATERIALIZED'
    binding=project.planning_provenance()
    assert binding['design_contract_hash']==workspace.state()['contract_hash']
    assert binding['design_contract_revision']==workspace.state()['revision']
    assert project.state()['planning']['current'] is True
    assert read_json(project.control/'anchor.json')['planning']==binding


@pytest.mark.integration
def test_planned_cad_build_finish_provenance_and_reopen_staleness(tmp_path):
    workspace,project,result,design=materialized(tmp_path)
    final=project.finish(mode='trusted-native',timeout=60)
    assert final['geometry_accepted'] and final['exported']
    assert final['design_contract_hash']==result['design_contract_hash']
    export=Path(final['export_directory'])
    assert read_json(export/'export_manifest.json')['design_contract_hash']==result['design_contract_hash']
    assert read_json(export/'input/meta.json')['design_contract_revision']==result['design_contract_revision']
    assert digest(read_json(export/'input/design_contract.json'))==result['design_contract_hash']
    cad_revision=project.revision()
    workspace.reopen(base=workspace.state()['revision'],reason='User revises intent')
    assert project.revision()==cad_revision  # Never relabel old CAD as new intent.
    assert project.state()['planning']['current'] is False
    assert project.state()['latest_is_current'] is False
    for action in [lambda: project.evaluate(mode='trusted-native',render=False),
                   lambda: project.finish(mode='trusted-native'),
                   lambda: project.propose({'base_revision':cad_revision,'parameters':{'motor_width':42},'reason':'Try stale CAD'}),
                   lambda: project.latest()]:
        with pytest.raises(CadLoopError) as exc: action()
        assert exc.value.code=='PLANNING_STALE'
    assert read_json(export/'export_manifest.json')['design_contract_hash']==result['design_contract_hash']


def test_materialization_is_not_available_before_freeze(tmp_path):
    workspace=PlanningProject.initialize(tmp_path/'plan',brief='Make a mount')
    with pytest.raises(CadLoopError) as exc:
        workspace.materialize(base=workspace.state()['revision'],design_dir=tmp_path/'missing')
    assert exc.value.code=='PLANNING_NOT_FROZEN'
    assert not (workspace.control/'anchor.json').exists()


def test_existing_cad_cannot_be_rebound_or_overwritten(tmp_path):
    workspace,project,result,design=materialized(tmp_path)
    before=project.revision()
    with pytest.raises(CadLoopError) as exc:
        workspace.materialize(base=workspace.state()['revision'],design_dir=design)
    assert exc.value.code=='PLANNING_ALREADY_MATERIALIZED'
    assert project.revision()==before


@pytest.mark.parametrize('change', ['check', 'bounds', 'blocker', 'tolerance', 'overlap'])
def test_reviewed_requirements_cannot_weaken_compiled_intent(tmp_path, change):
    workspace,state,design=prepared(tmp_path)
    data=workspace.handoff()['requirements_adapter']['requirements']
    if change=='check': data['checks'][0]['minimum']=40.0
    elif change=='bounds': data['parameters']['motor_width']['minimum']=40.0
    elif change=='blocker': data['engineering_blockers']=['Unreviewed engineering']
    elif change=='tolerance': data['numerical_mm']*=2
    else: data['max_overlap_mm3']*=2
    path=tmp_path/'weaker.json';write_json(path,data)
    with pytest.raises(CadLoopError) as exc:
        workspace.materialize(base=state['revision'],design_dir=design,requirements=path)
    assert exc.value.code=='PLANNING_REQUIREMENTS_MISMATCH'
    assert not (workspace.root/'design').exists()
    assert not (workspace.control/'anchor.json').exists()


def test_materialization_failure_leaves_planning_workspace_intact(tmp_path, monkeypatch):
    workspace,state,design=prepared(tmp_path)
    from cadloop.util import tree_hashes
    before=tree_hashes(workspace.root)
    import cadloop.planning.store as store
    real_write=store.write_json
    def fail_anchor(path,data):
        if path==workspace.control/'anchor.json': raise OSError('Simulated import failure')
        return real_write(path,data)
    monkeypatch.setattr(store,'write_json',fail_anchor)
    with pytest.raises(OSError): workspace.materialize(base=state['revision'],design_dir=design)
    assert tree_hashes(workspace.root)==before
    assert workspace.state()['status']=='FROZEN'


@pytest.mark.parametrize('commit_first', [False, True])
def test_killed_materialization_recovers_committed_or_empty_workspace(tmp_path, commit_first):
    import subprocess
    import sys
    workspace,state,design=prepared(tmp_path)
    code='''
import os, sys
from cadloop.planning.store import PlanningProject
import cadloop.planning.store as store
plan=PlanningProject(sys.argv[1])
real_write=store.write_json
def interrupted(path,value):
    if path==plan.control/'anchor.json':
        if sys.argv[4]=='after': real_write(path,value)
        os._exit(92)
    return real_write(path,value)
store.write_json=interrupted
plan.materialize(base=sys.argv[2],design_dir=sys.argv[3])
'''
    result=subprocess.run([sys.executable,'-c',code,str(workspace.root),state['revision'],str(design),
                           'after' if commit_first else 'before'],capture_output=True,text=True)
    assert result.returncode==92,result.stderr
    assert (workspace.folder/'materialization.json').exists()
    assert workspace.state()['status']=='FROZEN'
    assert not (workspace.folder/'materialization.json').exists()
    assert not list(workspace.folder.glob('materialize-*'))
    if commit_first:
        assert Project(workspace.root).planning_provenance()['design_contract_revision']==state['revision']
    else:
        assert not (workspace.root/'design').exists()
        assert not (workspace.root/'requirements.json').exists()
        assert not (workspace.control/'anchor.json').exists()
        assert workspace.materialize(base=state['revision'],design_dir=design)['status']=='MATERIALIZED'
