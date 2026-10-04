# Operating CADLoop

Use the CLI or Python API. Do not edit `.cadloop/`, requirements, validators, receipts,
reference data, or acceptance flags to make a task pass. Do not execute arbitrary
Python supplied as an `inspect` expression; that interface does not exist.

1. Read `state`. Request source only when needed to understand or edit a feature. Evaluate the baseline in the execution mode
   the user approved. Native execution is not a sandbox.
2. Inspect the specific failed check. Check dimensions and interfaces from the
   measured evidence, not from a nominal parameter variable.
3. Prefer a parameter patch. Reuse named part functions before writing new code.
   Every proposal must contain the exact current base revision.
4. Keep corrections local. For simple dimension choices, use `search-parameter`
   rather than repeatedly guessing. Never change hardware bounds to clear a test.
5. Reevaluate. If a reference is ambiguous, a solid is invalid, or the kernel fails,
   fix that cause; indeterminate is not pass. Use the axial section when necessary.
6. Call `finish`; the controller rebuilds and rechecks. Link the actual export and
   clearly retain engineering/process blockers. A pretty render is not evidence of
   strength, manufacturability, correct material, or dynamic clearance.

Internal explanations should be brief, with complete units and numerical limits.
No code golf, vague "looks fine", or unsupported claims of model intelligence.
There are no known provider costs until the user configures and verifies them.

For managed inference, only parameter changes are allowed in native mode. Source
edits require the Docker profile after its isolation has been validated locally.
An external coding agent may itself have unrestricted filesystem/shell access;
CADLoop cannot control that host's permissions or total token spending.

In parameter-only mode, `context` omits source and source-edit schema fields. Use
`context --include-source` when understanding implementation is necessary; use
`inspect --source --path helper.py --start-line 181 --max-lines 180` for a specific
source window. Preserve the full requirement values, units, and numerical evidence.

Use `progress_key` only as a repair-scheduling hint. It never authorizes acceptance.
A search that returns `FINAL_VALIDATION_FAILED` did not succeed, even if an earlier
candidate passed. Renderer failure is separate from geometric failure; inspect
`view_error.json` rather than assuming a preview exists.

## Account workflow for this repository

Use the account-authenticated host chosen by the user: Codex or Cursor CLI.
For Codex, read docs/CODEX_ACCOUNT.md; for Cursor, read docs/CURSOR_ACCOUNT.md.
Do not switch hosts or configure/start the separate API-provider loop unless the
user explicitly requests it. Cursor uses a Cursor account, not ChatGPT entitlement. Do not read, copy, commit or mount account tokens into generated-code
workers. The included CADGenBench document is a protocol, not a benchmark result.

## Planning from a short request

For new work that starts with a natural-language brief, use the planning workflow
in [docs/DESIGN_PLANNING.md](docs/DESIGN_PLANNING.md). Existing projects with
reviewed requirements/source and no planning metadata keep their current flow.

1. Run `design-init` in an empty workspace; it needs no CAD source. Read
   `design-context` before constructing a `PlanningProposal`.
2. Expand the intent, components, interfaces and verification intent. Use
   canonical parameter IDs with explicit `FIXED`, `BOUNDED`, `DERIVED`, `FREE` or
   `OPTIMIZED` modes and source provenance. Treat cosmetic choices and declared
   optimization freedom as design freedom rather than missing human input.
3. Submit `design-propose` with the exact current base revision. Preserve the
   controller-owned brief, task, sources, decisions and status. Do not edit
   `.cadloop/planning/` or mint new user/approved-reference authority.
4. Inspect `design-audit`, `design-questions` and `design-render`. Show the user
   the interpretation, current front/side/top SVGs and up to three ranked
   questions. Record only the options the user explicitly selected with
   `design-answer`; never reinterpret a letter by changing its predefined updates.
5. Optionally revise the hypothesis once. Reaudit and rerender the resulting
   revision. Unresolved critical issues remain blocking after two review rounds.
6. Call `design-freeze` only after the user confirms the exact current rendered
   interpretation. A draft proposal's successful exit is not freeze acceptance.
7. Read `design-handoff` and the frozen contract before CAD authoring. The handoff
   preserves all unsupported checks and engineering/process blockers. Never
   bypass unresolved critical planning issues by inventing a dimension in CAD
   source, and never substitute an implementation choice for a user requirement.
8. Resolve mandatory unsupported geometric intent through reviewed planning
   revisions. Then use `design-materialize` to import reviewed CAD source into
   the frozen workspace and continue the ordinary build/verify/repair/finish
   workflow in the authorized execution profile.

Planning revisions and downstream CAD revisions are distinct. Read the relevant
state before each mutation. Reopening the design preserves the old freeze and
marks materialized CAD stale; do not rebind that CAD to a new contract hash.
Use a new workspace for CAD belonging to changed intent. Account credentials,
live-model costs and a second autonomous provider loop are not planning inputs.
