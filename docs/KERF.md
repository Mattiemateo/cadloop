# Kerf import: first integration

CADLoop imports Kerf's version 1.0.0 parameter specification and Build123d source,
then uses its existing build worker, independent BREP/STEP verifier, revision
proposals, bounded search and fresh `finish` gate. No Kerf provider loop is started.
Codex remains the account-authenticated agent; Cursor is retained.

This implements the first vertical slice in `IMPLEMENTATION_BRIEF.md` from
`CADLoop_Upgrade_Brief_2026-09-29.zip`, not the whole backlog. The source comparison,
test results and delivery artifacts are under `work/kerf-upgrade/`.

The subsequent response-gate/cache/preview implementation and measured results are
recorded in [PARAMETRIC_RESULTS.md](PARAMETRIC_RESULTS.md), with evidence under
`work/phase2/`.

## Install

Keep Kerf in a separate checkout. The inspected upstream revision is
`7ff449c9cf6ecf409d4faba209119646440b92f2`:

```sh
git clone https://github.com/wearethefoos/kerf.git ../kerf
git -C ../kerf checkout --detach 7ff449c9cf6ecf409d4faba209119646440b92f2
uv pip install --python .venv/bin/python ../kerf/schemas/python/kerf_schemas
docker build -t cadloop-worker:0.1.1 .
.venv/bin/python scripts/check_worker_isolation.py --output work/isolation.json
```

Only Kerf's small schema package is needed in the controller environment. Neither
its harness nor its CAD stack is imported by the controller. Install the standalone
packages with `uv sync --frozen --python 3.12` separately in Kerf's `harness/` and
`sidecar/` directories. Installation does not start a provider or service.

For account-driven planning, use Kerf's existing `extract_spec.py`, `clarify.py`
and `plan_features.py` instructions under `harness/src/kerf_harness/steps/`.
Resolve critical questions explicitly and produce `ParameterSpec` JSON. Write
Build123d source using injected `params` and either `result` or a `BuildPart`
context named `part`. Supply separately reviewed CADLoop requirements. The importer
does not derive acceptance targets from proposed parameter values or model guesses.

## Run the synthetic carrier

From CADLoop's root, use a new project directory:

```sh
.venv/bin/cadloop import-kerf work/kerf-carrier \
  --spec examples/kerf_carrier/spec.json \
  --code examples/kerf_carrier/model.py \
  --requirements examples/kerf_carrier/requirements.json --part carrier
.venv/bin/cadloop state work/kerf-carrier
.venv/bin/cadloop evaluate work/kerf-carrier --docker --no-render
# Expected exit 2: the initial bore is deliberately undersized.
.venv/bin/cadloop inspect work/kerf-carrier --check interfaces
.venv/bin/cadloop search-parameter work/kerf-carrier bore_diameter \
  --values '[20,21,22]' --docker
.venv/bin/cadloop finish work/kerf-carrier --docker
```

Use the `export_directory` returned by `finish`. Its `geometry/assembly.step` is
the delivery; source, parameters, measurements and receipts accompany it. The
fixture targets a 50 × 40 × 8 mm plate (each dimension ±0.01 mm), a 22 mm central
through bore and four 4 mm through holes at (±18, ±13) mm. Hole radius and position
tolerance is 0.001 mm. These are synthetic test requirements, not reviewed bearing
fits or fabrication instructions.

`design/kerf_model.py` preserves the imported source for scoped inspection and
local repair. The wrapper's `IMPORT_PROVENANCE` retains the original specification,
units and input hashes inside revision snapshots and exports. Its feature sequence
is diagnostic planning information, not proof that those features exist. After a
source patch, the original source hash remains import provenance.

## Supported boundary

- One named body; existing projects cannot be overwritten.
- Independent numeric parameters: mm/cm/m/in/ft normalize to mm, rad/deg to
  degrees, and `count` to an integer. Per-parameter units take precedence over
  the part's display unit. Source receives normalized values and must not apply
  a second conversion.
- Exact parameter-name agreement and compatible kinds, units and bounds with
  approved requirements. Model constraints never widen approved limits.
- Missing approved parameters return `NEEDS_INPUT`; duplicate names, unknown
  feature references, unsupported versions/units, nonfinite values and conflicting
  bounds are rejected before creation.
- Relational expressions are explicitly rejected until they can be enforced on
  every subsequent proposal. Derived values, booleans and enumerations are not
  represented by Kerf's input schema and are not added by this adapter.
- Import parses source without executing it. This delivery executes generated
  source in the validated Docker profile, with no host-native fallback.

Docker previews now run in a separate restricted container with read-only geometry
and verification mounts. Preview failure is recorded in `view_error.json` and does
not change geometric acceptance. Cache reuse requires the same immutable worker
image ID and execution policy; each evaluation pins that image for all its stages.

