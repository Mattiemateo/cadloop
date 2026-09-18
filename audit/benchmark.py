"""Reproducible microbenchmark; no provider requests or pricing assumptions.
Run: PYTHONPATH=src python audit/benchmark.py --output benchmark.json
"""
import argparse
import importlib.util
import json
import statistics
import time
from pathlib import Path
from unittest.mock import patch

from cadloop import kernel
from cadloop.checks import GeometryQueries, run_checks
from cadloop.contracts import Requirements
from cadloop.util import read_json, write_json, versions, digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repetitions', type=int, default=12)
    args = parser.parse_args()
    if not 3 <= args.repetitions <= 100:
        parser.error('repetitions must be between 3 and 100')
    template = Path(__file__).resolve().parents[1] / 'src/cadloop/templates/plate_stack'
    req = Requirements.model_validate(read_json(template / 'requirements.json'))
    spec = importlib.util.spec_from_file_location('reviewed_benchmark_fixture', template / 'design/model_cadquery.py')
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    params = read_json(template / 'design/parameters.json')
    params.update(include_spacer=True, gap_mm=12.)
    parts = model.build(params).parts
    samples = {'cached': [], 'uncached': []}
    calls = {}
    reports = {}
    # Warm both modes, then alternate their order to reduce ordering bias.
    for i in range(-2, args.repetitions):
        for mode in (('cached', 'uncached') if i % 2 == 0 else ('uncached', 'cached')):
            start = time.perf_counter()
            if mode == 'uncached':
                with patch.object(GeometryQueries, '_get', lambda self, key, compute: compute()):
                    report = run_checks(parts, req)
            else:
                report = run_checks(parts, req)
            elapsed = time.perf_counter() - start
            reports[mode] = report
            if i >= 0:
                samples[mode].append(elapsed)
    for mode in ('cached', 'uncached'):
        with patch.object(kernel, 'cylinders', wraps=kernel.cylinders) as spy:
            if mode == 'uncached':
                with patch.object(GeometryQueries, '_get', lambda self, key, compute: compute()):
                    run_checks(parts, req)
            else:
                run_checks(parts, req)
            calls[mode] = spy.call_count
    assert reports['cached'] == reports['uncached'], 'Cache changed check evidence'
    assert all(c['status'] == 'pass' for c in reports['cached'])
    med = {k: statistics.median(v) for k, v in samples.items()}
    result = {
        'scope': 'Identical hardened in-process geometric checks, one synthetic 3-part assembly; not end-to-end model or CAD build latency',
        'versions': versions(), 'repetitions_each': args.repetitions,
        'median_seconds': med, 'samples_seconds': samples,
        'median_reduction_percent': 100 * (1 - med['cached'] / med['uncached']),
        'cylindrical_face_traversals': calls,
        'identical_evidence': True, 'check_evidence_digest': digest(reports['cached']),
        'checks_in_microbenchmark': len(reports['cached']),
        'llm_calls': 0,
        'limitations': 'Single-machine microbenchmark with warm imports and prebuilt geometry. Does not predict large assemblies or model costs.'
    }
    write_json(args.output, result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
