# Real-task test results — September 29, 2026

## Automated results

| Check | Result |
|---|---|
| Full repository suite | 431 passed, 0 failed, 0 skipped; 133.35 s |
| Shooter fresh finish | 471 passing checks, no failures/indeterminate results; 29 registered solids |
| 70° response rebuild | 470 passing checks; same side-panel BREPs as 65° |
| Mold fresh finish | 23 passing checks; 4 registered solids |
| Independent exported-BREP audits | 65° and 70° pass; measured outlet tangent and maximum-sphere path checked |
| Negative geometry probes | Wrong outlet-angle expectation and excessive 200 mm deck height rejected |
| Manufacturing meshes | 15/15 closed, positive volume, <1% deviation from source BREP |
| Cut sheet | Millimetre DXF/SVG, 600 × 400 sheet; extents x=10..560, y=10..381 mm |
| Export integrity | Both fresh finish manifests verified by SHA256 before conversion |

The full run had a mold-test return-value warning (subsequently corrected, focused mold test rerun successfully without warnings) and an upstream VTK/NumPy deprecation warning. `tests.xml` preserves the complete full-run accounting. No benchmark denominator excludes a failed attempt.

## Observed worker times

| Fresh finish stage | Build | Verify | Sum |
|---|---:|---:|---:|
| Shooter 65° | 3.3315 s | 5.5114 s | 8.8429 s |
| Shooter 70° | 3.0416 s | 5.3615 s | 8.4031 s |
| Mold | 1.8649 s | 1.5850 s | 3.4499 s |

These are one fresh finish per delivered configuration, excluding controller setup, rendering and packaging. They are not stable latency benchmarks or a before/after speed claim. Workers ran in restricted Docker, 2 CPU/3 GiB limits, immutable image `sha256:ab2b52751cbf2a474a1911166dfb02cbecd1f9a5477323ffbd1cb3f73cdb87da`. Python 3.13.15, CadQuery 2.8.0, OCP 7.9.3.1.1, Linux ARM64. Provider costs and token usage are unknown.

## What the task caught

Engineering review corrected a front motor placement that obstructed the intended shot, a disconnected material island in the cast-tire boolean, and a mold funnel that prevented flat cavity-up printing. The approved project was then locally revised through CADLoop proposals: a common forward hood arc slot makes 65°/70° hoods interchangeable without recutting plywood, and the mold now has a flat outer top with an internal recessed funnel. Requirements/checkers were not changed to clear these repairs. Independent review also corrected a false initial assumption that UltraPlanetary required a reduction stage: REV documents zero-stage 1:1 assembly.

This is one supervised integration task with human-style research and source design, not a controlled model-quality benchmark. Mechanical feasibility has open issues explicitly retained in the receipt: material strength, rotor integrity, friction/drag, chain and shaft interfaces, physical tolerances, actual turret and kit inventory, and scored shots. A nominal success flag must not be read as engineering approval.

## Comparison already measured for CADLoop

The separate six-case synthetic response-gate benchmark (three repeats, 18 attempts) improved correct classifications from 9/18 nominal-only to 18/18 with required parameter-response checks, and false accepts from 9/12 invalid attempts to 0/12. It added runtime: median nominal workers 3.230 s, additional scenario workers 9.728 s, total wall time 13.248 s. It did not measure inference quality or show a speed gain. See repository `docs/PARAMETRIC_RESULTS.md` and its frozen raw evidence. The shooter supplies a real integration example alongside that bounded benchmark; it does not replace physical testing.
