import json
from pathlib import Path
import pytest
from cadloop.errors import CadLoopError
from cadloop.contracts import Proposal
from cadloop.util import write_json, read_json
from cadloop.execution import docker_command


def patch(project,**parameters):
    return project.propose({'base_revision':project.revision(),'parameters':parameters,'reason':'Test transaction'})


def test_stale_proposal(project):
    revision=project.revision();patch(project,gap_mm=10)
    with pytest.raises(CadLoopError) as e:
        project.propose({'base_revision':revision,'parameters':{'gap_mm':12},'reason':'stale'})
    assert e.value.code=='STALE_REVISION'


def test_requirements_are_protected(project):
    p=project.root/'requirements.json';data=read_json(p);data['checks']=data['checks'][:1];write_json(p,data)
    with pytest.raises(CadLoopError) as e: project.revision()
    assert e.value.code=='REQUIREMENTS_CHANGED'


def test_parameter_bounds_preserve_working_copy(project):
    old=project.parameters()
    with pytest.raises(ValueError): patch(project,gap_mm=1000)
    assert project.parameters()==old


def test_source_patch_requires_unique_match(project):
    old=project.revision()
    with pytest.raises(CadLoopError) as e:
        project.propose({'base_revision':old,'edits':[{'path':'model.py','old':'not present','new':'x'}],'reason':'test'})
    assert e.value.code=='EDIT_AMBIGUOUS'
    assert project.revision()==old


def test_bad_source_syntax_rolls_back(project):
    old=project.revision()
    with pytest.raises(SyntaxError):
        project.propose({'base_revision':old,'edits':[{'path':'model.py','old':'def build(p):','new':'def build(p)'}],'reason':'test'})
    assert project.revision()==old


def test_source_patch_cannot_target_requirements(project):
    with pytest.raises(CadLoopError):
        project.propose({'base_revision':project.revision(),'edits':[{'path':'../requirements.json','old':'mm','new':'inch'}],'reason':'test'})


def test_successful_local_source_patch(project):
    old=project.revision()
    result=project.propose({'base_revision':old,'edits':[{'path':'model.py','old':'def spacer(length):','new':'def spacer(length):\n    # Reviewed local edit.'}],'reason':'test'})
    assert result['revision']!=old
    assert '# Reviewed local edit.' in (project.design/'model.py').read_text()


def test_no_silent_native_fallback(project):
    with pytest.raises(CadLoopError): project.evaluate(mode='')


def test_docker_contract_has_readonly_and_no_network(tmp_path):
    cmd=docker_command('build',tmp_path,'cadloop-worker:0.1.0','test')
    assert '--network=none' in cmd and '--read-only' in cmd and '--cap-drop=ALL' in cmd
    assert any('dst=/input,readonly' in s for s in cmd)
    assert not any('API_KEY' in s for s in cmd)
    check=docker_command('verify',tmp_path,'cadloop-worker:0.1.0','test')
    assert any('dst=/geometry,readonly' in s for s in check)

@pytest.mark.integration
def test_failed_then_fixed_and_cached(project):
    failed=project.evaluate(mode='trusted-native',render=False)
    assert not failed['geometry_accepted'] and 'plate_gap' in failed['blocker_ids']
    patch(project,gap_mm=12,include_spacer=True)
    passed=project.evaluate(mode='trusted-native',render=False)
    assert passed['geometry_accepted'] and passed['summary']['indeterminate']==0
    cached=project.evaluate(mode='trusted-native',render=False)
    assert cached['cached'] and cached['run_id']==passed['run_id']
    assert not passed['engineering_approved']

@pytest.mark.integration
def test_tampered_geometry_does_not_hit_cache(project):
    r=project.evaluate(mode='trusted-native',render=False)
    p=Path(r['run_directory'])/'geometry/parts/lower_plate.brep'
    with p.open('a') as f:f.write('\ntamper')
    with pytest.raises(CadLoopError) as e: project.evaluate(mode='trusted-native',render=False)
    assert e.value.code=='ARTIFACT_TAMPERED'

@pytest.mark.integration
def test_forged_report_is_rejected(project):
    r=project.evaluate(mode='trusted-native',render=False)
    p=Path(r['run_directory'])/'verification/report.json'
    data=read_json(p);data['geometry_accepted']=True;write_json(p,data)
    with pytest.raises(CadLoopError): project.latest()

@pytest.mark.integration
def test_stale_geometry_cannot_be_inspected_as_current(project):
    project.evaluate(mode='trusted-native',render=False)
    patch(project,gap_mm=10)
    with pytest.raises(CadLoopError) as e: project.inspect(part='lower_plate')
    assert e.value.code=='STALE_REVISION'

@pytest.mark.integration
def test_invalid_script_fails_closed(project):
    (project.design/'model.py').write_text('raise RuntimeError("Intentional fixture error")\n')
    r=project.evaluate(mode='trusted-native',render=False)
    assert not r['geometry_accepted']
    assert r['blockers'][0]['code']=='BUILD_FAILED'
    assert set(c.id for c in project.requirements().checks).issubset(set(r['blocker_ids']))

@pytest.mark.integration
def test_timeout_fails_closed(project):
    (project.design/'model.py').write_text('import time\ntime.sleep(30)\n')
    r=project.evaluate(mode='trusted-native',timeout=.2,render=False)
    assert not r['geometry_accepted'] and r['blockers'][0]['code']=='BUILD_TIMEOUT'

@pytest.mark.integration
def test_api_secret_not_forwarded_to_worker(project,monkeypatch):
    monkeypatch.setenv('CADLOOP_TEST_SECRET','do-not-forward')
    code=(project.design/'model.py').read_text()
    (project.design/'model.py').write_text('import os\nassert "CADLOOP_TEST_SECRET" not in os.environ\n'+code.replace('"""Synthetic','"""Synthetic',1))
    r=project.evaluate(mode='trusted-native',render=False)
    assert r['blockers'][0]['code']!='BUILD_FAILED'


def test_new_project_from_reviewed_source(project,tmp_path):
    from cadloop.project import Project
    p=Project.create(tmp_path/'custom',requirements=project.root/'requirements.json',design_dir=project.design)
    assert p.parameters()==project.parameters()
    assert p.requirements().name==project.requirements().name


def test_custom_project_cannot_overwrite(project,tmp_path):
    from cadloop.project import Project
    p=tmp_path/'occupied';p.mkdir();(p/'keep.txt').write_text('keep')
    with pytest.raises(CadLoopError):
        Project.create(p,requirements=project.root/'requirements.json',design_dir=project.design)
    assert (p/'keep.txt').read_text()=='keep'


def test_custom_project_cannot_recurse_into_source(project):
    from cadloop.project import Project
    with pytest.raises(CadLoopError):
        Project.create(project.design/'nested',requirements=project.root/'requirements.json',design_dir=project.design)
