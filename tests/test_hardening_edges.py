import json
import math
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from cadloop.project import Project
from cadloop.errors import CadLoopError
from cadloop.util import read_json,write_json,tree_hashes,strict_loads
from cadloop.search import search_parameter
from cadloop.execution import run_stage
from cadloop.loop import ChatProvider,ProviderConfig
from cadloop.cli import pairs,main


def config():
    return ProviderConfig(base_url='http://localhost:8080/v1',model='mock',api_key_env=None,
        pricing_confirmed=True,budget_usd=1,input_per_million_usd=1,output_per_million_usd=1)


@pytest.mark.parametrize('content',['{"kind":"finish","kind":"stop"}', '{"kind":"propose", "proposal":null}', 'not JSON', None])
def test_invalid_provider_action_is_accounted_and_rejected(tmp_path,content):
    import httpx
    def handler(_):
        return httpx.Response(200,json={'choices':[{'message':{'content':content}}],
                                       'usage':{'prompt_tokens':10,'completion_tokens':5}})
    p=ChatProvider(config(),tmp_path/'budget.json',transport=httpx.MockTransport(handler))
    with pytest.raises(CadLoopError) as e: p.next_action({'revision':'a'*64})
    assert e.value.code=='ACTION_INVALID'
    assert not p.usage()['uncertain'] and float(p.usage()['booked_usd'])>0


@pytest.mark.parametrize('usage',[None,{}, {'prompt_tokens':True,'completion_tokens':1},
                                 {'prompt_tokens':2,'completion_tokens':-1}])
def test_bad_usage_never_authorizes_another_request(tmp_path,usage):
    import httpx
    def handler(_):
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"kind":"stop"}'}}],'usage':usage})
    p=ChatProvider(config(),tmp_path/'budget.json',transport=httpx.MockTransport(handler))
    with pytest.raises(CadLoopError): p.next_action({'revision':'a'*64})
    assert p.usage()['blocked']
    with pytest.raises(CadLoopError): p.next_action({'revision':'a'*64})
    assert p.usage()['request_count']==1


def test_duplicate_cli_sets_are_not_silently_overwritten():
    with pytest.raises(CadLoopError) as e: pairs(['gap_mm=8','gap_mm=12'])
    assert e.value.code=='DUPLICATE_SET'


@pytest.mark.parametrize('timeout',[0,-1,math.inf,math.nan,301])
def test_invalid_timeout_rejected_even_before_build(project,timeout):
    with pytest.raises(CadLoopError) as e: project.evaluate(mode='trusted-native',timeout=timeout)
    assert e.value.code=='INVALID_TIMEOUT'


def test_search_deduplicates_and_restores_base(project,monkeypatch):
    before=project.parameters()
    calls=[]
    def evaluate(**kw):
        calls.append(project.parameters())
        return {'geometry_accepted':False,'run_id':'mock','revision':project.revision(),
                'status':'REPAIR_REQUIRED','summary':{},'blocker_ids':['plate_gap']}
    monkeypatch.setattr(project,'evaluate',evaluate)
    r=search_parameter(project,'gap_mm',[8,8.,10,10],mode='trusted-native',fixed={'include_spacer':True})
    assert len(r['attempts'])==2 and len(calls)==3
    assert project.parameters()==before


def test_search_interrupt_rolls_back_and_unlocks(project,monkeypatch):
    before=project.parameters()
    def stop(**kwargs): raise KeyboardInterrupt('test cancellation')
    monkeypatch.setattr(project,'evaluate',stop)
    with pytest.raises(KeyboardInterrupt): search_parameter(project,'gap_mm',[12],mode='trusted-native')
    assert project.parameters()==before
    project.propose({'base_revision':project.revision(),'parameters':{'gap_mm':10},'reason':'Lock is released'})


def test_other_controller_cannot_modify_search_mid_run(project,monkeypatch):
    contender=Project(project.root)
    statuses=[]
    def mutate():
        try:
            contender.propose({'base_revision':contender.revision(),'parameters':{'gap_mm':13},'reason':'Competing edit'})
        except CadLoopError as e: return e.code
        return 'incorrectly_changed'
    def evaluate(**kw):
        with ThreadPoolExecutor(1) as executor: statuses.append(executor.submit(mutate).result())
        return {'geometry_accepted':False,'run_id':'mock','revision':project.revision(),
                'status':'REPAIR_REQUIRED','summary':{},'blocker_ids':['plate_gap']}
    monkeypatch.setattr(project,'evaluate',evaluate)
    search_parameter(project,'gap_mm',[10],mode='trusted-native')
    assert statuses and all(s=='PROJECT_BUSY' for s in statuses)


def test_failed_final_search_sets_nonzero_cli_exit(project,monkeypatch,capsys):
    monkeypatch.setattr('cadloop.search.search_parameter',lambda *a,**kw:{'status':'FINAL_VALIDATION_FAILED'})
    code=main(['search-parameter',str(project.root),'gap_mm','--values','[12]','--trusted-native'])
    assert code==2
    assert json.loads(capsys.readouterr().out)['status']=='FINAL_VALIDATION_FAILED'


@pytest.mark.integration
def test_preview_worker_failure_does_not_erase_geometry_acceptance(project,monkeypatch):
    import cadloop.project as module
    real=module.run_stage
    def run(stage,run,**kwargs):
        if stage=='render':
            return {'stage':'render','mode':'trusted-native','exit_code':-11,'timed_out':False,
                    'stderr_tail':'Injected renderer crash','sandboxed':False}
        return real(stage,run,**kwargs)
    monkeypatch.setattr(module,'run_stage',run)
    project.propose({'base_revision':project.revision(),'parameters':{'gap_mm':12,'include_spacer':True},'reason':'Reviewed fixture'})
    r=project.evaluate(mode='trusted-native',render=True)
    assert r['geometry_accepted']
    error=read_json(Path(r['run_directory'])/'view_error.json')
    assert error['code']=='VIEW_FAILED'
    project.latest()  # Entire result, including preview failure, has a sound receipt.


@pytest.mark.integration
def test_render_only_checkpoint_launches_no_geometry_workers(project,monkeypatch):
    import cadloop.project as module
    project.propose({'base_revision':project.revision(),'parameters':{'gap_mm':12,'include_spacer':True},'reason':'Reviewed fixture'})
    a=project.evaluate(mode='trusted-native',render=False)
    old=tree_hashes(Path(a['run_directory']))
    real=module.run_stage
    called=[]
    def run(stage,*args,**kw):
        called.append(stage)
        assert stage=='render'
        return real(stage,*args,**kw)
    monkeypatch.setattr(module,'run_stage',run)
    b=project.evaluate(mode='trusted-native',render=True)
    assert b['cached'] and called==['render'] and b['run_id']!=a['run_id']
    assert tree_hashes(Path(a['run_directory']))==old
    assert (Path(b['run_directory'])/'report.html').is_file()
    project.latest()


@pytest.mark.integration
def test_worker_signal_death_fails_closed(project):
    (project.design/'model.py').write_text('import os,signal\nos.kill(os.getpid(),signal.SIGSEGV)\n')
    r=project.evaluate(mode='trusted-native',render=False)
    assert not r['geometry_accepted']
    assert r['blockers'][0]['code']=='BUILD_FAILED'
    assert r['blockers'][0]['measurement']['execution']['exit_code']<0
