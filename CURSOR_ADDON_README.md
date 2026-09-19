# Cursor CLI add-on for CADLoop

Added September 19, 2026, to the previously supplied CADLoop GitHub-ready package.
The core package remains v0.1.1. This is an additional coding-host launcher, not
a new CAD engine or a claim of autonomous modeling quality.

## What changed

- `scripts/start_cursor.py`: supervised account-login launcher with optional
  task, model and mode; dry-run and preflight checks; exact flag detection;
  sandbox request; no API-key or unattended/force-mode flags.
- `docs/CURSOR_ACCOUNT.md`: setup, usage, security limits and official sources.
- `tests/test_cursor_launcher.py`: 105 new offline test cases.
- Shared `AGENTS.md`, README and status text recognize either Cursor or Codex.
- Local Cursor configuration is excluded from Git and Docker build contexts.
- Evidence and package manifests are refreshed without rewriting old audit results.

All 24 compared core-source/package/Codex files are byte-identical
to the GitHub-ready input. Both hosts use the same CADLoop commands and checks.

## Install / upgrade

The full ZIP is a complete project folder. The add-on ZIP contains only additions
and changed files **relative to CADLoop_GitHub_Ready.zip**, with a `cadloop/` root.
Merge that folder into an unchanged copy of the same baseline, or review the files
first when your working copy has local changes. Do not blindly overwrite custom
README/AGENTS/ignore rules. The full ZIP is simpler for a fresh checkout.

The add-on is not standalone and does not install the base v0.1.1 package or the
Codex add-on into a differently assembled tree. A merge with the exact baseline
was verified to reproduce every file in the full ZIP.

```sh
agent login
cd /path/to/cadloop
python3 scripts/start_cursor.py --check
python3 scripts/start_cursor.py --task "Inspect the project and propose a minimal CAD repair."
```

Read `docs/CURSOR_ACCOUNT.md` first. Cursor uses a Cursor account, not ChatGPT
Business/Codex entitlement. No model API key is requested or bundled. The original
`scripts/start_codex.py` remains unchanged. User account usage limits still apply.

## Tests and limitations

Launcher suite: **123 passed** (105 Cursor, 18 Codex).
Complete installed-checkout suite: **337 passed, 1 skipped**.
The skip needs unavailable build123d. This includes actual local CAD checks,
but Cursor tests use mocks and a synthetic executable, not a real Cursor service.
No live Cursor login, inference, billing, sandbox effectiveness or CADGenBench
result is claimed. The initial uninstalled-checkout failure and its environment
correction are recorded, not hidden. Details: `evidence/cursor_addon/`.

## Integrity and publication

`SOURCE_MANIFEST.json` covers every packaged file except itself.
`MANIFEST.sha256.json` covers payload files except both root manifests, avoiding
a circular hash dependency. Original root manifests are retained as historical
inputs under `evidence/cursor_addon/previous_*`; do not use those old snapshots
to verify this update. The original Codex ADDON_MANIFEST remains unchanged.
These are integrity checks, not signatures or security certification.

This package was created in the conversation container. It has not been pushed
to GitHub or installed on the user's computer.
