# Design planning before CAD

Planning turns a short human request into reviewed engineering intent before
modeling starts. The account-authenticated Codex or Cursor agent expands the
request; CADLoop validates the proposal, ranks useful questions, records user
decisions, renders concept sketches and freezes an immutable contract. No model
API key, additional provider or autonomous planning loop is involved.

The frozen contract sits upstream of the existing `Requirements` schema. A
reviewed interpretation is not proof of correct CAD, strength, material, fit or
manufacturability. Existing independent BREP/STEP verification remains the
geometric acceptance gate.

## Workspace and lifecycle

`design-init` creates a `PlanningProject` without requiring `design/model.py` or
dummy CAD source. This keeps the legacy `Project` creation path unchanged.

| Status | Meaning |
|---|---|
| `DRAFT` | Initial brief or explicitly reopened intent. |
| `REVIEW_REQUIRED` | The proposal needs deterministic corrections before review. |
| `NEEDS_INPUT` | A blocking ambiguity or unapproved critical claim remains. |
| `REVIEWABLE` | The deterministic audit has no blockers; review the current sketches. |
| `FROZEN` | The user confirmed the current interpretation and the freeze gate succeeded. |

All mutation commands require the exact current planning revision. A stale
proposal or answer fails with `STALE_REVISION`; it never merges silently.
CADLoop owns the original brief, task identity, source history, accepted decisions
and status. The agent submits complete hypotheses rather than editing internal
files. Prior revisions are immutable and decisions are bound to their original
questions, options and resulting contract hashes.

Planning state uses the existing `.cadloop` area, atomic JSON writes, content
digests and controller lock:

```text
.cadloop/planning/
    state.json
    brief.json
    revisions/000000.json
    revisions/000001.json
    decisions.jsonl
    questions.json
    renders/<planning-revision>/
        front.svg
        side.svg
        top.svg
        manifest.json
    frozen/<frozen-planning-revision>/
        contract.json
        manifest.json
        modeling_context.md
        requirements_adapter.json
```

Freeze directories include the revision to preserve every previous frozen
artifact after reopening. A small state pointer selects the current immutable
revision. A transaction journal recovers interrupted controller writes. These
digests detect changes within the workflow; they are not a hostile-host security
boundary. No account credentials belong in planning data or generated workers.
Each committed revision, including its decision history, must fit the shared
4,000,000-byte JSON artifact budget. Oversized revisions fail before commit. V1
also bounds each workspace to 1,024 planning transitions; start a new workspace
when that limit is reached.

## DesignContract and provenance

The versioned `DesignContract` contains the brief and intent, sources, components,
interfaces, parameters, hard/soft requirements, structured constraints,
manufacturing instructions, optimization objectives, assumptions, decisions,
coordinate frames, diagram specification and verification intent. IDs are stable
strings, unique throughout the contract. References use those IDs rather than
list positions. Unknown fields, unresolved references, incompatible types,
inverted bounds and non-finite numbers fail validation.

| Provenance | Meaning |
|---|---|
| `USER` | Supplied human facts, initially recorded with the brief. |
| `ATTACHMENT_MEASURED` | An established measured attachment source. |
| `APPROVED_REFERENCE` | An established approved reference source. |
| `EXTERNAL_REFERENCE` | An external claim requiring explicit approval for critical use. |
| `MODEL_INFERRED` | A model hypothesis, retained as such until a user decision approves it. |
| `DEFAULT` | A declared default or design choice. |

An agent cannot create new `USER`, `ATTACHMENT_MEASURED` or
`APPROVED_REFERENCE` authority in a proposal, alter existing source records, or
mark an assumption accepted. Use external/inferred provenance for new claims and
present an explicit decision. An option's `approved_source_refs` can record user
approval of referenced evidence without changing the original source kind.
Approval is a recorded decision, not proof that an external specification is
accurate. Hard requirements need source provenance. Critical inferred or external
dimensions and relationships cannot silently become accepted ground truth.
An option that only approves evidence may have no parameter updates; it must
declare the approved source IDs. Empty choices with neither updates nor source
approval are rejected.
The controller checks source references and recorded approvals; it does not
automatically prove that a prose source entails every extracted fact. Review the
interpretation and canonical values before freezing.

## Parameter freedom is explicit

