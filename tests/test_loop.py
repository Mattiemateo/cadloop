from pathlib import Path
import json
import pytest
from cadloop.budget import Budget
from cadloop.loop import ChatProvider,ProviderConfig,ReplayProvider,repair_loop
from cadloop.errors import CadLoopError
from cadloop.util import read_json


def config(**kw):
    return ProviderConfig(base_url='http://127.0.0.1:8080/v1',model='test-model',api_key_env=None,
                          input_per_million_usd=1,output_per_million_usd=2,budget_usd=.5,
                          pricing_confirmed=True,**kw)


def test_budget_reserves_before_request_and_reconciles(tmp_path):
    b=Budget(tmp_path/'usage.json',cap_usd=.02,input_per_million=1,output_per_million=2)
    rid=b.reserve(10000,2000)
    assert str(b.booked())=='0.014000'
    b.reconcile(rid,1000,500)
    assert float(b.booked())==pytest.approx(.002)


def test_exhausted_budget_prevents_call(tmp_path):
    b=Budget(tmp_path/'usage.json',cap_usd=.001,input_per_million=1,output_per_million=2)
    with pytest.raises(CadLoopError) as e:b.reserve(10000,2000)
    assert e.value.code=='BUDGET_EXHAUSTED' and b.summary()['request_count']==0


def test_uncertain_charge_not_refunded(tmp_path):
    b=Budget(tmp_path/'usage.json',cap_usd=.02,input_per_million=1,output_per_million=2)
    rid=b.reserve(10000,2000);before=b.booked();b.uncertain(rid)
    assert before==b.booked()
    with pytest.raises(CadLoopError):b.reserve(1,1)


def test_usage_bound_violation_stops_session(tmp_path):
    b=Budget(tmp_path/'usage.json',cap_usd=.02,input_per_million=1,output_per_million=2)
    rid=b.reserve(1000,200)
    with pytest.raises(CadLoopError):b.reconcile(rid,1001,200)
    assert b.summary()['blocked']


def test_provider_uses_json_and_accounts_usage(tmp_path):
    import httpx
    def handler(request):
        body=json.loads(request.content)
        assert body['max_completion_tokens']==2048
        assert body['response_format']=={'type':'json_object'}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'kind':'stop','reason':'test'})}}],
                                       'usage':{'prompt_tokens':100,'completion_tokens':40}})
    p=ChatProvider(config(),tmp_path/'ledger.json',transport=httpx.MockTransport(handler))
    a=p.next_action({'revision':'a'*64})
    assert a.kind=='stop' and p.usage()['request_count']==1 and not p.usage()['uncertain']


def test_provider_failure_retains_reservation(tmp_path):
    import httpx
    p=ChatProvider(config(),tmp_path/'ledger.json',transport=httpx.MockTransport(lambda r:httpx.Response(503)))
    with pytest.raises(CadLoopError):p.next_action({'revision':'a'*64})
    assert p.usage()['uncertain'] and float(p.usage()['booked_usd'])>0


def test_unconfirmed_prices_block_network(tmp_path):
    c=config();c.pricing_confirmed=False
    with pytest.raises(CadLoopError):ChatProvider(c,tmp_path/'x.json')


def test_source_edit_loop_requires_docker(project):
    with pytest.raises(CadLoopError) as e:
        repair_loop(project,ReplayProvider([]),mode='trusted-native',allow_source_edits=True)
    assert e.value.code=='SANDBOX_REQUIRED'

@pytest.mark.integration
def test_replay_runs_real_geometry_not_a_fake_checker(project):
    provider=ReplayProvider([{'kind':'propose','proposal':{'base_revision':'$CURRENT_REVISION',
            'parameters':{'gap_mm':12,'include_spacer':True},'reason':'Known fixture repair'}}])
    r=repair_loop(project,provider,mode='trusted-native')
    assert r['status']=='GEOMETRY_ACCEPTED'
    assert r['final_feedback']['exported']
    assert r['usage']['model_api_calls']==0 and r['usage']['simulated_inference']

@pytest.mark.optional
def test_build123d_authoring_optional(tmp_path):
    pytest.importorskip('build123d')
    from cadloop.project import Project
    p=Project.initialize(tmp_path/'b3d',backend='build123d')
    p.propose({'base_revision':p.revision(),'parameters':{'gap_mm':12,'include_spacer':True},'reason':'Optional backend check'})
    r=p.evaluate(mode='trusted-native',render=False)
    assert r['geometry_accepted']
