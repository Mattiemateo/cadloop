# CADLoop with your ChatGPT Business / Codex account

Status: local supervised launcher and operating instructions. The launcher is
covered by subprocess mocks; no live Codex login, inference, macOS run, or
CADGenBench evaluation has been performed in this environment. The CADLoop core
is unchanged from v0.1.1. This add-on is not a new validated CAD release.

## The correct ownership of the loop

Use **Codex as the agent, CADLoop as local tools**:

```
Your existing ChatGPT Business account
    -> official Codex CLI (login and model calls owned by Codex)
       -> CADLoop CLI (build / measure / inspect / propose / finish)
          -> local CAD workers and independent geometry checker
```

Do not run `cadloop loop --provider ...` for this workflow. Do not configure
`provider.example.json`, install the `llm` extra, or pay for another model API.
The scripted replay remains useful for testing orchestration, not model quality.
An MCP interface is optional future work; the existing JSON CLI is sufficient
for supervised Codex operation. Do not add a second AI planner around Codex.

## Start on your computer

Install the official Codex CLI if it is not already installed. Use the official
installation guide below. Complete the browser login locally:

```sh
codex login
codex login status
cd /path/to/cadloop
python3 scripts/start_codex.py --dry-run
python3 scripts/start_codex.py
```

Select the Business workspace where available and verify it in Codex's account
UI. Optional model selection: `python3 scripts/start_codex.py --model MODEL_ID`.
Use an actually available account model; this add-on does not invent a default.
If an old API-key login is active, sign out and sign in with ChatGPT locally.
Never upload `~/.codex/auth.json` or copy its tokens into CADLoop.

The launcher removes OPENAI_API_KEY and CODEX_API_KEY from its child's environment,
selects the built-in OpenAI provider, sets forced_login_method="chatgpt", checks
login status, and opens a supervised workspace-write session. Unknown login status
fails closed. It does not install software, auto-log in, read credential files,
fall back to another provider, enable bypass flags, or change global Codex config.
Its status parsing is conservative and may need updating if CLI wording changes.
The dry run does not prove installation/authentication works.

ChatGPT login consumes your plan/workspace entitlement. It is not unlimited and
not necessarily zero incremental spend: workspace credit settings and your seat
matter. Check included usage and workspace spending controls in the actual account.
Do not convert API list prices into claimed subscription savings. Record time,
retry count, tool calls and Codex-reported tokens/usage where available.
CADLoop's API-dollar ledger cannot cap an external Codex session's usage.

## Security boundary: read before running generated code

The launcher is for **supervised local use**, not an unattended isolated benchmark.
Workspace-write lets Codex modify the repository, including its checkers. AGENTS.md
and prompt instructions are not access controls. CADLoop hashes detect accidental
changes within its intended workflow; they cannot defend against an agent with
write access to both the policy and its anchor. Review diffs and never count edits
to validators/requirements as successful CAD repair.

`--trusted-native` is permitted only for reviewed code with your explicit consent.
For unattended generation, first validate separate build isolation and mount the
checker/requirements/reference data outside the agent's writable area. Do not
mount Codex auth caches into generated-code workers. Docker's daemon socket is
privileged; exposing it broadly to an agent is not sufficient isolation.
No `--yolo`, `danger-full-access`, auto-approval, or public CI credential workflow
is configured by this add-on.

## CADGenBench

Read CADGENBENCH_PROTOCOL.md. The benchmark protocol is specified, not executed.
The existing Python fixtures and 214-test report are not CADGenBench results.
Using the public validity script on a fixture would still not measure drawing
reconstruction or establish an official CAD Score.

For future controlled runs, `codex exec --json` can record event/usage output and
uses saved CLI auth. Preserve the same forced ChatGPT-login configuration, review
permissions first, and use a fresh task session rather than reusing another
sample's context. This add-on deliberately does not launch an unattended batch.

## Official documentation checked September 18, 2026

- Codex authentication: https://developers.openai.com/codex/auth
- CLI installation: https://developers.openai.com/codex/cli
- CLI options: https://developers.openai.com/codex/cli/reference
- Non-interactive runs and JSONL: https://developers.openai.com/codex/noninteractive
- ChatGPT-plan access: https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan
- Business seat/credit overview: https://help.openai.com/en/articles/8792828-chatgpt-business-overview

Some developer URLs redirect to OpenAI's learn.chatgpt.com documentation.