| Mode | Meaning | Example |
|---|---|---|
| `FIXED` | Preserve the reviewed value. | Supplied motor square size. |
| `BOUNDED` | Choose within approved limits; one-sided bounds are allowed in planning. | Wall thickness at least a reviewed minimum. |
| `DERIVED` | Preserve a relationship to named parameters. | A feature position derived from an approved axis. |
| `FREE` | The CAD agent may choose. | Noncritical cosmetic fillet. |
| `OPTIMIZED` | Choose to satisfy an explicit objective. | Minimize envelope while retaining interfaces. |

Numeric parameters reuse `mm`, `deg` and `count`; booleans use `boolean`; enum and
string parameters use `text`. Values are typed rather than coerced from strings.
The `editable` flag records which parameters should remain exposed to later CAD
authoring. A missing `FIXED` value is an unresolved fact; an unspecified `FREE`
value is legitimate freedom. `DERIVED` references and structured relationships
are instructions for modeling, not arbitrary Python expressions to execute.

Keep requirements separate from implementation choices. “Must be stiff” does
not mean “wall thickness is six millimeters.” Record loads, material and strength
verification separately when available; retain the engineering blocker otherwise.

## Questions and transactional answers

The external agent proposes decision candidates. The controller selects the
questions using:

```text
score = (1 - confidence) * impact_weight * change_cost_weight

impact weights:      LOW .25, MEDIUM .50, HIGH .75, CRITICAL 1.00
change-cost weights: LOW .40, MEDIUM .70, HIGH 1.00
default threshold:   .18
```

Critical unknown interfaces, missing mating dimensions, ambiguous topology,
unapproved critical inference and source conflicts affecting hard requirements
override the threshold. Cosmetic choices and explicit `FREE`/`OPTIMIZED` freedom
normally do not generate questions. The controller returns at most three per
round, with deterministic ranking and ID tie ordering. It aims for two rounds;
remaining blockers after that remain `NEEDS_INPUT`.

Each question has two to four stable option IDs, concise consequences and one
recommendation unless a genuine source conflict prevents it. An answer applies
the selected option's predefined updates transactionally. V1 accepts only `set`
operations on allowlisted parameter fields, interface `resolved` and assumption
`accepted`. Paths identify objects by ID:

```json
{
  "op": "set",
  "path": "/parameters/motor_orientation/value",
  "value": "shaft_outward"
}
```

Array indexes, arbitrary paths, Python and execution payloads are unsupported.
Answering multiple active questions commits one revision; stale/unknown questions,
invalid options, duplicate answers and conflicting update paths reject the entire
batch. Accepted choices cannot be silently undone by a later agent proposal.
This protection includes the selected parameter's kind, units, mode, bounds,
enum choices and derivation/objective semantics, not just the selected scalar.
Changing those semantics requires a new explicit decision or reopening the plan.

## Concept sketches and freeze

`DiagramSpec` uses normalized layout coordinates from zero to one thousand,
separate from real engineering dimensions. Front/side/top views support
rectangles, circles, lines, axes, arrows, dimensions, labels, keepouts, motion arcs
and component envelopes. Engineering annotations reference canonical parameter,
component or requirement IDs. No independent dimension text, arbitrary SVG/XML,
remote resources or scripts are accepted. Text is escaped; invalid XML characters
are rejected. The same contract produces byte-identical SVGs.

Geometric enum choices use `diagram_spec.variant_sets`: each set declares an
`id`, a canonical enum `parameter_ref`, and `cases` mapping supported enum values
to complete front/side/top primitive layers. The renderer adds the selected layer
to the shared `views`; `design-answer` selects it through the parameter update,
without parsing the option's label or description. Case IDs and references are
validated even in unselected layers. Each case must contain actual geometry and
different cases cannot differ only in labels, dimensions or ignored fields.

An unresolved binding displays an incomplete-geometry notice and blocks freeze.
A selected value without an authored case blocks both rendering and freeze;
there is no silent fallback to another option. Static diagrams remain supported
with byte-compatible serialization. Only explicitly bound enum geometry is
dynamic: ordinary labels and numeric dimensions do not generate or scale CAD.
The author must supply reviewed layers for each supported geometric alternative.
These normalized sketches do not establish dimensions, fit or manufacturability.

After any proposal or answer, old sketches remain with their old revision and do
not count as current review. Render the new revision and show it to the user.
`design-freeze --base REVISION` requires a clean deterministic audit and valid
renders for that exact revision. Submit freeze only after the user confirms that
interpretation. Calling the command records this confirmation; CADLoop cannot
prove that a person actually looked at the sketches.

Freeze creates a new `FROZEN` revision and a manifest with the contract, brief,
decision-log and render hashes, the reviewed revision/render hashes and a
timestamp. `design-handoff` verifies these artifacts before returning them.
`design-reopen` preserves the old freeze, creates a new `DRAFT`, resets current
decision/assumption approvals and invalidates downstream currency.

