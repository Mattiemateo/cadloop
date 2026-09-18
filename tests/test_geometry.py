import math
import cadquery as cq
import pytest
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.gp import gp_Trsf, gp_Vec
from cadloop import kernel as k
from cadloop.checks import run_checks, check_one, interval
from cadloop.contracts import CylinderRef, HolesCheck, Hole
from cadloop.errors import CadLoopError


def statuses(checks):
    return {c['id']: c for c in checks}


def test_known_correct_assembly(requirements, model, good_parameters):
    checks = run_checks(model.build(good_parameters).parts, requirements)
    assert checks and all(c['status'] == 'pass' for c in checks)


def test_plate_analytic_volume_and_dimensions(model):
    m = k.metrics(model.plate(6, 8).wrapped)
    expected = 80*50*6 - math.pi*(4**2+4*1.6**2)*6
    assert m['volume_mm3'] == pytest.approx(expected, abs=1e-6)
    assert m['bounds_mm']['size'] == pytest.approx([80, 50, 6])


@pytest.mark.parametrize('parameter,value,check_id', [
    ('gap_mm', 8, 'plate_gap'),
    ('gap_mm', 16, 'plate_gap'),
    ('plate_thickness_mm', 5, 'lower_z'),
    ('bore_diameter_mm', 9, 'lower_holes'),
    ('spacer_length_mm', 11, 'upper_spacer_contact'),
    ('upper_dx_mm', 1, 'bore_alignment'),
])
def test_seeded_parameter_faults(parameter, value, check_id, requirements, model, good_parameters):
    good_parameters[parameter] = value
    r = statuses(run_checks(model.build(good_parameters).parts, requirements))
    assert r[check_id]['status'] != 'pass'


def test_missing_spacer_is_not_hidden_by_scene_inventory(requirements, model, good_parameters):
    good_parameters['include_spacer'] = False
    r = statuses(run_checks(model.build(good_parameters).parts, requirements))
    assert r['AUTO_inventory']['status'] == 'fail'
    assert r['AUTO_inventory']['evidence']['missing'] == ['spacer']
    assert r['upper_spacer_contact']['status'] == 'indeterminate'


def test_interference_volume_not_bbox_guess(requirements, model, good_parameters):
    good_parameters['gap_mm'] = 8
    r = statuses(run_checks(model.build(good_parameters).parts, requirements))
    c = r['AUTO_overlap_upper_plate_spacer']
    assert c['status'] == 'fail'
    assert c['evidence']['overlap_mm3'] == pytest.approx(math.pi*(81-16)*4, abs=1e-5)
    assert c['evidence']['method'] == 'BREP_boolean_common'


def test_stray_named_part_rejected(requirements, model, good_parameters):
    parts = model.build(good_parameters).parts
    parts['surprise'] = cq.Workplane().box(1, 1, 1).translate((100, 0, 0)).val().wrapped
    assert statuses(run_checks(parts, requirements))['AUTO_inventory']['status'] == 'fail'


def test_stray_solid_inside_part_rejected(requirements, model, good_parameters):
    parts = model.build(good_parameters).parts
    parts['lower_plate'] = k.compound([parts['lower_plate'], cq.Workplane().box(1,1,1).val().wrapped])
    assert statuses(run_checks(parts, requirements))['AUTO_valid_lower_plate']['status'] == 'fail'


def test_spacer_cannot_be_placed_elsewhere_on_plate(requirements, model, good_parameters):
    parts = model.build(good_parameters).parts
    tr=gp_Trsf(); tr.SetTranslation(gp_Vec(20,0,0))
    parts['spacer']=BRepBuilderAPI_Transform(parts['spacer'],tr,True).Shape()
    r=run_checks(parts,requirements)
    assert any(c['status'] != 'pass' for c in r), 'A relocated spacer must not pass.'


def test_extra_open_face_inside_part_rejected(requirements, model, good_parameters):
    parts = model.build(good_parameters).parts
    sheet = cq.Workplane('XY').rect(2,2).wires().toPending().extrude(.1).val().Faces()[0].wrapped
    parts['lower_plate'] = k.compound([parts['lower_plate'], sheet])
    assert statuses(run_checks(parts, requirements))['AUTO_valid_lower_plate']['status'] == 'fail'


