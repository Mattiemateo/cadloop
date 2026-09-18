# CADLoop v0.1.1: adversarial audit and measured improvements

**Date:** September 18, 2026. **Scope:** audit and patches to the supplied v0.1.0 implementation, not a redesign of the architecture.

## Results

| Run | Passed | Skipped | Failed / errors | Recorded duration |
|---|---:|---:|---:|---:|
| Original suite, rerun before changes | 74 | 1 | 0 / 0 | 58.52 s |
| Expanded suite after patches | 214 | 1 | 0 / 0 | 122.35 s |
| Complete expanded suite, shuffled order | 214 | 1 | 0 / 0 | 122.82 s |

The expanded suite adds **140 passing test cases**. Counts include parameterized cases, not that many distinct robot designs. The repeat uses seed 20260918. The only skipped case needs unavailable build123d. All executed CAD tests use actual CadQuery/OpenCascade geometry; provider tests use mocks or scripted replay. CADLoop made **zero live inference requests**.

## Reproduced defects and fixes

| Defect in v0.1.0 | Consequence | Patch and retained regression |
|---|---|---|
| A solid bar/web across a bore retained enough cylindrical-face metadata to pass the old through-hole test. | A blocked hole passed every local assembly geometry check. | Probe the actual bore interior with a continuous inset cylinder and measure BREP common volume. Four obstruction positions/thicknesses plus full-assembly and delivered-export demonstrations are tested. |
| A multi-object CadQuery Workplane was unwrapped with `.val()`. | The second object was silently discarded before checking. | Reject empty/multi-object stacks and require explicit registration or composition. Single-object authoring still works. |
| A report containing only custom requirements could omit automatic inventory, validity, overlap and export checks. Duplicate IDs were also accepted. | An incomplete report could declare acceptance. | Require the complete unique set of checks. Remove each of the fixture's 26 required IDs in turn and require rejection. |
| An unbounded interval accepted NaN/infinity; JSON accepted duplicate keys and exponent overflow. | Invalid or ambiguous evidence/configuration could pass through validation. | Reject ambiguous/nonfinite JSON and fail closed on invalid measurement/bound/tolerance values. |
| Native cache could satisfy a Docker request; a timeout could poison subsequent evaluations; missing previews stayed missing. | Execution policy was bypassed by cache lookup, or retries did no useful work. | Match execution mode, reject failed/indeterminate cached runs, and create sealed view-only checkpoints for missing native previews. Actual Docker execution remains untested. |
| Oversized edits failed only after replacing the working design. | A rejected proposal still changed source and parameters. | Validate total source size and no-op status before commit; multi-edit failures remain atomic. |
| Search announced a feasible winner even when mandatory final validation failed. | Success contradicted its own latest evidence. | Return `FINAL_VALIDATION_FAILED`, no winning value and CLI exit 2. |
| A pending budget reservation did not block a new reservation. | An uncertain outstanding call could be followed by another paid request. | Serialize ledger mutations and block pending/uncertain reservations; concurrent and mocked-usage tests are retained. |
| No-progress detection compared only blocker counts. | A 6 to 8 to 10 to 12 mm repair was stopped even though it was improving toward the valid design. | Compare a numerical-violation scheduling key after artifact/check counts; preserve the strict final acceptance gate. Real CAD replay now completes. |

Failed-before logs are retained as `regressions_before`, `geometry_before`, `progress_before` and `authoring_before` under `evidence/audit/`. Multiple parameterized failures can represent one defect; they are not reported as separate bugs.

## Additional hardening, distinguished from reproduced bugs

Complete search, finish and managed-loop transactions now hold an advisory project lock. Cross-thread/process tests verify serialization; this is not crash-consistent distributed locking. Preview generation now runs in a bounded child interpreter: an injected failed preview stage does not destroy successful geometric evidence, and the error is exported. An actual reviewed build process killed by SIGSEGV is rejected with execution evidence. This does not test a real graphics-driver exploit or a security sandbox.

Exported BREP/STEP files containing an extra free face were already rejected by the original implementation in the tested cases. Those negative controls were retained and explicit export-topology checks strengthened; this is **not** counted as a newly discovered false pass.

## Independent and adversarial geometry checks

