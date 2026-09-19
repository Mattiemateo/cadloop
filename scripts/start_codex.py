#!/usr/bin/env python3
"""Launch supervised CADLoop work with existing Codex ChatGPT authentication.

No model API client, credential reading, installation, or automatic login is
performed here. This is a convenience launcher, not a security boundary or a
CADGenBench runner. Requires a current official Codex CLI on the user's machine.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence

API_KEY_VARIABLES = ("OPENAI_API_KEY", "CODEX_API_KEY")
AUTH_CONFIG = ["-c", 'model_provider="openai"', "-c", 'forced_login_method="chatgpt"']
PROMPT = """Read AGENTS.md, docs/TOOLS.md and docs/CODEX_ACCOUNT.md. You are the
single coding agent for this CADLoop session. Use the local CADLoop CLI for
state, measurements, scoped proposals, evaluation, views, searches and finish.
Do not start its paid-provider managed loop, request API keys, read credentials,
install another model provider, or invoke a nested AI agent. First report the
available projects and current evidence; do not assume a model is accepted.
Do not edit the harness, checkers, requirements, receipts, references or acceptance
flags to make a CAD task pass. Obtain explicit permission before native execution;
only reviewed source may run natively. Newly generated source needs separately
validated isolation. Keep edits small and reports factual. Do not upload anything
publicly or claim a CADGenBench score without its actual independent evaluation.
Ask the user which existing project/task to work on after the initial inspection.
"""


def child_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Leave Codex in charge of its cached auth; remove API-key env overrides."""
    return {key: value for key, value in source.items() if key not in API_KEY_VARIABLES}


def interactive_command(executable: str, repo: Path, model: str | None) -> list[str]:
    command = [executable, *AUTH_CONFIG, "--cd", str(repo),
               "--sandbox", "workspace-write", "--ask-for-approval", "on-request"]
    if model:
        command.extend(["--model", model])
    return [*command, PROMPT]


def exit_code(value: int) -> int:
    return 128 - value if value < 0 else value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--model", help="An available model from your Codex account; default keeps Codex's configured model.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned command; do not launch Codex or check login.")
    args = parser.parse_args(argv)
    repo = args.repo.expanduser().resolve()
    required = ("AGENTS.md", "docs/TOOLS.md", "docs/CODEX_ACCOUNT.md", "pyproject.toml")
    if not repo.is_dir() or any(not (repo / name).is_file() for name in required):
        print("Not a CADLoop repository with this add-on installed.", file=sys.stderr)
        return 2
    if args.model is not None and (not args.model.strip() or len(args.model) > 200):
        print("Model must be a nonempty model ID of at most 200 characters.", file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps({
            "command": interactive_command("codex", repo, args.model),
            "removed_environment_variable_names": list(API_KEY_VARIABLES),
            "auth": "existing Codex ChatGPT login; no credential contents read",
            "mode": "supervised local session; not a benchmark run",
            "billing": "ChatGPT plan/workspace policy; not a guarantee of zero credits",
        }, indent=2))
        return 0
    executable = shutil.which("codex")
    if not executable:
        print("Codex CLI is not installed/on PATH. Install the official CLI locally, then run codex login.", file=sys.stderr)
        return 127
    env = child_environment(os.environ)
    try:
        login = subprocess.run([executable, *AUTH_CONFIG, "login", "status"],
                               cwd=repo, env=env, capture_output=True, text=True,
                               timeout=20, check=False)
        text = (login.stdout or "") + "\n" + (login.stderr or "")
        # The human-readable status isn't a stable protocol. Unknown output
        # fails closed rather than risking an unexpected billing path.
        confirmed = bool(re.search(r"\bchatgpt\b", text, flags=re.IGNORECASE))
        api_auth = bool(re.search(r"\bapi[ _-]?key\b", text, flags=re.IGNORECASE))
        if login.returncode != 0 or not confirmed or api_auth:
            print("ChatGPT login not confirmed. Run codex login locally, select your Business workspace, and check codex login status. No inference was launched.", file=sys.stderr)
            return 3
        print("Starting Codex using ChatGPT account auth. Workspace-write is NOT isolation of the CADLoop checkers. Review native execution and workspace credit settings.", file=sys.stderr)
        child = subprocess.run(interactive_command(executable, repo, args.model),
                               cwd=repo, env=env, check=False)
        return exit_code(child.returncode)
    except subprocess.TimeoutExpired:
        print("Codex login check timed out. No inference was launched.", file=sys.stderr)
        return 124
    except KeyboardInterrupt:
        return 130
    except OSError as error:
        print(f"Could not launch Codex: {type(error).__name__}.", file=sys.stderr)
        return 126


if __name__ == "__main__":
    raise SystemExit(main())
