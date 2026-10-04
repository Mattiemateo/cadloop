"""Small actionable packets; geometry evidence and acceptance remain independent."""
from __future__ import annotations
import math


def progress_key(report):
    """A scheduling heuristic, NOT an acceptance score.

    Fewer artifact/validity failures take priority over counts, then normalized
    numerical violation. Improving a gap must not look stalled merely because
    the same check still fails. Complete, independent checks still gate delivery.
    """
    blockers = [c for c in report['checks'] if c['blocking'] and c['status'] != 'pass']
    fatal = sum(c['id'].startswith(('AUTO_export_', 'AUTO_valid_', 'AUTO_inventory',
                                   'AUTO_execution', 'AUTO_artifacts', 'AUTO_check_coverage')) for c in blockers)
    penalties = []
    def amount(value, limit, lower=False):
        if type(value) not in (float,int) or type(limit) not in (float,int):
            return
        if not math.isfinite(value) or not math.isfinite(limit):
            return
        error = max(0., limit-value if lower else value-limit)
        ratio = error/max(abs(limit),1e-9)
        if math.isfinite(ratio):
            penalties.append(math.log1p(ratio))
    for c in blockers:
        ev=c['evidence']
        value=ev.get('measured_mm',ev.get('distance_mm'))
        if 'range_mm' in ev:
            lo,hi=ev['range_mm']
            if lo is not None: amount(value,lo,True)
            if hi is not None: amount(value,hi)
        for metric,limit,lower in [('offset_mm','max_offset_mm',False),
                ('angle_deg','max_angle_deg',False), ('distance_mm','max_gap_mm',False),
                ('projected_contact_area_mm2','min_area_mm2',True),
                ('overlap_mm3','allowed_numerical_mm3',False)]:
            if metric in ev and limit in ev:
                amount(ev[metric],ev[limit],lower)
        for defect in ev.get('defects',[]):
            if 'obstruction_mm3' in defect:
                amount(defect['obstruction_mm3'],defect.get('allowed_numerical_mm3',0))
    return [fatal,len(blockers),round(sum(penalties),9)]


def compact(report, *, detail_limit=8):
    if type(detail_limit) is not int or not 1 <= detail_limit <= 32:
        raise ValueError('detail_limit must be between 1 and 32')
    blockers=[c for c in report['checks'] if c['blocking'] and c['status']!='pass']
    def priority(c):
        if c['id']=='AUTO_execution': return 0
        if c['code'] in ('INVENTORY_MISMATCH','INVALID_SOLID','CHECK_COVERAGE_INVALID'): return 1
        if c['status']=='fail': return 2
        if c['code'] in ('DEPENDENCY_INVALID','BUILD_UNAVAILABLE','MISSING_REQUIRED_PART'): return 4
        return 3
    ordered=sorted(blockers,key=priority)
    details=[]
    for c in ordered[:detail_limit]:
        ev=c['evidence']
        brief={key:ev[key] for key in ('missing','unexpected','measured_mm','range_mm',
                    'distance_mm','parts','part','offset_mm','angle_deg','overlap_mm3',
                    'projected_contact_area_mm2','max_gap_mm','min_area_mm2',
                    'max_offset_mm','max_angle_deg','match_count','duplicate',
                    'scenario','parameters','blocker_ids','run_directory') if key in ev}
        if 'observed' in ev:
            brief['observed_holes']=[{'center_xy_mm':h['axis_origin_mm'][:2],
                                      'radius_mm':h['radius_mm'],
                                      'z_span_mm':[h['bounds_mm']['min'][2],h['bounds_mm']['max'][2]]}
                                     for h in ev['observed'][:8]]
            brief['observed_hole_count']=len(ev['observed'])
            brief['expected_holes']=ev.get('expected',[])[:8]
            brief['expected_hole_count']=len(ev.get('expected',[]))
            brief['defects']=ev.get('defects',[])[:8]
            brief['hole_details_truncated']=any(len(ev.get(key,[]))>8 for key in ('observed','expected','defects'))
        if 'execution' in ev:
            brief['execution']={key:ev['execution'][key] for key in ('stage','exit_code','timed_out','stderr_tail') if key in ev['execution']}
        details.append({'id':c['id'],'status':c['status'],'code':c['code'],
                        'message':c['message'],'measurement':brief,'edit_hint':c['edit_hint']})
    packet = {'schema_version':1,'revision':report['revision'],'status':report['status'],
            'geometry_accepted':report['geometry_accepted'],'engineering_approved':False,
            'parametric_accepted':report.get('parametric_accepted'),
            'task_accepted':report.get('task_accepted',report['geometry_accepted']),
            'parametric_tests':report.get('parametric_tests',[]),
            'summary':report['summary'],'blocker_ids':[c['id'] for c in blockers],
            'blockers':details,'more_blocker_details':max(0,len(blockers)-detail_limit),
            'inspect_instruction':'Use inspect --check CHECK_ID for full evidence.',
            'suggested_view':'section_xz','units':'mm','progress_key':progress_key(report),
            'engineering_blockers':report['engineering_blockers']}
    for key in ('design_contract_hash', 'design_contract_revision'):
        if key in report:
            packet[key] = report[key]
    return packet
