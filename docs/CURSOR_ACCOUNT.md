# CADLoop with Cursor CLI

This adds a supervised Cursor entry point alongside the existing Codex launcher.
The CAD engine, validators, project format and Codex launcher are unchanged.
Cursor owns the conversation and model calls; CADLoop supplies local tools.

**Use your Cursor account.** This does not use your ChatGPT Business/Codex
entitlement. It does not need a provider API key, does not provide unlimited
usage, and does not impose an account spending limit. Review your Cursor plan
and usage controls yourself. The CADLoop managed API-cost ledger cannot cap
an external CLI session.

## Quick start

Install the official Cursor CLI on your computer using its official installation
instructions (sources below), then authenticate locally:

```sh
agent login
agent status
cd /path/to/cadloop
python3 scripts/start_cursor.py --dry-run
python3 scripts/start_cursor.py --check
python3 scripts/start_cursor.py
```

`--dry-run` starts no subprocesses and checks neither installation nor login.
`--check` probes help and saved login, but starts no model inference and does not
build CAD. The normal launch requires an interactive terminal.

The current executable name is `agent`. The launcher also tries `cursor-agent`
when present, checking that its help describes a compatible Cursor CLI. An old
binary missing `--workspace` or `--sandbox` is rejected: update the official CLI
rather than silently dropping the sandbox request. A conflicting generic
`agent` program is rejected; use an explicit executable when needed:

```sh
python3 scripts/start_cursor.py --cli "$HOME/.local/bin/cursor-agent" --check
```

With an installation whose binary is only `cursor-agent`, use
`cursor-agent login` and `cursor-agent status` for the first two commands too.

## Start with a task or model

```sh
python3 scripts/start_cursor.py \
  --task "Inspect work/manual, explain its failing checks, and propose a minimal repair."

python3 scripts/start_cursor.py --mode plan \
  --task "Plan a bearing-carrier project. Identify missing dimensions before modeling."

# Optional: select an actual model ID shown by your installed CLI/account.
agent models
python3 scripts/start_cursor.py --model YOUR_AVAILABLE_MODEL_ID
```

Omitting `--model` preserves Cursor's configured/default choice. The launcher
supports default agent mode and explicit `plan` or `ask`; it does not invent a
model ID or automatically change to a premium model. Use your CLI's model picker
when the `models` subcommand is unavailable on an older installation.

`--task` is optional, bounded UTF-8 text. It is passed as one argument without a
shell, including when it contains quotes or punctuation. Arguments can be visible
to other local processes; never put credentials in a task. `--repo` defaults to
the repository containing the launcher. No need to launch from its root.

## How Cursor operates the harness

Cursor reads the shared `AGENTS.md`; there is intentionally no second copy of
the CADLoop policy under `.cursor/rules`. Its startup brief directs it to:

1. Inspect the active project and compact measured feedback before fetching source.
2. Prefer bounded parameter search or a feature-local patch over repeated guesses.
3. Preserve requirements and checkers, then call `finish` for fresh verification.

See `docs/TOOLS.md` for the real CLI interfaces. This launcher does not turn the
fixture into a general drawing-to-CAD solver or add new geometry checks. Existing
projects can be used by either coding host; do not run both on the same working
tree concurrently. `scripts/start_codex.py` remains available unchanged.

## Authentication and permissions

The launcher removes `CURSOR_API_KEY`, `CURSOR_AUTH_TOKEN`, `OPENAI_API_KEY`,
`CODEX_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` and `GEMINI_API_KEY` from
its child environment, without modifying your shell. It never accepts a key/token
argument or reads, writes, uploads or logs a credential file. Cursor itself uses
its locally stored login. Clear Cursor overrides in your shell before logging in
when needed:

```sh
unset CURSOR_API_KEY CURSOR_AUTH_TOKEN
agent login
```

Preflight requires successful `status` output explicitly indicating login. It
rejects negative, ambiguous, unrecognized, and explicit key/token-auth output.
Raw account/status output is not printed or saved by this launcher. Current
Cursor docs do not define a stable text status schema or a Codex-style forced
browser-only flag. Therefore, successful preflight confirms CLI status with the
documented environment overrides removed; it does **not** independently inspect
or attest to Cursor's opaque credential storage. Status-format changes can
require a small parser update rather than allowing an unchecked fallback.

The launcher requests `--sandbox enabled` and never adds `--force`, `--yolo`,
`--trust`, `--approve-mcps`, `--print`, endpoint overrides or TLS bypass flags.
It does not change global/project configuration or auto-approve tool prompts.
Existing Cursor permissions, hooks, plugins and MCP configuration may still
apply; review those before trusting a workspace. This is a supervised workflow,
not a hardened security boundary. Cursor's sandbox behavior is not live-tested
by this add-on's offline tests.

An agent able to edit this repository can also edit its checkers. `AGENTS.md` is
instruction, not access control. Put the validator, requirements and references
outside the agent's writable area for an unattended benchmark. Do not mount
account caches into generated-code workers. Native CAD execution requires reviewed
code and explicit consent; Cursor's shell sandbox is not proof of validated
CADLoop worker isolation. See `docs/SECURITY.md`.

## Troubleshooting and exit codes

| Code | Meaning |
|---|---|
| 0 | Check/dry run succeeded, or interactive child exited normally. |
| 2 | Invalid repository, model, task or arguments. |
| 3 | Login not confirmed; no inference started. |
| 4 | Installed executable is not a compatible Cursor CLI. |
| 5 | Interactive launch requested without a terminal. |
| 124 | Help/login probe timed out. |
| 126 | OS-level launch failure. |
| 127 | No candidate executable on PATH. |
| 130 | Interrupted by the user. |

A launched child's nonzero code is forwarded, so it can overlap these launcher
codes; use the accompanying message to distinguish them. On POSIX, child signal
termination is translated to `128 + signal`. No automatic paid retry is made.

## Validation scope

See `evidence/cursor_addon/test_results.json` for the actual test run. Tests use
mocks and a temporary fake CLI executable, not a real Cursor service. An actual
Cursor binary was not installed here, and the download attempt failed with DNS
resolution blocked. No live Cursor login, inference, billing, macOS integration,
or CADGenBench comparison is claimed. Existing test records remain historical;
this add-on is not evidence of improved autonomous modeling performance.

## Official sources checked September 19, 2026

- Installation: https://cursor.com/docs/cli/installation
- Authentication: https://cursor.com/docs/cli/reference/authentication
- Parameters, sandbox options and modes: https://cursor.com/docs/cli/reference/parameters
- Shared AGENTS.md and CLI operation: https://cursor.com/docs/cli/using
- Permission configuration: https://cursor.com/docs/cli/reference/permissions
- CLI account/subscription context: https://cursor.com/blog/cli

These establish intended integration contracts, not a successful live run.
