"""Launcher contract tests only; no real Codex inference or authentication."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

spec = importlib.util.spec_from_file_location("cadloop_codex_launcher", Path(__file__).resolve().parents[1] / "scripts/start_codex.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "CAD project ; spaces"
    for name in ("AGENTS.md", "docs/TOOLS.md", "docs/CODEX_ACCOUNT.md", "pyproject.toml"):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("fixture\n")
    return root


def test_environment_removes_keys_without_mutating_parent():
    src = {"OPENAI_API_KEY": "secret-a", "CODEX_API_KEY": "secret-b", "PATH": "/bin", "CODEX_HOME": "/private/codex"}
    result = launcher.child_environment(src)
    assert result == {"PATH": "/bin", "CODEX_HOME": "/private/codex"}
    assert "OPENAI_API_KEY" in src


def test_command_auth_permissions_and_no_shell(repo):
    cmd = launcher.interactive_command("/bin/codex", repo, "account-model")
    assert 'forced_login_method="chatgpt"' in cmd
    assert 'model_provider="openai"' in cmd
    assert cmd[cmd.index("--cd") + 1] == str(repo)
    assert cmd[cmd.index("--sandbox") + 1] == "workspace-write"
    assert cmd[cmd.index("--ask-for-approval") + 1] == "on-request"
    assert cmd[cmd.index("--model") + 1] == "account-model"
    assert not {"--yolo", "--full-auto", "--dangerously-bypass-approvals-and-sandbox"}.intersection(cmd)


def test_dry_run_never_invokes_codex(repo, monkeypatch, capsys):
    monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **kw: pytest.fail("unexpected subprocess"))
    assert launcher.main(["--repo", str(repo), "--dry-run"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert "--model" not in result["command"]
    assert "not a benchmark" in result["mode"]


def test_missing_repository_rejected(tmp_path):
    assert launcher.main(["--repo", str(tmp_path), "--dry-run"]) == 2


@pytest.mark.parametrize("model", ["", "  ", "x" * 201])
def test_invalid_model_rejected(repo, model):
    assert launcher.main(["--repo", str(repo), "--model", model, "--dry-run"]) == 2


def test_missing_codex_stops(repo, monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda _: None)
    assert launcher.main(["--repo", str(repo)]) == 127


@pytest.mark.parametrize("code,text", [(1, "Not logged in"), (0, "Logged in using an API key"), (0, "unknown auth"), (0, "ChatGPT but API key override")])
def test_wrong_or_unknown_login_never_launches_inference(repo, monkeypatch, code, text):
    calls = []
    monkeypatch.setattr(launcher.shutil, "which", lambda _: "/bin/codex")
    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, code, stdout="", stderr=text)
    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.main(["--repo", str(repo)]) == 3
    assert len(calls) == 1
    assert calls[0][-2:] == ["login", "status"]


@pytest.mark.parametrize("code,want", [(0, 0), (17, 17), (-15, 143)])
def test_confirmed_chatgpt_launch_and_exit(repo, monkeypatch, code, want):
    calls = []
    monkeypatch.setattr(launcher.shutil, "which", lambda _: "/bin/codex")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("CODEX_API_KEY", "must-not-leak")
    def run(command, **kwargs):
        calls.append(command)
        assert "OPENAI_API_KEY" not in kwargs["env"]
        assert "CODEX_API_KEY" not in kwargs["env"]
        assert not kwargs.get("shell", False)
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="Logged in using ChatGPT")
        return subprocess.CompletedProcess(command, code)
    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.main(["--repo", str(repo)]) == want
    assert len(calls) == 2


@pytest.mark.parametrize("error,want", [(subprocess.TimeoutExpired("codex", 20), 124), (FileNotFoundError(), 126), (KeyboardInterrupt(), 130)])
def test_launch_error_is_reported(repo, monkeypatch, error, want):
    monkeypatch.setattr(launcher.shutil, "which", lambda _: "/bin/codex")
    def run(*args, **kwargs):
        raise error
    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.main(["--repo", str(repo)]) == want
