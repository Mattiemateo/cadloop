#!/usr/bin/env python3
"""Launch supervised CADLoop work with Cursor's locally saved account login.

Stdlib only. No model API client, credential-file access, automatic installation,
login, headless batch, or global configuration changes. This is not a security
boundary, a CAD benchmark, or an integration with a ChatGPT subscription.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

# Preserve HOME / keychain / config paths: Cursor, not this launcher, owns login.
# This removes documented Cursor overrides and common provider overrides, not
# every secret a user's environment could contain.
REMOVED_ENVIRONMENT_VARIABLES = (
    "CURSOR_API_KEY", "CURSOR_AUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY",
    "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
)
REQUIRED_FILES = ("AGENTS.md", "docs/TOOLS.md", "docs/CURSOR_ACCOUNT.md", "pyproject.toml")
PROBE_TIMEOUT_SECONDS = 20
MAX_PROBE_CHARACTERS = 65536
MAX_TASK_BYTES = 16384
ANSI_ESCAPE = re.compile(r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~])")
PROMPT = """Read AGENTS.md, docs/TOOLS.md and docs/CURSOR_ACCOUNT.md. You are the
single coding agent in this supervised CADLoop session. Use the local CADLoop
CLI for state, measured evidence, bounded context, scoped proposals, evaluation,
views, parameter search and finish. Do not launch another AI agent or CADLoop's
paid-provider loop, request API keys, or read/copy account credentials.
For an existing CAD project, start with state and compact context, then fetch
only relevant source and failed checks. Prefer a parameter change or a small
feature edit; use bounded search for simple dimensions instead of repeated
model guesses. Preserve units, constraints and uncertainty in concise feedback.
For a new part, establish the reviewed brief, parameters and requirements before
creating a project. Do not invent missing manufacturer dimensions or weaken a
requirement to pass. Do not modify the harness, checkers, existing requirements,
reference data, receipts or acceptance flags during CAD repair.
Inspect and report available execution modes. Ask before native CAD execution;
only reviewed source may run natively. Newly generated source needs validated
build isolation or human review and explicit native-execution consent. Cursor's
shell sandbox is not proof that CADLoop's generated-code isolation is validated.
Do not install dependencies, publish files, or change account/configuration
settings without permission. Finish by freshly verifying the result and reporting
remaining engineering blockers; never invent benchmark scores or cost savings.
"""


def child_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Remove direct credential overrides without mutating the parent process."""
    return {key: value for key, value in source.items()
            if key.upper() not in REMOVED_ENVIRONMENT_VARIABLES}


def clean_probe(text: str) -> str:
    if len(text) > MAX_PROBE_CHARACTERS:
        return ""
    return ANSI_ESCAPE.sub("", text).replace("\r", "\n")


def confirms_account_status(text: str) -> bool:
    """Conservative text-status recognition, NOT an undocumented JSON schema.

    Cursor documents `status`, but not a stable result schema or a forced
    browser-only flag. Unknown/negative/key-auth output fails closed. Positive
    status plus removed overrides is not proof about opaque cached credentials.
    No account details are echoed or stored by this launcher.
    """
    text = clean_probe(text)
    negative = re.compile(
        r"\b(?:not\s+(?:logged\s+in|authenticated|signed\s+in)|"
        r"unauthenticated|logged\s+out|signed\s+out|"
        r"(?:authentication|login)\s+(?:failed|required)|"
        r"(?:session|token|credentials?)\s*[:=-]?\s*(?:has\s+|have\s+)?expired|"
        r"expired\s+(?:session|token|credentials?)|"
        r"invalid\s+(?:credentials?|token)|"
        r"api[ _-]?key|CURSOR_API_KEY|CURSOR_AUTH_TOKEN|auth[ _-]token|"
        r"(?:authentication|authenticated|logged[ _]in)\s*:\s*(?:false|none|no|0))\b", re.IGNORECASE,
    )
    if not text or negative.search(text):
        return False
    positive = re.compile(
        r"^(?:logged\s+in\s+(?:as|using|via)\b[^\n]+|"
        r"authenticated\s+(?:as|using|via|with)\b[^\n]+|"
        r"authenticated\s*[.!]?|login\s+successful\s*[.!]?|"
        r"(?:status|authentication(?:\s+status)?)\s*:\s*"
        r"(?:authenticated|logged\s+in)\s*[.!]?)$", re.IGNORECASE,
    )
    for line in text.splitlines():
        line = line.strip().lstrip("\u2713\u2714\u2705\u2022*- ").strip()
        if positive.fullmatch(line):
            return True
    return False


def cursor_help_is_compatible(text: str, mode: str = "agent") -> bool:
    text = clean_probe(text).lower()
    # `agent` is a generic executable name. Do not silently launch some other
    # program merely because it happens to be on PATH before Cursor.
    words_ok = all(re.search(r"\b" + term + r"\b", text) for term in ("cursor", "login", "status"))
    flags = set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", text))
    required_flags = {"--workspace", "--sandbox", "--model"}
    if mode != "agent":
        required_flags.add("--mode")
    return words_ok and required_flags.issubset(flags)


def interactive_command(executable: str, repo: Path, model: str | None = None,
                        mode: str = "agent", task: str | None = None) -> list[str]:
    command = [executable, "--workspace", str(repo), "--sandbox", "enabled"]
    if model:
        command.extend(["--model", model])
    # Cursor's current default is agent; --mode accepts plan or ask.
    if mode != "agent":
        command.extend(["--mode", mode])
    prompt = PROMPT
    if task:
        prompt += "\nUser's CAD task for this session:\n" + task
    else:
        prompt += "\nInspect available projects, then ask which CAD task to work on.\n"
    return [*command, prompt]