Approved requirements can declare `parametric_tests`: bounded parameter patches
with explicit changed dimension or analytic Z-hole targets. Every other check
remains mandatory. Each scenario rebuilds an isolated input copy. `task_accepted`
requires nominal geometry and every declared response to pass; `finish`, search,
and the inference loop use this combined decision. `geometry_accepted` retains its
nominal meaning. Use `inspect PROJECT --scenario ID` for complete measurements.
These finite scenarios do not establish correctness across the whole parameter
domain. STEP remains geometry only, with no native Onshape feature tree.

For example, approve this field when preparing a new carrier requirement file
before import (the original `thickness` check remains 8.00 ±0.01 mm):

```json
"parametric_tests": [{
  "id": "thickness_10",
  "description": "Thickness becomes 10 mm; all hole interfaces stay fixed.",
  "parameters": {"thickness": 10},
  "overrides": [{
    "id": "thickness", "kind": "dimension", "part": "carrier", "axis": "z",
    "minimum": 9.99, "maximum": 10.01,
    "description": "Thickness 10.00 +/- 0.01 mm"
  }]
}]
```

Scenario overrides retain check identity, part, axis and tolerance width. Unknown
parameters, widened tolerances and unchanged geometric targets are rejected.
Up to 12 scenarios are supported. A no-op patch against current nominal parameters
fails the response gate. Existing requirements without scenarios retain nominal
acceptance; scenarios are never inferred from a proposed model or added to clear a
failed test.

## Baseline and remaining gates

The starting CADLoop commit is `9cb3531b9ac5d40850980a3e5141da24745a89db`.
All 242 files in the brief's recovered source inventory match it exactly. The
baseline full suite completed with **338 passes**, including clean process exit.
The first run crashed in VTK because `libegl1` was missing; Dockerfile now installs
it. Five synthetic CLI tests also required an executable temporary filesystem in
the test container. Use `--tmpfs /tmp:rw,exec,nosuid,nodev,size=1g` for those tests;
production worker permissions were not loosened.

The worker isolation probe exercised no network, read-only root/input, unprivileged
UID, no new privileges/capabilities, no account or Docker socket mounts, absent
host-sentinel environment, a 96-process limit, 2-CPU limit and a 3 GiB memory limit.
A host-only sentinel file stayed inaccessible. A real child process stopped after
the 5-second timeout, and its container was removed. The host
agent still has unrestricted workspace access: this is not a protected hidden
benchmark grader. No hidden-reference evaluation was run. CL-002 is therefore
only established for the local worker boundary, not an unattended evaluation host.

A clean macOS ARM64 Python 3.12.12 controller environment is installed at
`work/kerf-upgrade/macos-controller`; Kerf's separate macOS environments use frozen
lockfiles. Package versions and image IDs are recorded in the evidence directory.
Installation/metadata checks do not establish native macOS geometry performance;
geometry execution in this delivery used Docker.

The clean Linux worker build uses Python 3.13.15, CadQuery 2.8.0, Build123d 0.11.1,
cadquery-ocp 7.9.3.1.1 and VTK 9.6.2 on ARM64. Kerf's upstream tests completed:
29 harness tests, 12 sidecar tests and 11 schema tests. Harness tests use mocked
inference; sidecar tests ran inside Docker. These are correctness tests, not an
agent-performance benchmark.

The final CADLoop suite completed with **357 passes**, no skips/failures and exit
code 0 in 92.58 seconds, using a test image derived from the clean worker build.
It retains one upstream VTK/NumPy deprecation warning. The standalone Docker
carrier delivery passed all eight geometry checks and a fresh `finish` export.
See `work/kerf-upgrade/final/pytest-release.xml`, `isolation.json`,
`carrier-finish.json` and `delivery.json` for the recorded evidence.

CL-003 is limited to the existing approved requirement contract plus normalized
Kerf parameters. A new general TaskSpec, derived relationships and feature ledger
are not claimed complete. CL-004/006/007/008 are exercised by the carrier and
negative controls through existing independent checks and transaction machinery.
CL-009 runtime-aware container cache keys are implemented; a portable dependency
lock remains open. Final evidence is rebuilt with `finish`, never accepted from a
cached run.

## Repeatable parameter-response benchmark

```sh
.venv/bin/python scripts/benchmark_parametric.py --output work/response-benchmark --repeat 3 --seed 29
```

The runner freezes six synthetic sources, requirements, expected verdicts, hashes,
image ID and policy before scoring. It compares nominal-only and required-response
decisions from the same runs. Cases include ignored parameters and a thickness
change that moves protected mounting holes. It reports every attempt, false accepts,
false rejects, worker/controller times, and median/p95 wall time. Output directories
cannot be reused. This measures checker discrimination and execution overhead;
there are no model calls, model-quality claims or measured provider costs.

The supplied counterexample script also runs in Docker. Equal mass properties
still hide displaced holes; the explicit hole checker rejects them. No external
inference, paid-provider fallback, data collection, public benchmark submission
or training was performed. Further backlog items remain separately gated.
