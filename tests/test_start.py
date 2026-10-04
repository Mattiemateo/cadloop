"""Convenience entry point; account/authentication behavior stays in the launchers."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from cadloop import cli


@pytest.mark.parametrize("host", ["codex", "cursor"])
def test_start_dry_run_from_other_directory(tmp_path, host):
    result = subprocess.run(
        [sys.executable, "-m", "cadloop.cli", "start", "--host", host, "--dry-run"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    command = json.loads(result.stdout)["command"]
    repo = Path(cli.__file__).resolve().parents[2]
    flag = "--cd" if host == "codex" else "--workspace"
    assert command[command.index(flag) + 1] == str(repo)
    assert "--model" not in command
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("code,expected", [(0, 0), (17, 17), (-15, 143)])
def test_start_delegates_exact_arguments_and_exit(tmp_path, monkeypatch, code, expected):
    repo = tmp_path / "checkout ; spaces"
    script = repo / "scripts/start_codex.py"
    script.parent.mkdir(parents=True)
    script.write_text("# launcher fixture\n")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, code)

    monkeypatch.setattr(cli.subprocess, "run", run)
    assert cli.main(["start", "--repo", str(repo), "--model", "account-model"]) == expected
    assert calls == [([sys.executable, str(script), "--repo", str(repo),
                      "--model", "account-model"], {"cwd": repo, "check": False})]


def test_missing_launcher_reports_repository_hint(tmp_path, capsys):
    assert cli.main(["start", "--repo", str(tmp_path), "--dry-run"]) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["code"] == "ACCOUNT_LAUNCHER_UNAVAILABLE"
    assert "--repo" in result["message"]


def test_start_keyboard_interrupt_returns_shell_exit(monkeypatch):
    def run(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.subprocess, "run", run)
    assert cli.main(["start"]) == 130


def test_help_does_not_launch(monkeypatch, capsys):
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: pytest.fail("launch"))
    with pytest.raises(SystemExit) as error:
        cli.main(["start", "--help"])
    assert error.value.code == 0
    assert "--host" in capsys.readouterr().out
