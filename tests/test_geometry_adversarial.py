"""Analytic adversaries: these shapes are valid solids but not usable holes."""
import cadquery as cq
import pytest
from cadloop import kernel as k
from cadloop.checks import check_one, run_checks
from cadloop.contracts import HolesCheck, Hole


@pytest.mark.parametrize('z,height', [(0,1),(2.5,1),(5,1),(2.5,.01)])
def test_partial_web_cannot_pass_as_through_bore(requirements,z,height):
    plate=cq.Solid.makeBox(20,20,6,cq.Vector(-10,-10,0))
    plate=plate.cut(cq.Solid.makeCylinder(4,8,cq.Vector(0,0,-1)))
    bridge=cq.Solid.makeBox(10,1,height,cq.Vector(-5,-.5,z))
    shape=plate.fuse(bridge).clean().wrapped
    assert k.metrics(shape)['valid'] and k.metrics(shape)['solid_count']==1
    check=HolesCheck(id='bore',kind='through_holes_z',description='Unobstructed bore',
                    part='plate',holes=[Hole(x=0,y=0,radius=4)])
    r=check_one(check,{'plate':shape},requirements)
    assert r['status']!='pass', 'A trimmed cylindrical face does not prove a clear hole'


def test_obstruction_is_rejected_in_full_assembly(requirements,model,good_parameters):
    parts=model.build(good_parameters).parts
    bridge=cq.Solid.makeBox(10,1,1,cq.Vector(-5,-.5,2.5))
    parts['lower_plate']=cq.Shape.cast(parts['lower_plate']).fuse(bridge).clean().wrapped
    checks=run_checks(parts,requirements)
    assert any(c['status']!='pass' for c in checks)
    assert next(c for c in checks if c['id']=='lower_holes')['status']=='fail'