def test_distance_closest_points():
    a=cq.Solid.makeBox(2,2,2).wrapped
    b=cq.Solid.makeBox(2,2,2,cq.Vector(5,0,0)).wrapped
    d=k.distance(a,b)
    assert d['distance_mm'] == pytest.approx(3)
    assert k.norm(k.sub(d['point_a_mm'],d['point_b_mm'])) == pytest.approx(3)
    assert k.common_volume(a,b)==0


def test_contact_is_not_overlap():
    a=cq.Solid.makeBox(2,2,2).wrapped
    b=cq.Solid.makeBox(2,2,2,cq.Vector(2,0,0)).wrapped
    assert k.distance(a,b)['distance_mm']==pytest.approx(0)
    assert k.common_volume(a,b)==pytest.approx(0)


def test_nested_solids_overlap():
    a=cq.Solid.makeBox(10,10,10).wrapped
    b=cq.Solid.makeBox(2,2,2,cq.Vector(4,4,4)).wrapped
    assert k.common_volume(a,b)==pytest.approx(8)
    assert k.distance(a,b)['distance_mm']==pytest.approx(0)


def test_hollow_shape_bounding_boxes_overlap_without_interference():
    ring=cq.Solid.makeCylinder(10,5).cut(cq.Solid.makeCylinder(8,5)).wrapped
    inner=cq.Solid.makeCylinder(5,5).wrapped
    assert not k.disjoint_bounds(ring,inner)
    assert k.common_volume(ring,inner)==pytest.approx(0)
    assert k.distance(ring,inner)['distance_mm']==pytest.approx(3)


def test_rotated_parts_distance():
    a=cq.Solid.makeBox(2,2,2).wrapped
    b=cq.Solid.makeBox(2,2,2).rotate((0,0,0),(0,0,1),45).translate((8,0,0)).wrapped
    assert k.distance(a,b)['distance_mm'] > 4
    assert k.common_volume(a,b)==0


def test_boolean_failure_is_not_empty_intersection(monkeypatch):
    class Failed:
        def __init__(self,*args): pass
        def IsDone(self): return False
    monkeypatch.setattr(k,'BRepAlgoAPI_Common',Failed)
    with pytest.raises(CadLoopError,match='did not complete'):
        k.common_volume(cq.Solid.makeBox(1,1,1).wrapped,cq.Solid.makeBox(1,1,1).wrapped)


def test_blind_hole_fails_through_check(requirements):
    plate=cq.Solid.makeBox(20,20,6,cq.Vector(-10,-10,0))
    plate=plate.cut(cq.Solid.makeCylinder(4,3,cq.Vector(0,0,3)))
    c=HolesCheck(id='bore',kind='through_holes_z',description='Must be through',part='p',holes=[Hole(x=0,y=0,radius=4)])
    r=check_one(c,{'p':plate.wrapped},requirements)
    assert r['status']=='fail'
    assert any(x.get('reason')=='BLIND_OR_PARTIAL_HOLE' for x in r['evidence']['defects'])


def test_external_cylinder_is_not_a_hole():
    assert k.holes_z(cq.Solid.makeCylinder(4,6).wrapped)==[]


def test_ambiguous_reference_is_rejected():
    s=cq.Solid.makeBox(30,20,6,cq.Vector(-15,-10,0))
    for x in [-6,6]: s=s.cut(cq.Solid.makeCylinder(2,8,cq.Vector(x,0,-1)))
    with pytest.raises(CadLoopError) as e:
        k.cylinder_ref(s.wrapped,CylinderRef(kind='cylinder',part='p',radius=2))
    assert e.value.code=='REF_AMBIGUOUS'


def test_numerical_boundary_is_indeterminate():
    assert interval(2,2,3,1e-6)=='indeterminate'
    assert interval(2.5,2,3,1e-6)=='pass'
    assert interval(1.99,2,3,1e-6)=='fail'