The suite includes 64 seeded box-pair cases checked against independent analytic overlap-volume and Euclidean-distance formulas; 12 rigid-transform cases; and 12 scale configurations within 3 parameterized tests. Cases cover touching, overlapping, separated and nested geometry. Closest-point witnesses and distance symmetry are checked. Existing hollow-body, blind-hole, extra-body, shifted-spacer, wrong-diameter, alignment and kernel-failure tests remain.

The bore test deliberately uses valid solids. It is not just detecting an invalid BREP. The new probe is a supported analytic straight Z-bore check with explicit radial/numerical guards and overlap tolerance. It does not certify arbitrary curved passages, filleted topology, surface roughness or physical press fits.

## Cheap wins: what was actually measured

### Smaller parameter-repair context

Canonical JSON decreased from **9,187 to 4,892 bytes**, a **46.75% reduction** for the recorded synthetic packet. Parameter-only mode no longer sends source it cannot edit or unusable source-edit schema fields. Repeated schema labels/prose are removed, while dimensions, limits, units and named geometric references remain. Source is opt-in and can be paged by file and line range.

This is a byte comparison, not a measured token bill, inference speedup or model-quality result. Source-capable tasks need a richer packet. The saved before/after JSON files make the comparison inspectable.

### Fewer redundant geometry traversals, but no demonstrated meaningful speedup

Within one evaluation, cylindrical-face traversals dropped from **7 to 3**, with byte-equivalent complete check evidence. The cache is not reused across revisions. Twelve paired warm microbenchmark repetitions measured **105.73 ms uncached versus 105.39 ms cached** median. The approximately 0.32% difference is too small to claim a useful wall-clock gain. BREP operations dominate this tiny fixture.

This comparison uses the same new hardened checks in both modes. The old check runtime is not a fair speed baseline because it did not validate bore obstruction. The microbenchmark excludes startup, construction, export, rendering and inference.

### Avoided work

A render-only cached request now launches **zero CAD build/verification workers**, retaining identical already-verified geometry in a new sealed checkpoint. `finish` still rebuilds and verifies. Parameter search validates then removes duplicate values, restores the initial state after unsuccessful/handled-interrupted searches, and does not fabricate a final winner. Improving numerical repairs avoid unnecessary early escalation; actual paid-model savings have not been measured.

Compact feedback now includes measured hole dimensions and prioritizes actionable causes over cascaded missing-dependency messages, while retaining every blocker ID. Recent repair attempts remain bounded to two in managed context.

## Reproduction

Run the normal tests, then the shuffled suite and benchmark:

```sh
python -m pytest -q
python audit/run_shuffled.py --output-dir work/repeat --seed 20260918
python audit/benchmark.py --output work/benchmark.json
python audit/blocked_bore_demo.py --project work/bore --evidence work/bore-evidence
```

Use the installed environment created by `scripts/bootstrap.sh`, or prefix commands with `.venv/bin/`. The demonstration script executes reviewed Python in **unsandboxed native mode**. It first rejects a barred bore, removes the bar, then freshly verifies and exports the corrected fixture. Stored absolute paths in evidence refer to this run's container, not your computer.

## What this release does not establish

Build123d, Docker isolation, macOS, a clean networked install, live provider compatibility, inexpensive-model CAD ability, and cost per accepted task remain unverified. No Onshape native-feature export or new real drivetrain model is included. The observed cases all pass after the fixes, but tests do not prove general geometric correctness, manufacturing readiness or structural safety. Requirements still need independent review; an unstated design intention cannot be automatically enforced.

The coverage tool observes the test/controller interpreter, not all worker-process execution. Raw line-coverage output is included as diagnostic data only. This audit is not a hostile-code security audit or certification.

## Packaging smoke test

Built `cadloop-0.1.1-py3-none-any.whl`, installed it into a separate virtual
environment, ran the installed CLI, and performed a fresh installed-wheel build,
verification and export: all 26 fixture checks passed. Existing CAD dependencies
were explicitly reused from this runtime. The first attempted inherited-only
virtual environment did not see the parent environment's Pydantic; dependency
visibility was corrected before the successful smoke run. This is not a clean
networked dependency installation test.
