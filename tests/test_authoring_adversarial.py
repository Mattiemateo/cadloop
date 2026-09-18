import cadquery as cq
import pytest
from cadloop.authoring import Scene,unwrap
from cadloop import kernel as k


def test_workplane_does_not_silently_discard_second_object():
    first=cq.Solid.makeBox(1,1,1)
    second=cq.Solid.makeBox(1,1,1,cq.Vector(10,0,0))
    multi=cq.Workplane().add(first).add(second)
    assert len(multi.vals())==2
    with pytest.raises((ValueError,TypeError)):
        Scene().add('part',multi)


def test_single_object_workplane_still_works():
    scene=Scene()
    scene.add('part',cq.Workplane().box(1,2,3))
    assert k.volume(scene.parts['part'])==pytest.approx(6)


def test_empty_workplane_is_rejected():
    with pytest.raises((ValueError,TypeError)):
        unwrap(cq.Workplane())
