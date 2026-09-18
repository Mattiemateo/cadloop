"""Seeded analytic oracles: independent box equations, not generator self-reporting."""
import math
import random
import cadquery as cq
import pytest
from cadloop import kernel as k


def case(seed):
    rng=random.Random(42000+seed)
    sa=[rng.randint(2,30)/4 for _ in range(3)]
    sb=[rng.randint(2,30)/4 for _ in range(3)]
    a=[rng.randint(-30,30)/4 for _ in range(3)]
    b=[rng.randint(-30,30)/4 for _ in range(3)]
    if seed%4==0: b=a.copy()
    if seed%4==1: b=a.copy(); b[0]+=sa[0]
    if seed%4==2: b=a.copy(); b[0]+=sa[0]+rng.randint(1,15)/4
    overlap=math.prod(max(0.,min(a[i]+sa[i],b[i]+sb[i])-max(a[i],b[i])) for i in range(3))
    gap=math.sqrt(sum(max(0.,b[i]-(a[i]+sa[i]),a[i]-(b[i]+sb[i]))**2 for i in range(3)))
    return cq.Solid.makeBox(*sa,cq.Vector(*a)),cq.Solid.makeBox(*sb,cq.Vector(*b)),overlap,gap


@pytest.mark.parametrize('seed',range(64))
def test_aabb_oracle_and_symmetry(seed):
    a,b,volume,gap=case(seed)
    assert k.common_volume(a.wrapped,b.wrapped)==pytest.approx(volume,abs=1e-7)
    d=k.distance(a.wrapped,b.wrapped)
    assert d['distance_mm']==pytest.approx(gap,abs=1e-7)
    assert k.norm(k.sub(d['point_a_mm'],d['point_b_mm']))==pytest.approx(gap,abs=1e-7)
    assert k.distance(b.wrapped,a.wrapped)['distance_mm']==pytest.approx(gap,abs=1e-7)
    if k.disjoint_bounds(a.wrapped,b.wrapped):
        assert volume==0 and gap>0


@pytest.mark.parametrize('seed',range(12))
def test_rigid_transform_preserves_measurements(seed):
    a,b,volume,gap=case(seed)
    def moved(shape):
        return shape.rotate((0,0,0),(1,2,3),37).translate((100,-53,17)).wrapped
    aa,bb=moved(a),moved(b)
    assert k.common_volume(aa,bb)==pytest.approx(volume,abs=2e-7)
    assert k.distance(aa,bb)['distance_mm']==pytest.approx(gap,abs=1e-7)


@pytest.mark.parametrize('scale',[.25,2.,4.])
def test_scale_covariance(scale):
    for seed in range(4):
        a,b,volume,gap=case(seed)
        a,b=a.scale(scale).wrapped,b.scale(scale).wrapped
        assert k.common_volume(a,b)==pytest.approx(volume*scale**3,abs=1e-6)
        assert k.distance(a,b)['distance_mm']==pytest.approx(gap*scale,abs=1e-7)
