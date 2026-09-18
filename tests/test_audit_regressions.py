"""Adversarial regressions discovered in the v0.1.0 hardening audit."""
import math
from pathlib import Path
import pytest
import cadquery as cq
from cadloop import kernel as k
from cadloop.checks import interval, result
from cadloop.worker import build, verify, make_report
from cadloop.util import read_json, write_json
from cadloop.errors import CadLoopError
from cadloop.budget import Budget


def repaired(project):
    project.propose({'base_revision':project.revision(),
                     'parameters': {'gap_mm':12,'include_spacer':True}, 'reason':'Reviewed fixture repair'})


@pytest.mark.parametrize('name', ['assembly.brep', 'assembly.step'])
def test_export_cannot_hide_free_face(project, tmp_path, name):
    repaired(project)
    write_json(project.root / 'meta.json', {'revision':project.revision()})
    geometry, output = tmp_path/'geometry', tmp_path/'verify'
    build(project.root, geometry)
    assembly = k.read_brep(geometry/'assembly.brep')
    sheet = cq.Solid.makeBox(2,2,1,cq.Vector(100,0,0)).Faces()[0].wrapped
    polluted = k.compound([assembly, sheet])
    (k.write_brep if name.endswith('brep') else k.write_step)(polluted, geometry/name)
    report = verify(project.root, geometry, output)
    c = next(c for c in report['checks'] if c['id']=='AUTO_export_'+name.replace('.','_'))
    assert c['status'] != 'pass', 'Deliverable contains an extra non-solid face, yet export verification passed'
    assert not report['geometry_accepted']


def test_report_requires_automatic_checks(requirements):
    checks = [result(c.id,'pass','OK',c.description) for c in requirements.checks]
    assert not make_report('a'*64, requirements, checks)['geometry_accepted']


def test_report_rejects_duplicate_check_ids(requirements):
    checks = [result(c.id,'pass','OK',c.description) for c in requirements.checks]
    checks.append(checks[0].copy())
    assert not make_report('a'*64, requirements, checks)['geometry_accepted']


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_measurement_never_passes_interval(value):
    assert interval(value, None, None, 1e-6) != 'pass'


@pytest.mark.parametrize('text', ['{"x":1,"x":2}', '{"x":1e999}', '{"nested":{"x":1,"x":2}}'])
def test_json_rejects_ambiguous_or_nonfinite_values(tmp_path, text):
    path=tmp_path/'input.json'; path.write_text(text)
    with pytest.raises((ValueError,CadLoopError)):
        read_json(path)


def test_pending_reservation_blocks_new_reservation(tmp_path):
    b = Budget(tmp_path/'budget.json',cap_usd=1,input_per_million=1,output_per_million=1)
    b.reserve(10,10)
    with pytest.raises(CadLoopError) as e:
        b.reserve(10,10)
    assert e.value.code=='BUDGET_UNCERTAIN'


@pytest.mark.integration
def test_native_cache_cannot_satisfy_docker_request(project):
    repaired(project)
    r=project.evaluate(mode='trusted-native',render=False)
    assert r['geometry_accepted']
    r=project.evaluate(mode='docker',render=False)
    assert not r['cached'], 'A native run was silently used instead of Docker'


@pytest.mark.integration
def test_requesting_render_after_no_render_creates_views(project):
    repaired(project)
    r=project.evaluate(mode='trusted-native',render=False)
    assert r['geometry_accepted']
    r=project.evaluate(mode='trusted-native',render=True)
    assert (Path(r['run_directory'])/'views/overview.png').is_file()
    project.latest()  # New views must be covered by a valid receipt.


@pytest.mark.integration
def test_timed_out_evaluation_does_not_poison_cache(project):
    repaired(project)
    r=project.evaluate(mode='trusted-native',render=False,timeout=.001)
    assert not r['geometry_accepted']
    r=project.evaluate(mode='trusted-native',render=False,timeout=45)
    assert not r['cached']
    assert r['geometry_accepted']


def test_oversize_proposal_does_not_commit_broken_working_copy(project):
    from cadloop.util import tree_hashes
    size=sum(p.stat().st_size for p in project.design.iterdir() if p.is_file())
    (project.design/'padding.py').write_text('#'+'x'*(499000-size-2)+'\n')
    before=tree_hashes(project.design)
    with pytest.raises(CadLoopError) as e:
        project.propose({'base_revision':project.revision(),
                         'edits':[{'path':'model.py','old':'def build(p):',
                                   'new':'#'+'x'*4000+'\ndef build(p):'}],
                         'reason':'Proposal crossing source budget must be atomic'})
    assert e.value.code=='SOURCE_TOO_LARGE'
    assert tree_hashes(project.design)==before


def test_search_does_not_claim_success_when_fresh_validation_fails(tmp_path):
    from cadloop.search import search_parameter
    class FakeProject:
        def __init__(self):
            self.calls=0; self.p={'gap':1}; self.control=tmp_path/'control'
        def parameters(self): return dict(self.p)
        def requirements(self): return self
        def validate_parameters(self,p): pass
        def revision(self): return 'a'*64
        def propose(self,p): self.p.update(p['parameters'])
        def evaluate(self,**kwargs):
            self.calls+=1; good=self.calls==1
            return {'geometry_accepted':good,'revision':'a'*64,'run_id':'fake',
                    'status':'GEOMETRY_ACCEPTED' if good else 'REPAIR_REQUIRED',
                    'summary':{'pass':1 if good else 0, 'fail':0 if good else 1},
                    'blocker_ids':[] if good else ['nondeterministic_build']}
        def event(self,*args): pass
    p=FakeProject()
    r=search_parameter(p,'gap',[2],mode='trusted-native')
    assert r['status']!='FEASIBLE_CANDIDATE_FOUND'
    assert r['value'] is None
