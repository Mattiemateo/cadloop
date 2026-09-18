"""Create and reject an obstructed through-hole, then repair and export.
Reviewed synthetic source only. This intentionally uses UNSANDBOXED native mode.
"""
import argparse
from pathlib import Path
import shutil
from cadloop.project import Project
from cadloop.util import read_json, write_json

p = argparse.ArgumentParser()
p.add_argument('--project', type=Path, required=True)
p.add_argument('--evidence', type=Path, required=True)
a = p.parse_args()
a.evidence.mkdir(parents=True, exist_ok=True)
project = Project.initialize(a.project)
project.propose({'base_revision': project.revision(),
                 'parameters': {'gap_mm': 12., 'include_spacer': True},
                 'reason': 'Set the reviewed analytical fixture dimensions.'})
original = (project.design / 'model.py').read_text()
wrapper = '''\n\n_unobstructed_build = build

def build(p):
    scene = _unobstructed_build(p)
    # A real solid bar crosses the otherwise cylindrical lower-plate bore.
    bridge = cq.Solid.makeBox(10, 1, 1, cq.Vector(-5, -0.5, 2.5))
    lower = cq.Shape.cast(scene.parts["lower_plate"])
    scene.parts["lower_plate"] = lower.fuse(bridge).clean().wrapped
    return scene
'''
project.propose({'base_revision': project.revision(), 'edits': [
    {'path': 'model.py', 'old': original, 'new': original + wrapper}],
    'reason': 'Deliberately obstruct the through-bore to test independent checking.'})
rejected = project.evaluate(mode='trusted-native', render=True)
assert not rejected['geometry_accepted'], rejected
run, report = project.latest()
check = next(c for c in report['checks'] if c['id'] == 'lower_holes')
assert check['status'] == 'fail', check
assert any(d.get('reason') == 'BORE_OBSTRUCTED' for d in check['evidence']['defects']), check
shutil.copytree(run, a.evidence / 'rejected')
project.propose({'base_revision': project.revision(), 'edits': [
    {'path': 'model.py', 'old': wrapper, 'new': ''}],
    'reason': 'Remove the obstruction and preserve all protected requirements.'})
accepted = project.finish(mode='trusted-native')
assert accepted['geometry_accepted'] and accepted['exported'], accepted
shutil.copytree(Path(accepted['export_directory']), a.evidence / 'accepted')
write_json(a.evidence / 'summary.json', {
    'rejected': rejected, 'obstructed_bore_check': check, 'accepted': accepted,
    'llm_calls': 0, 'scope': 'Synthetic geometry regression, not live-model or manufacturing validation'})
print('Blocked bore rejected; repaired assembly freshly verified and exported.')
