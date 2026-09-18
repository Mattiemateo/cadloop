import json
from pathlib import Path
from unittest.mock import patch
import pytest
from cadloop import kernel as k
from cadloop.checks import GeometryQueries,run_checks,required_check_ids,result
from cadloop.worker import make_report
from cadloop.feedback import compact,progress_key
from cadloop.loop import context
from cadloop.errors import CadLoopError
from cadloop.util import canonical,tree_hashes


def report_for(parts,req):
    checks=run_checks(parts,req)
    checks += [result('AUTO_export_assembly_'+ext,'pass','OK','Export fixture') for ext in ('step','brep')]
    return make_report('a'*64,req,checks)


def test_query_cache_changes_no_check_evidence(requirements,model,good_parameters):
    parts=model.build(good_parameters).parts
    with patch.object(k,'cylinders',wraps=k.cylinders) as cached:
        a=run_checks(parts,requirements)
        cached_calls=cached.call_count
    with patch.object(GeometryQueries,'_get',lambda self,key,compute:compute()):
        with patch.object(k,'cylinders',wraps=k.cylinders) as uncached:
            b=run_checks(parts,requirements)
            uncached_calls=uncached.call_count
    assert a==b
    assert cached_calls==len(parts)
    assert uncached_calls>cached_calls


def test_cache_is_not_shared_across_rebuilds(requirements,model,good_parameters):
    assert all(c['status']=='pass' for c in run_checks(model.build(good_parameters).parts,requirements))
    good_parameters['bore_diameter_mm']=9
    r=run_checks(model.build(good_parameters).parts,requirements)
    assert next(c for c in r if c['id']=='lower_holes')['status']=='fail'


def test_hole_failure_packet_contains_measured_diameter(requirements,model,good_parameters):
    good_parameters['bore_diameter_mm']=9
    packet=compact(report_for(model.build(good_parameters).parts,requirements))
    evidence=next(c for c in packet['blockers'] if c['id']=='lower_holes')['measurement']
    assert any(h['radius_mm']==pytest.approx(4.5) for h in evidence['observed_holes'])
    assert evidence['expected_hole_count']==5


def test_blocker_details_prioritize_actionable_failures():
    checks=[result('dependency_'+str(i),'indeterminate','DEPENDENCY_INVALID','missing upstream') for i in range(10)]
    checks.append(result('actual_fault','fail','DIMENSION_OUT_OF_RANGE','wrong thickness',{'measured_mm':4,'range_mm':[5,6]}))
    report={'checks':checks,'revision':'a'*64,'status':'REPAIR_REQUIRED','geometry_accepted':False,
            'summary':{},'engineering_blockers':[]}
    packet=compact(report,detail_limit=2)
    assert packet['blockers'][0]['id']=='actual_fault'
    assert len(packet['blocker_ids'])==11  # All remaining IDs are discoverable.


def test_numeric_progress_rewards_smaller_error_without_accepting_it(requirements,model,good_parameters):
    keys=[]
    for gap in [6,8,10]:
        good_parameters['gap_mm']=gap
        report=report_for(model.build(good_parameters).parts,requirements)
        assert not report['geometry_accepted']
        keys.append(progress_key(report))
    assert keys[0]>keys[1]>keys[2]


def test_parameter_context_omits_unusable_source_edit_schema(project):
    packet=context(project,{'status':'REPAIR_REQUIRED'})
    assert 'source' not in packet
    assert 'edits' not in packet['action_schema']['$defs']['Proposal']['properties']
    assert 'references' in packet and packet['units']=='mm'
    richer=context(project,{},allow_source_edits=True)
    assert 'source' in richer
    assert 'edits' in richer['action_schema']['$defs']['Proposal']['properties']
    assert len(canonical(packet))<len(canonical(richer))


def test_parameter_context_can_include_source_by_request(project):
    packet=context(project,{},include_source=True)
    assert 'source' in packet and packet['edit_mode']=='parameters_only'


def test_source_inspection_supports_later_lines_and_helpers(project):
    helper=project.design/'helper.py'
    helper.write_text('\n'.join('# line '+str(i) for i in range(1,401)))
    page=project.inspect(source=True,path='helper.py',start_line=201,max_lines=20)
    assert page['source'].startswith('201: # line 201')
    assert page['next_start_line']==221 and page['end_line']==220
    with pytest.raises(CadLoopError):
        project.inspect(source=True,path='../requirements.json')
    with pytest.raises(CadLoopError):
        project.inspect(source=True,path='helper.py',start_line=0)


def test_noop_source_edit_is_not_a_new_candidate(project):
    before=tree_hashes(project.design)
    with pytest.raises(CadLoopError) as error:
        project.propose({'base_revision':project.revision(),'edits':[{
            'path':'model.py','old':'def build(p):','new':'def build(p):'}],'reason':'No actual change'})
    assert error.value.code=='NO_CHANGE'
    assert tree_hashes(project.design)==before
