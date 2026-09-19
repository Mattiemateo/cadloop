# Cursor integration evidence

The added launcher uses the existing CADLoop core unchanged. Official CLI docs
were read on September 19, 2026; source links are in docs/CURSOR_ACCOUNT.md.

`initial_failures.log` records two bugs in the new launcher during development:
an underscore-boundary miss for CURSOR_API_KEY, and a substring match that mistook
--model for --mode. Both were fixed and retained as regression tests before the
successful launcher and full-suite runs. These are not bugs attributed to Cursor.

`launchers.xml` / `.log`: Cursor and existing Codex launcher tests.
`full_suite.xml` / `.log`: complete combined CADLoop test run.
`core_identity.json`: exact comparison with the uploaded GitHub-ready archive.
`availability.json`: actual CLI availability and failed installer retrieval.
`real_cli_probe.*`: the real launcher returning CLI-not-found in this environment.
`dry_run.json`: a launcher plan, not a live account session.

Mock help/status payloads and the temporary executable are synthetic fixtures.
They do not establish real CLI authentication, account billing, model quality,
sandbox effectiveness, or support for every historical status output format.
No authentication caches, API keys, tokens or user account details are included.

All pre-existing CADLoop test/audit records remain historical. They are not
relabeled as new Cursor results. This is not a CADGenBench evaluation.

The first full run from the uninstalled source tree had one child-import failure
(`before_install.*`). A direct import reproduced ModuleNotFoundError. This checkout
was then installed editable with --no-deps --no-build-isolation using the existing
CAD dependencies. The entire suite was rerun; `full_suite.*` are that result. No
core/test changes were made to turn the lock check green. This is not a clean
network installation test.
