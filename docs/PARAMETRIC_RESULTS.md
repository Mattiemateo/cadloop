# Parameter-response acceptance: September 29, 2026

## What changed

Approved requirements can now demand measured responses to parameter changes.
Every declared scenario rebuilds its own input copy and retains all other checks.
`finish`, search and the repair loop require both nominal and response acceptance.
Original project parameters and requirements remain unchanged by these tests.

Docker evaluations pin one immutable image for build, verification, scenarios and
rendering. Cache reuse requires the same image and execution policy. Previews run
in a separate restricted container; rendering errors remain separate from geometry.
See [the contract and commands](KERF.md).

Evidence paths below refer to local generated files under ignored `work/`; the evidence and model exports are not committed to GitHub.

## Verification

The full suite passed **425 tests**, with no failures or skips, in **147.86 s**.
That adds 68 tests to the previous 357-test integration suite: 54 response-gate
cases, 13 runtime/cache/preview cases and one benchmark-accounting test. Coverage
includes ignored parameters, displaced interfaces, scaling, stale/tampered evidence,
worker failures, interrupted scenarios, export refusal and search/loop acceptance.
One upstream VTK/NumPy deprecation warning remains.

An earlier run during source edits had one failure and 417 passes; the frozen
54-case gate run and frozen full suite above passed with clean process exits.
The actual rebuilt Docker worker passed all isolation probes, including child
termination and container removal after timeout. A real cache hit and a separate
render-only checkpoint succeeded before the final fresh rebuild.

Evidence: [test summary](../work/phase2/test-summary.json),
[full log](../work/phase2/pytest-release.log),
[JUnit results](../work/phase2/pytest-release.xml),
[isolation](../work/phase2/isolation.json).

## Benchmark result

Six fixed synthetic cases, three repeats each, seed 29. Sources, approved targets,
expected verdicts, driver/controller hashes, image and policy were frozen before
scoring. All 18 attempts remain in the denominator. No infrastructure failures or
indeterminate scenarios occurred. Repeats were consistent.

| Case | Expected | Nominal-only decision | Required-response decision |
|---|---|---|---|
| Responsive `result` source | Accept | Accept | Accept |
| Responsive `BuildPart` source | Accept | Accept | Accept |
| Ignores length parameter | Reject | Accept | Reject |
| Ignores bore parameter | Reject | Accept | Reject |
| Thickness change displaces mounts | Reject | Accept | Reject |
| Mounts displaced at nominal setting | Reject | Reject | Reject |

| Metric | Nominal only | Required response |
|---|---:|---:|
| Correct decisions / all attempts | 9/18 | 18/18 |
| False accepts / invalid attempts | 9/12 | 0/12 |
| False rejects / valid attempts | 0/6 | 0/6 |

The response targets are length 54.00 ±0.01 mm, bore diameter 24 mm with
0.001 mm radius/position tolerance, and thickness 10.00 ±0.01 mm. Untouched
interfaces retain their nominal requirements. The moved-hole control has the same
bounds and volume (12556.814451665578 mm³) as the responsive control in every repeat;
the explicit interface check still rejects it.

These are two classifiers applied to the **same runs**, using nominal acceptance
as the legacy decision. This is evidence of improved detection on six known cases,
not 18 independent designs, a historical timing A/B, a hidden holdout, or a model
quality benchmark. There were no inference calls; token/cost fields are unknown.

## Runtime cost

| Time per attempt | Median | p95, nearest rank |
|---|---:|---:|
| Nominal build + verification | 3.230 s | 3.403 s |
| Additional scenario workers | 9.728 s | 10.102 s |
| Controller/setup/artifact reads | 0.264 s | 2.427 s |
| Total wall time | 13.248 s | 15.494 s |

All 18 attempts are included; the three nominal failures execute no scenarios.
The first attempt includes startup overhead. The response gate improves detection
and adds execution time. These measurements do not claim a speed improvement.
Benchmark CAD runs were separated from the full test run.

Environment: Linux ARM64, Python 3.13.15, CadQuery 2.8.0, Build123d 0.11.1,
OCP 7.9.3.1.1, VTK 9.6.2; each worker is limited to 2 CPUs and 3 GiB RAM.
The clean Docker build used the same key CAD dependency versions as the prior
integration. Installed worker and controller source digests match.

Raw evidence: [benchmark report](../work/phase2/benchmark/report.json),
[frozen plan](../work/phase2/benchmark/plan.json),
[runtime identity](../work/phase2/runtime.json),
[installed environment](../work/phase2/worker-environment.json).

Reproduce with a fresh output directory:

```sh
docker build -t cadloop-worker:0.1.1 .
.venv/bin/python scripts/check_worker_isolation.py --output work/isolation-new.json
.venv/bin/python scripts/benchmark_parametric.py --output work/benchmark-new --repeat 3 --seed 29
```

## Export and remaining scope

Fresh `finish` rebuilt the nominal carrier and all three scenarios: eight nominal
checks plus three scenario summaries pass; each scenario passes its own eight
checks. The nominal export measures 50 × 40 × 8 mm. Docker overview and axial
section previews were generated and visually checked.

[STEP export](../work/phase2/benchmark/repeat-01/responsive/project/exports/c682ba0c2d2c-d5c000ef/geometry/assembly.step)
and [self-contained report](../work/phase2/benchmark/repeat-01/responsive/project/exports/c682ba0c2d2c-d5c000ef/report.html)
are accompanied by input snapshots, scenario evidence and receipts.

Engineering approval remains false: bearing fits/retention, hardware dimensions,
material, loads, strength, manufacturing tolerances and dynamic clearance are
unverified. This is a synthetic fixture. STEP has no native Onshape feature tree.
Finite response scenarios do not prove the complete parameter domain. General
derived relationships/TaskSpec, a portable dependency lock, protected holdouts,
live account-model evaluation and native Onshape publishing remain open.
