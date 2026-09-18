"""Run the complete pytest suite in a reproducible shuffled order."""
import argparse
import json
from pathlib import Path
import random
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument('--output-dir', type=Path, required=True)
p.add_argument('--seed', type=int, default=20260918)
a = p.parse_args()
a.output_dir.mkdir(parents=True, exist_ok=True)
root = Path(__file__).resolve().parents[1]
collected = subprocess.run([sys.executable, '-m', 'pytest', '--collect-only', '-q'], cwd=root,
                           capture_output=True, text=True, check=True)
nodes = [line.strip() for line in collected.stdout.splitlines() if line.startswith('tests/') and '::' in line]
if not nodes:
    raise SystemExit('No test nodes collected')
random.Random(a.seed).shuffle(nodes)
(a.output_dir / 'shuffled_order.json').write_text(json.dumps({'seed': a.seed, 'nodes': nodes}, indent=2))
command = [sys.executable, '-m', 'pytest', '-q', '--tb=short', '--durations=12',
           '--junitxml=' + str(a.output_dir / 'repeat.xml'), *nodes]
with (a.output_dir / 'repeat.log').open('w') as log:
    result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
(a.output_dir / 'repeat.exit').write_text(str(result.returncode) + '\n')
raise SystemExit(result.returncode)
