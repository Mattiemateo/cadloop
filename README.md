# CADLoop 0.1.1

A working local CAD feedback harness: generate solids, inspect the **exported geometry** in a separate process, make a small revision-bound repair, and verify again.

**Kerf integration:** import a versioned Kerf spec and Build123d source into the existing independent verification/repair workflow. See [docs/KERF.md](docs/KERF.md) for installation, the carrier example, fresh export commands and current limits.

**Parameter-response gate:** completion can require measured parameter changes while preserving other interfaces. Docker cache entries include image/policy identity, and previews run in Docker. [Tests and benchmark results](docs/PARAMETRIC_RESULTS.md): 425 tests pass; the six-case synthetic benchmark reduces false accepts from 9 to 0 across three repeats, with measured execution overhead.

**Original v0.1.1 delivery:** CadQuery 2.8.0 / OpenCascade 7.9.3.1.1 on Linux, Python 3.13.5; Build123d was not exercised in that delivery. The Kerf integration above adds Build123d/Docker evidence. The planned `agentcad` integration remains unimplemented. See `docs/STATUS.md` for historical scope and `docs/KERF.md` for the new work.

**Adversarial audit:** 214 tests passed and 1 optional dependency test skipped in the expanded run. See `AUDIT.md` for reproduced bugs, regression coverage, measured overhead, and limitations. No live-model cost or quality result is claimed.

The included synthetic fixture starts with a missing spacer and an 8 mm plate gap where 12 mm is required. The demo detects the faults, searches bounded candidate gaps, and exports a corrected assembly. The tests also inject wrong holes, misalignment, interference, hidden geometry, stale revisions, tampered evidence, and worker failures.

## Account-based coding hosts: Codex or Cursor CLI

Both launchers are included. Use one coding host with CADLoop's local tools;
no second API-backed model loop is needed.

| Host | Sign in locally | Launch from this repository |
|---|---|---|
| Codex | `codex login` | `python3 scripts/start_codex.py` |
| Cursor CLI | `agent login` | `python3 scripts/start_cursor.py` |

Read the [Codex account guide](docs/CODEX_ACCOUNT.md) or
[Cursor account guide](docs/CURSOR_ACCOUNT.md). Cursor uses its own account,
not your ChatGPT/Codex entitlement. The Cursor launcher supports `--dry-run`,
`--check`, `--task`, `--model`, and `--mode plan` / `--mode ask`; it requests a
sandbox without force/auto-approval flags. It detects compatible `agent` and
`cursor-agent` executables. No model API key is requested.

```sh
python3 scripts/start_cursor.py --check
python3 scripts/start_cursor.py --task "Inspect work/manual and propose a minimal repair."
```

