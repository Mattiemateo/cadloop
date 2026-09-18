"""Atomicity and cross-controller tests, independent of inference providers."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import pytest
from cadloop.util import project_lock,tree_hashes,read_json
from cadloop.project import Project
from cadloop.errors import CadLoopError
from cadloop.budget import Budget
from cadloop.contracts import Requirements
from cadloop.checks import required_check_ids,result
from cadloop.worker import make_report


def test_nested_lock_is_reentrant_but_other_thread_cannot_enter(tmp_path):
    def contender():
        try:
            with project_lock(tmp_path): return 'incorrectly_acquired'
        except CadLoopError as e: return e.code
    with project_lock(tmp_path),project_lock(tmp_path):
        with ThreadPoolExecutor(1) as pool:
            assert pool.submit(contender).result()=='PROJECT_BUSY'
    assert contender()=='incorrectly_acquired'  # It is available after both releases.


def test_lock_is_respected_by_a_separate_process(tmp_path):
    code='from pathlib import Path\nfrom cadloop.util import project_lock\nfrom cadloop.errors import CadLoopError\ntry:\n with project_lock(Path('+repr(str(tmp_path))+')): print("acquired")\nexcept CadLoopError as e: print(e.code)\n'
    with project_lock(tmp_path):
        r=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,check=True)
        assert r.stdout.strip()=='PROJECT_BUSY'
    r=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,check=True)
    assert r.stdout.strip()=='acquired'


def test_multiple_edits_fail_atomically(project):
    before=tree_hashes(project.design)
    with pytest.raises(CadLoopError):
        project.propose({'base_revision':project.revision(),'parameters':{'gap_mm':12},'edits':[
            {'path':'model.py','old':'def build(p):','new':'def build(p):\n    # First edit'},
            {'path':'model.py','old':'certainly absent token','new':'x'}], 'reason':'Atomic multi-edit'})
    assert tree_hashes(project.design)==before


def test_budget_reservations_are_serialized(tmp_path):
    b=Budget(tmp_path/'b.json',cap_usd=1,input_per_million=1,output_per_million=1)
    def attempt(_):
        try: return 'reserved',b.reserve(100,100)
        except CadLoopError as e: return e.code,None
    with ThreadPoolExecutor(8) as pool:
        r=list(pool.map(attempt,range(16)))
    assert sum(status=='reserved' for status,_ in r)==1
    assert len(read_json(b.path)['requests'])==1
    assert set(status for status,_ in r) <= {'reserved','PROJECT_BUSY','BUDGET_UNCERTAIN'}


def test_required_automatic_ids_are_not_optional(requirements):
    ids=required_check_ids(requirements)
    all_checks=[result(id,'pass','OK','Synthetic coverage fixture') for id in ids]
    assert make_report('a'*64,requirements,all_checks)['geometry_accepted']
    for missing in ids:
        report=make_report('a'*64,requirements,[c for c in all_checks if c['id']!=missing])
        assert not report['geometry_accepted'],missing
        assert any(missing in c['evidence'].get('missing',[]) for c in report['checks'])


def test_automatic_pair_id_collision_rejected(requirements):
    d=requirements.model_dump()
    d.update(expected_parts=['a_b','c','a','b_c'],refs={},checks=[{
        'id':'size','kind':'dimension','part':'a','axis':'x','minimum':1,'maximum':2,'description':'extent'}])
    with pytest.raises(ValueError,match='ambiguous'):
        Requirements.model_validate(d)
