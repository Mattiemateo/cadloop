# Delivery status and deviations

This is an implemented prototype, not completion of every milestone in the original architecture.

## Implemented and exercised

- CadQuery model generation and raw OCP BREP/STEP export in a child process.
- Independent verification in a second interpreter, without importing generated design code.
- Typed requirements, bounded parameters, unique source replacements and revision checks.
- Hashed source snapshots, versioned runs, artifact receipts and a separate last-accepted pointer.
- Solid/inventory/free-topology checks, analytic supported-feature checks and assembly measurements.
- Exact-kernel Boolean overlap (within numerical tolerances), clearance witnesses and planar contact footprints.
- Full BREP/STEP geometry consistency checks by solid count and bidirectional volume difference.
- Compact feedback, source inspection, detailed JSON evidence, real section views and offline HTML.
- Depth-buffered VTK previews from BREP meshes, tested with the installed offscreen Linux graphics backend.
- Bounded parameter search; full-revision cache with integrity checks; fresh final verification.
- Scripted replay of the repair loop with actual CAD regeneration.
- Text-only HTTP adapter mock tests, persistent cost reservation tests, explicit stop limits.

## Implemented but not live-tested

- Equivalent build123d fixture and shared `Shape.wrapped` registration interface.
- Chat Completions-compatible inference transport, with user-configured endpoint/model/prices.
- Docker command/profile. Docker was unavailable in the delivery environment.
- Bootstrap installation on a networked machine, macOS, and Python 3.12.

The native runs used Python 3.13.5, CadQuery 2.8.0 and cadquery-ocp
7.9.3.1.1. Build123d and Docker remain unavailable in the audit runtime. A build123d
package installation/resolution attempt did not succeed. No live-model credentials
were used. Replays and mocked HTTP requests are not cheap-model ability tests.

## Deliberately not implemented yet

- `agentcad` adapter and its live viewer. A small direct executor and offline views
  were used to deliver a testable core with the installed kernel rather than an
  untested upstream integration.
- Native Onshape publishing or FCStd feature-tree generation.
- Automatic strong-model escalation or cross-session inference resume.
- Per-part/feature caching, symbolic operation graphs and arbitrary feature queries.
- Reviewed real motor/wheel/bearing dimensions or a complete drivetrain model.
- General manufacturing checks, tolerance stacks, motion or structural analysis.
- A resolved `uv.lock`: package download/resolution was unavailable. The delivered
  environment snapshot is not a portable dependency-lock claim.

The original M0 security/clean-environment gate and full M2/M4 gates are therefore
not claimed complete. The narrower native execution/measurement/repair demonstration
is complete and backed by the included tests.

## Faults discovered during implementation

Two new negative tests initially failed: a spacer shifted sideways still passed
because its contact footprints were sufficient, and an extra free face could hide
alongside a valid solid. The protected demonstration specification now checks the
spacer bore/axis/envelope, and solid validation checks that all face/edge/vertex
topology belongs to the expected solid. Those regressions are retained in the suite.

## Next implementation priorities

1. Run the optional build123d test on a networked machine; pin the resolved environment.
2. Run Docker isolation/adversarial tests before enabling generated source edits.
3. Replace the synthetic fixture with reviewed drivetrain reference parts and requirements.
4. Benchmark a single inexpensive model on held-out creation and repair tasks. Only
   introduce model routing or terser prompts after measuring cost per accepted task.
5. Add named operation recording and a restricted native Onshape exporter separately.

## v0.1.1 adversarial audit

See `AUDIT.md` and the raw `evidence/audit/` records. This release fixes reproduced
geometry false passes, discarded Workplane objects, incomplete-report acceptance,
nonfinite input handling, execution-mode cache confusion, transient-failure reuse,
atomic edit failures, false final search success, pending budget reuse and premature
stalling during numerically improving repairs. It also adds bounded render-worker
isolation and scoped, per-evaluation query caching.

Expanded suite: 214 passed, 1 skipped. The count includes parameterized numerical
cases, not 214 distinct robot designs. Known seeded faults tested by the suite were
rejected; this is not evidence of universal geometric correctness.

## Packaging smoke test

Built `cadloop-0.1.1-py3-none-any.whl`, installed it into a separate virtual
environment, ran the installed CLI, and performed a fresh installed-wheel build,
verification and export: all 26 fixture checks passed. Existing CAD dependencies
were explicitly reused from this runtime. The first attempted inherited-only
virtual environment did not see the parent environment's Pydantic; dependency
visibility was corrected before the successful smoke run. This is not a clean
networked dependency installation test.