Cursor launch tests are offline contract tests, not real account/model calls.
See [the Cursor guide](docs/CURSOR_ACCOUNT.md#validation-scope) for the tested
scope. The original Codex launcher and CAD engine are unchanged.

The [CADGenBench protocol](docs/CADGENBENCH_PROTOCOL.md) is a plan, not a completed
benchmark. [Repository preparation notes](docs/GITHUB_PREPARATION.md) describe the
previous merged package; this package additionally includes Cursor support.
Credentials are not part of the repository.

## Run the demo

Python 3.12 or 3.13 is required. The delivered tests ran on 3.13.5; macOS and other interpreter versions have not been tested here.

```sh
cd cadloop
./scripts/bootstrap.sh
.venv/bin/cadloop doctor
.venv/bin/cadloop demo --directory ./work/plate-stack --trusted-native
```

The installer needs internet access. The demo itself does not need an API key, account or network connection. `--trusted-native` is an explicit opt-in to execute the included reviewed Python fixture **without a security sandbox**. Do not use this mode for untrusted generated source.

The demo writes `work/plate-stack/demo_result.json`, versioned `.cadloop/runs/` evidence, and an `exports/` folder containing:

* `geometry/assembly.step`, `assembly.brep`, and individual part BREP files;
* `input/design/` with the exact Python source and parameter snapshot;
* `verification/report.json` with every check and its numerical evidence;
* `views/overview.png` (depth-buffered rendering), a real BREP-derived axial section, and a self-contained `report.html`;
* content digests and execution information.

This is **nominal geometry acceptance, not engineering or fabrication approval**. It is a synthetic validation fixture, not a design for the user's actual drivetrain.

## Use it with a coding agent

Give your coding agent `AGENTS.md`. The CLI emits JSON; an existing coding host can operate it without adding another managed model subscription.

```sh
.venv/bin/cadloop init work/manual
.venv/bin/cadloop evaluate work/manual --trusted-native
# Exit 2 is expected: the initial model is deliberately broken.
.venv/bin/cadloop inspect work/manual --check plate_gap
.venv/bin/cadloop inspect work/manual --source
.venv/bin/cadloop context work/manual
```

Get the current revision with `state`, then submit a patch against that exact revision:

```sh
.venv/bin/cadloop state work/manual
.venv/bin/cadloop propose work/manual --base PASTE_REVISION_HERE \
  --set include_spacer=true --set gap_mm=12 --reason 'Restore the required spacer and plate separation.'
.venv/bin/cadloop finish work/manual --trusted-native
.venv/bin/cadloop view work/manual --kind report
```

`finish` performs a **fresh build and verification**, not a cached-pass lookup. Source edits are supported through an exact, unique text replacement in `propose --patch`; see `docs/TOOLS.md`.

For your own parts, create a **new** project from reviewed requirements and source:

```sh
.venv/bin/cadloop create work/my-part --requirements reviewed/requirements.json --design-dir reviewed/design
```

This does not overwrite or repin an existing project. The JSON requirement schema
is in `docs/requirements.schema.json`.

## Bounded search instead of repeated LLM guesses

```sh
.venv/bin/cadloop init work/search
.venv/bin/cadloop search-parameter work/search gap_mm \
  --values '[8,10,12,14]' --set include_spacer=true --trusted-native
```

Each candidate is rebuilt and independently checked. Duplicate candidates are validated then removed. A candidate wins only if the mandatory fresh final evaluation also passes. If none passes, the original parameters are restored and re-evaluated. There is a maximum of 12 search candidates, plus a final verification.

## Managed loop

A scripted replay tests orchestration with real geometry, without claiming to test LLM quality:

```sh
.venv/bin/cadloop init work/replay
.venv/bin/cadloop loop work/replay --replay scripts/replay_repair.json --trusted-native
```

An experimental, text-only Chat Completions-compatible adapter is included. Its HTTP contract and budget handling have mock tests, but **no live provider request or cheap-model benchmark was run**. Install `.[llm]`, configure your endpoint/model/current prices in a copy of `scripts/provider.example.json`, and explicitly confirm pricing before use. No model or tariff is silently chosen. Native managed loops are parameter-only; generated source edits require the Docker mode. Details: `docs/MODEL_LOOP.md`.

## Tests

```sh
.venv/bin/python -m pytest -q
```

`evidence/pytest.xml`, `evidence/pytest.log`, and `evidence/test_summary.json` record the actual delivered test run. The optional build123d test is skipped when that dependency is absent. Docker is a separately configured, unexecuted integration, not part of the native runtime test result.

## Supported checks

One nonempty valid solid per part, expected inventory, no extra free topology, axis-aligned dimensions, complete unsplit analytic Z-axis bores, through-depth, and a continuous inset bore-obstruction probe, actual cylindrical-axis alignment, BREP minimum distance with closest points, all-pairs Boolean overlap, named planar contact area, and BREP/STEP export consistency. Missing/failed/unsupported measurements block acceptance.

Through-hole checks use complete local circular rims adjoining outward-facing
axial planar faces, plus a clear lumen across the full part height. A remote
boss does not make a locally open hole blind; countersinks, partial openings,
and arbitrary tilted bores remain outside this supported check. The lumen
check does not certify continuous bearing-wall support around a side pocket.

For supported near-Z cylinder references, coaxial `max_offset` is the maximum
XY distance between the two axes over the combined Z span of their actual
cylindrical faces, measured at both span endpoints. It is symmetric and does
not depend on where either cylinder's mathematical axis origin was placed.
The separate `max_angle_deg` limit still applies. This is a nominal alignment
check, not dynamic shaft clearance or fit certification.
An optional cylinder-reference `center_xy` selects the axis position at the
midpoint of that cylindrical face's Z span, not its arbitrary surface origin.
The selected physical datum is included in the reference evidence.

Checks, approved bounds and requirements are outside the agent's patch interface. Receipt checks detect stale or modified artifacts within this workflow. **Hashes and separate processes are not a hostile-code security boundary**; read `docs/SECURITY.md`.

## What is not included

Native Onshape feature-tree publishing; a general build123d compiler; universal wall-thickness checking; motion/strength/fastener certification; physical kerf or fit calibration; automatic requirement discovery; strong-model escalation; portable part-level caching; a completed portable lockfile or cross-platform validation.

The local source and parameters remain editable. STEP contains geometry, not the original feature history. `Scene` records source/parameter hints for diagnosis, not a native parametric tree.

## Reproduce the additional audit

```sh
.venv/bin/python -m pytest -q
.venv/bin/python audit/run_shuffled.py --output-dir work/audit-repeat
.venv/bin/python audit/benchmark.py --output work/benchmark.json
.venv/bin/python audit/blocked_bore_demo.py --project work/blocked-bore --evidence work/bore-evidence
```

The last command executes the included reviewed fixture without a sandbox. The
benchmark compares identical hardened checks with and without transient query
memoization; it is not a claim about LLM speed or general assembly performance.

## Reusable parts and real task example

[608 bearing parts](parts/README.md) provide measured carrier, retainer and REV hex-sleeve solids; copy the module into a design before revision creation. The [BIOBUZZ shooter example](examples/biobuzz_shooter/README.md) includes a 3 mm plywood/printed shooter, cast silicone wheel mold, trajectory model, manufacturing exporter and independent BREP checks. Geometry acceptance retains explicit physical-validation blockers.

Generated models, exports, packages and run evidence stay local under ignored `work/` and `artifacts/` directories; editable design sources and reproduction scripts are versioned.
