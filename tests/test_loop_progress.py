import pytest
from cadloop.loop import repair_loop,ReplayProvider


@pytest.mark.integration
def test_numeric_improvement_is_not_mistaken_for_stall(project):
    project.propose({'base_revision':project.revision(),'parameters':{'include_spacer':True,'gap_mm':6},'reason':'Seed gap error'})
    actions=[{'kind':'propose','proposal':{'base_revision':'$CURRENT_REVISION',
             'parameters':{'gap_mm':gap},'reason':'Reduce measured error'}} for gap in [8,10,12]]
    r=repair_loop(project,ReplayProvider(actions),mode='trusted-native',max_steps=5)
    assert r['status']=='GEOMETRY_ACCEPTED'
    assert r['final_feedback']['exported']