## Modeling handoff and narrow Requirements adapter

The modeling agent receives the frozen contract plus `modeling_context.md`; the
full planning conversation is unnecessary. The deterministic handoff orders goal,
intent, references, frames, interfaces, hard requirements, canonical parameter
values/modes, objectives, manufacturing/access, keepouts, editable parameters,
protected requirements, verification intent, approved assumptions and prohibited
interpretations. Important values are emitted from canonical parameters; other
sections refer to their IDs.

`requirements_adapter.json` contains a proposed existing `Requirements` object
when supported checks exist, plus explicit unsupported items. It does not replace
the verifier or claim that every sentence is geometrically enforceable.

| Explicit verification intent | V1 translation |
|---|---|
| `dimension` | One registered component ID, global axis and a fixed numeric `mm` target with tolerance, or both approved bounded limits. |
| `clearance` | Two registered component IDs and an approved nonnegative minimum-clearance parameter, optionally with an upper bound. |
| `through_holes_z` | One registered component ID with explicit fixed global X/Y centers, positive radii and a supported tolerance. |
| `manual` or unsupported target | Retained in the handoff and engineering blockers; never converted into an invented check. |

Component IDs used by the adapter must map to registered CAD part IDs. Axes and
hole coordinates use the existing verifier's global CAD frame in `mm`; V1 does
not transform local frames, solve derived hole positions or infer fit clearances
from nominal fastener sizes. Existing boolean parameter schemas cannot enforce a
fixed truth value; such enforcement remains explicitly unsupported rather than
being silently exposed as an unrestricted boolean.

The existing numeric parameter schema also requires both finite bounds. A
one-sided `BOUNDED` planning parameter remains in the handoff but blocks
materialization until a reviewed planning revision supplies the other bound.
The adapter never drops the approved limit or invents the missing one. This
restriction applies even when the parameter's impact is below `CRITICAL`.

`design-materialize` imports reviewed CAD source into the same frozen workspace,
then uses ordinary `Project` build/repair/finish operations. Mandatory unsupported
geometric intent blocks materialization. Supplying `--requirements` cannot bypass
that blocker. Optional reviewed requirements may add checks but must preserve all
compiled targets, approved bounds and engineering blockers. Every unsupported
intent marked `geometry_required: true` is mandatory, regardless of its linked
requirement's impact or whether requirement references were supplied. Resolve
unsupported mandatory intent through reviewed planning revisions before
materialization.
Before import, the controller also checks an older frozen contract with the
current adapter rules. Previously omitted bounds or mandatory checks cannot
bypass a fail-closed fix through cached adapter output. The original freeze,
rendered review and artifact hashes remain unchanged.
The import has a recovery journal and writes the existing project anchor last as
its commit marker. An interrupted import is recovered under the shared controller
lock; only unchanged, hash-matching partial files owned by that import may be
removed. Changed partials fail rather than being silently deleted.

The project anchor, CAD revision inputs, runs and exports bind
`design_contract_hash` and `design_contract_revision`. Reopening or changing the
plan marks the old CAD stale and blocks repair/evaluation/completion against new
intent. Refreezing does not relabel that CAD. Start a new workspace for CAD
belonging to changed intent; V1 does not rebind an existing materialized project.
Legacy projects with no planning binding retain their existing workflow.
Planning state and downstream provenance checks use the same controller lock as
mutations; a frozen manifest is verified before planned CAD work continues.

## CLI workflow

All planning commands emit JSON by default. `design-audit` and `design-freeze`
return a nonzero status when blocked. A valid draft proposal can be accepted while
its returned status is `NEEDS_INPUT`; proposal acceptance is not freeze acceptance.

```sh
.venv/bin/cadloop design-init work/motor-mount \
  --brief-file benchmarks/planning/fixtures/motor_mount/lazy_brief.txt
.venv/bin/cadloop design-state work/motor-mount
.venv/bin/cadloop design-context work/motor-mount

# The account agent authors a PlanningProposal from context using its exact base.
.venv/bin/cadloop design-propose work/motor-mount \
  --base INITIAL_REVISION --file work/motor-mount-proposal.json
.venv/bin/cadloop design-questions work/motor-mount
.venv/bin/cadloop design-render work/motor-mount --base PROPOSED_REVISION

# Show the proposal/sketches and record only the user's selected options.
.venv/bin/cadloop design-answer work/motor-mount --base PROPOSED_REVISION \
  --answer motor_orientation_question=shaft_outward
.venv/bin/cadloop design-audit work/motor-mount
.venv/bin/cadloop design-render work/motor-mount --base ANSWERED_REVISION

# After the user confirms these current sketches:
.venv/bin/cadloop design-freeze work/motor-mount --base ANSWERED_REVISION
.venv/bin/cadloop design-handoff work/motor-mount
.venv/bin/cadloop design-handoff work/motor-mount --format markdown
```