def exit_code(value: int) -> int:
    return 128 - value if value < 0 else value


def probe(executable: str, args: list[str], repo: Path,
          env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [executable, *args], cwd=repo, env=dict(env), stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=PROBE_TIMEOUT_SECONDS, check=False,
    )


def probe_text(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stdout or "") + "\n" + (result.stderr or "")


def report_error(message: str, code: int) -> int:
    print(message, file=sys.stderr)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--cli", help="Cursor executable name or path; default tries agent, then cursor-agent.")
    parser.add_argument("--model", help="Model ID available in your Cursor account; omit to keep Cursor's default.")
    parser.add_argument("--mode", choices=("agent", "plan", "ask"), default="agent")
    parser.add_argument("--task", help="Optional CAD brief passed as one argument, never as shell code.")
    checks = parser.add_mutually_exclusive_group()
    checks.add_argument("--dry-run", action="store_true", help="Print a plan without starting a subprocess or checking login.")
    checks.add_argument("--check", action="store_true", help="Check CLI capabilities and saved login, without starting inference.")
    args = parser.parse_args(argv)
    try:
        repo = args.repo.expanduser().resolve()
    except (ValueError, OSError, RuntimeError):
        return report_error("Invalid CADLoop repository path.", 2)
    if not repo.is_dir() or any(not (repo / name).is_file() for name in REQUIRED_FILES):
        return report_error("Not a CADLoop repository with Cursor support installed.", 2)
    if args.model is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}", args.model):
        return report_error("Model must be a nonempty model ID (max 200 characters, no spaces or option prefixes).", 2)
    if args.cli is not None and (not args.cli.strip() or args.cli.startswith("-") or
                                any(ord(c) < 32 for c in args.cli)):
        return report_error("--cli must be an executable name or path, not shell arguments.", 2)
    if args.task is not None:
        try:
            size = len(args.task.encode("utf-8"))
        except UnicodeError:
            return report_error("Task must be valid UTF-8 text.", 2)
        if not args.task.strip() or size > MAX_TASK_BYTES or any(
                ord(c) < 32 and c not in "\n\r\t" for c in args.task):
            return report_error("Task must be nonempty text of at most 16384 UTF-8 bytes, without control characters.", 2)
    planned_cli = os.path.expanduser(args.cli) if args.cli else "agent"
    if args.dry_run:
        print(json.dumps({
            "schema_version": 1,
            "command": interactive_command(planned_cli, repo, args.model, args.mode, args.task),
            "cwd": str(repo), "checks_performed": [],
            "removed_environment_variable_names": list(REMOVED_ENVIRONMENT_VARIABLES),
            "authentication": "Saved Cursor login; no credential files read by the launcher.",
            "billing": "Cursor account settings, NOT your ChatGPT/Codex entitlement; no spend cap enforced here.",
            "mode": "Supervised interactive launch; not a benchmark or unattended batch.",
        }, indent=2))
        return 0
    env = child_environment(os.environ)
    candidates = [planned_cli] if args.cli else ["agent", "cursor-agent"]
    seen: set[str] = set()
    executable = None
    try:
        for candidate in candidates:
            found = shutil.which(candidate)
            if not found:
                continue
            found = str(Path(found).resolve())
            if found in seen:
                continue
            seen.add(found)
            help_result = probe(found, ["--help"], repo, env)
            if help_result.returncode == 0 and cursor_help_is_compatible(probe_text(help_result), args.mode):
                executable = found
                break
        if executable is None:
            if seen:
                return report_error("No compatible Cursor CLI found. Use the official CLI with --workspace and --sandbox support; update it or specify --cli. Nothing was launched beyond help checks.", 4)
            return report_error("Cursor CLI not found. Install it locally, then run agent login. See docs/CURSOR_ACCOUNT.md. No inference was launched.", 127)
        login = probe(executable, ["status"], repo, env)
        if login.returncode != 0 or not confirms_account_status(probe_text(login)):
            return report_error("Cursor account login not confirmed. Clear CURSOR_API_KEY/CURSOR_AUTH_TOKEN overrides, run agent login (or cursor-agent login for that installation), then retry. Unknown status is rejected; no inference was launched. Account output is not logged.", 3)
        if args.check:
            print(json.dumps({
                "schema_version": 1, "status": "ready_for_supervised_launch",
                "executable": executable, "cwd": str(repo),
                "authentication_check": "Positive CLI status after removing documented key/token overrides; opaque credential storage is not inspected.",
                "sandbox_requested": "enabled", "inference_started": False,
                "billing": "Cursor account settings; this launcher does not cap spending.",
                "validation_scope": "CLI help and login only, not CAD runtime, sandbox efficacy or model quality.",
            }, indent=2))
            return 0
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return report_error("Interactive Cursor launch needs a terminal. Use --check for preflight; headless execution is deliberately not enabled.", 5)
        print("Starting Cursor with saved account login and --sandbox enabled. Review tool approvals and account usage settings. CADLoop checkers are not isolated from an agent that can edit this repository.", file=sys.stderr)
        child = subprocess.run(
            interactive_command(executable, repo, args.model, args.mode, args.task),
            cwd=repo, env=env, check=False,
        )
        return exit_code(child.returncode)
    except subprocess.TimeoutExpired:
        return report_error("Cursor preflight timed out; no inference was launched.", 124)
    except KeyboardInterrupt:
        return 130
    except OSError as error:
        return report_error(f"Could not run Cursor: {type(error).__name__}.", 126)


if __name__ == "__main__":
    raise SystemExit(main())
