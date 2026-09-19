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
