# Tool contracts

Commands print one JSON object to stdout. Geometry-worker output is captured into
separate log files. Exit 0 means the command completed; `evaluate`/`finish` use exit
2 for an unaccepted design; exit 3 denotes invalid input or a controller error.
Managed-loop stops other than geometry acceptance return exit 2. A state/inspect
command returning exit 0 is not a geometry-acceptance claim.

## state PROJECT

Current content digest, parameter values, protected requirements and capabilities,
latest feedback, and whether that feedback belongs to the current revision.

## inspect PROJECT [--check ID | --part ID | --source]

Fetch one check's full evidence, one part's measured dimensions/volume, or a bounded source window. Use `--path helper.py --start-line 181 --max-lines 180`
to inspect a helper or continue a previous window; `next_start_line` is returned. No flag returns the complete report. Geometry requests
reject stale or tampered runs. Source inspection does not execute the source.

## propose PROJECT --patch patch.json

A patch is transactional and bound to its base revision:

```json
{
  "base_revision": "REPLACE_WITH_64_CHARACTER_CURRENT_DIGEST",
  "parameters": {"gap_mm": 12, "include_spacer": true},
  "edits": [],
  "reason": "Meet the protected gap and inventory requirements."
}
```

For a local source edit, use a Python path relative to `design/`, and an exact
`old` block that occurs once. Example:

```json
{
  "base_revision": "REPLACE_WITH_64_CHARACTER_CURRENT_DIGEST",
  "parameters": {},
  "edits": [
    {"path": "model.py", "old": "def spacer(length):", "new": "def spacer(length):\n    # Document the reviewed spacer interface."}
  ],
  "reason": "Local source annotation without rewriting the part."
}
```

The schema limits replacements to three Python-file edits of bounded size. It
checks path traversal, symlinks, ambiguity, syntax, source size and parameter types/bounds
before committing. Failed multi-edit/oversize proposals leave the design unchanged.
It does **not** prove generated code safe. Full JSON schemas are in this folder.

## evaluate PROJECT --trusted-native|--docker [--force] [--no-render]

Copy source/requirements into an input snapshot, build in a worker, independently
verify its output, produce feedback and seal the artifacts. Full-revision caching
requires an exact environment/source/requirement match and unchanged artifacts.
The execution mode must also match; successful native results never satisfy a
Docker request. Failed/timed-out workers and indeterminate reports are not reusable.
A missing native preview can be added in a new sealed checkpoint without rerunning
geometry; the original run is not modified. Rendering runs in a bounded child
process and failures are recorded separately. Docker preview remains disabled.
`--force` re-executes rather than trusting a prior result.

## view PROJECT [--kind report|overview|section_xz]

Returns the exact path to a revision-matched existing view; does not launch a
browser. Section XZ is the actual BREP intersection with world Y=0, not an inferred
sketch. It can be empty for geometry that does not cross that plane.

## search-parameter PROJECT NAME --values JSON_ARRAY [--set NAME=JSON] MODE

Try up to 12 approved parameter values, with optional fixed parameter changes.
All supplied candidates are validated, then duplicates are removed. Failed searches
restore starting parameters; handled exceptions restore them too. The controller
holds the project lock for the whole search. A hard process kill is not a completed
rollback transaction.
A final full evaluation is additional to the candidate evaluations. If it fails,
`FINAL_VALIDATION_FAILED` and exit 2 are returned; no feasible winner is claimed.
The original parameters are restored and reevaluated in that case. `final` retains
the rejected candidate's fresh validation evidence; `restored_final` holds the
restored design's feedback. This restoration adds one further evaluation.

## finish PROJECT MODE

Always rebuild and verify. Export only a geometry-accepted result. Engineering
approval remains false. The exported geometry and snapshots are useful even without
installing the harness; they do not contain a native CAD feature tree.

## context PROJECT [--include-source] [--source-edits]

A deterministic worker packet containing current parameters, allowed bounds,
requirements, named geometric reference definitions, compact blockers and an action
schema. Default parameter-only context omits source and unusable edit fields;
`--include-source` adds source, and `--source-edits` selects the source-capable profile. It does not include a
long transcript or every topology face. The managed loop is currently text-only;
external coding agents can request the image views separately.

## init versus new real projects

`init` intentionally creates the known demonstration, not an arbitrary design.
For a new engineering project, prepare a reviewed requirements JSON and a design
directory containing `model.py`, `parameters.json` and any helper Python modules.
Initialize a **new** project explicitly:

```sh
cadloop create work/my-bracket --requirements reviewed/requirements.json --design-dir reviewed/design
```

This anchors the provided requirements without executing the design. It refuses an
existing nonempty target and cannot repin an active project. Requirements can be
created by a human or drafted by an agent, but the human must review their adequacy.
The geometry gate only proves the implemented checks, not every unstated intention.
There is no agent-callable command to weaken requirements in an active task.