Replace each revision placeholder with the actual revision returned by the
preceding command. Optional `--brief TEXT` replaces `--brief-file`.
`design-propose --file -` reads a proposal from stdin. Multiple `--answer` options
submit one answer transaction. `design-render` can omit `--base` to render current
state; supplying it guards against an unintended newer revision.

After supported mandatory geometric intent and reviewed source are ready:

```sh
.venv/bin/cadloop design-materialize work/my-part --base FROZEN_REVISION \
  --design-dir reviewed/design --requirements reviewed/requirements.json
.venv/bin/cadloop state work/my-part
.venv/bin/cadloop evaluate work/my-part --docker
.venv/bin/cadloop finish work/my-part --docker

# Explicit intent revision; the existing CAD then belongs to the previous freeze.
.venv/bin/cadloop design-reopen work/my-part --base FROZEN_REVISION \
  --reason 'User changed the mounting interface'
```

Materialization imports source; it does not execute it. Use the existing validated
Docker profile for generated source. Native execution is not a sandbox, and the
existing account-host/generated-source rules still apply.

## Synthetic vertical slice and evaluation

Run the offline planner replay in an empty directory:

```sh
.venv/bin/python scripts/demo_design_planning.py \
  --directory work/design-planning/motor-mount-demo
```

It binds the versioned synthetic fixture to the new workspace, submits the
proposal, selects the oracle's outward orientation, renders three views, freezes
and returns the modeling handoff. The supplied motor square, extrusion square,
mounting pitch and shaft-clearance diameter come exclusively from the synthetic
brief; no external motor family specification is inferred. One orientation
question is expected. The oracle's choice is test data, not a real user approval.

This fixture deliberately retains unsupported mandatory bore/pitch checks because
nominal M3 hardware does not supply print-fit bore radii or approved hole-center
targets. It proves the planner path through freeze/handoff. It does not prove
that this mount can be materialized or fabricated without further specification.
Separate integration tests exercise supported planning-to-CAD provenance.

[The planning benchmark protocol](../benchmarks/planning/README.md) defines a
future matched comparison between a short brief, an expert prompt and a planned
brief using the same CAD agent and verifier. The eventual target is at least
95 percent of expert-prompt verified success with at most three questions and
30 seconds of human clarification. No live-model evaluation or improvement claim
is made by this implementation.

V1 excludes image understanding/generation, component lookup, STEP semantic
decomposition, 3D concept proxies, browser UI, CAD IR, Onshape publishing,
strength/FEA approval and general engineering certification. Planning schemas,
closed render primitives and explicit verification intents are the extension
boundaries; an additional provider loop is unnecessary.

## Implementation validation

The preimplementation baseline passed **431 tests**, with zero failures and
zero skips, in 140.18 seconds. The final complete suite passed **588 tests**,
with zero failures and zero skips, in 157.44 seconds. Both runs used the existing
`cadloop-upgrade-tests:current` image with no network, a read-only source snapshot,
dropped capabilities and bounded resources. The local controller venv lacked
pytest/CAD dependencies. One existing VTK/NumPy deprecation warning remains.

The 157 new cases cover strict contracts, provenance, scoring, safe updates,
atomic history and crash recovery, escaped deterministic SVGs, freeze/reopen,
handoff, CLI, the exact motor fixture, legacy behavior and downstream CAD binding.
A supported synthetic project also completed a real CAD build, independent
verification and fresh export, then rejected stale CAD after reopening.

The offline fixture reached `DRAFT -> NEEDS_INPUT -> REVIEWABLE -> FROZEN` after
one outward-orientation answer; no active questions remain. Its three SVGs were
rendered and visually inspected. CLI materialization correctly rejected the
fixture's unsupported mandatory geometric checks without changing the plan.

Local, ignored evidence is under `work/design-planning/`: `baseline.xml`,
`final.xml`, `verification_summary.json`, `demo-final.json` and
`materialization-block.json`. The demonstrated workspace is `motor-mount-final/`;
its revision-specific render and frozen-context paths are in `demo-final.json`.
These are infrastructure results, not a matched live-model quality benchmark.
