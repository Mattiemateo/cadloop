"""Offline launcher contracts. Mocks/fake CLIs are not live Cursor validation."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cadloop_cursor_launcher", ROOT / "scripts/start_cursor.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
HELP = """Usage: agent [options] [prompt]
Cursor Agent CLI
--workspace <path> --sandbox <mode> --model <model> --mode <mode>
Commands: login, status, logout
"""


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "CAD project ; spaces"
    for name in launcher.REQUIRED_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test fixture\n")
    return root


def setup_mock(monkeypatch, *, status="Logged in as fixture@example.test", status_code=0,
               child_code=0, help_text=HELP, help_code=0, installed=True, tty=True):
    calls = []
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/fake/cursor-agent" if installed else None)
    monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: tty)
    monkeypatch.setattr(launcher.sys.stdout, "isatty", lambda: tty)

    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert not kwargs.get("shell", False)
        if command[-1] == "--help":
            return subprocess.CompletedProcess(command, help_code, help_text, "")
        if command[-1] == "status":
            return subprocess.CompletedProcess(command, status_code, "", status)
        return subprocess.CompletedProcess(command, child_code)

    monkeypatch.setattr(launcher.subprocess, "run", run)
    return calls


def test_environment_filters_overrides_and_preserves_login_location():
    source = {name: "not-a-real-key" for name in launcher.REMOVED_ENVIRONMENT_VARIABLES}
    source.update({"HOME": "/user", "PATH": "/bin", "CURSOR_CONFIG_DIR": "/user/cursor",
                   "XDG_CONFIG_HOME": "/user/config", "TERM": "xterm", "cursor_api_key": "fake"})
    before = dict(source)
    filtered = launcher.child_environment(source)
    assert filtered == {"HOME": "/user", "PATH": "/bin", "CURSOR_CONFIG_DIR": "/user/cursor",
                        "XDG_CONFIG_HOME": "/user/config", "TERM": "xterm"}
    assert source == before


@pytest.mark.parametrize("status", [
    "Logged in as fixture@example.test",
    "Authenticated as fixture@example.test",
    "Authenticated with Cursor account",
    "Logged in using browser authentication",
    "Logged in via browser",
    "Authenticated",
    "Authentication: authenticated",
    "Status: logged in",
    "Login successful",
    "\u2705 Login successful\nEndpoint: https://api2.cursor.sh",
    "\x1b[32m\u2713 Authenticated\x1b[0m\nAccount: fixture@example.test",
    "\x1b]0;status title\x07\x1b[1mLogged in as fixture@example.test\x1b[0m",
])
def test_positive_account_status(status):
    assert launcher.confirms_account_status(status)


@pytest.mark.parametrize("status", [
    "", "ready", "Checking authentication...", "Logged in", "Not logged in",
    "Not authenticated", "Unauthenticated", "Logged out", "Login required",
    "Authentication failed", "Authentication required", "Signed out",
    "API key authentication active", "Logged in using API-key",
    "Logged in as fixture\nCURSOR_API_KEY override",
    "Logged in as fixture\nCURSOR_AUTH_TOKEN override",
    "Logged in as fixture\nAuth-token override",
    "Logged in as fixture\nCredentials expired",
    "Logged in as fixture\nToken has expired",
    "Logged in as fixture\nInvalid token",
    "Logged in as fixture\nAuthentication: false",
    "Logged in as fixture\nAuthenticated: false",
    "Logged in as fixture\nSession: expired",
    "Not authenticated; last message: Logged in as fixture",
    "Previous session: Logged in as fixture",
    '{"authenticated": true}',
    "x" * (launcher.MAX_PROBE_CHARACTERS + 1) + "\nAuthenticated",
])
def test_negative_or_unknown_status_fails_closed(status):
    assert not launcher.confirms_account_status(status)


@pytest.mark.parametrize("mode", ["agent", "plan", "ask"])
def test_command_construction_and_task_not_shell(repo, mode):
    task = 'Inspect "the plate"; $(touch DO_NOT_CREATE) --force --api-key fake'
    cmd = launcher.interactive_command("/path with spaces/cursor-agent", repo, "account-model", mode, task)
    assert cmd[:5] == ["/path with spaces/cursor-agent", "--workspace", str(repo), "--sandbox", "enabled"]
    assert cmd[cmd.index("--model") + 1] == "account-model"
    if mode != "agent":
        assert cmd[cmd.index("--mode") + 1] == mode
    else:
        assert "--mode" not in cmd
    assert task in cmd[-1]
    assert not {"--force", "--yolo", "--trust", "--approve-mcps", "--print", "-p", "--api-key", "--auth-token"}.intersection(cmd)


def test_dry_run_has_no_side_effects(repo, monkeypatch, capsys):
    monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **k: pytest.fail("subprocess"))
    monkeypatch.setattr(launcher.shutil, "which", lambda *a: pytest.fail("executable discovery"))
    monkeypatch.setenv("CURSOR_API_KEY", "sensitive-fixture-value")
    before = {str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert launcher.main(["--repo", str(repo), "--dry-run"]) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["checks_performed"] == []
    assert "sensitive-fixture-value" not in output
    assert "--model" not in result["command"]
    assert before == {str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob("*") if p.is_file()}


@pytest.mark.parametrize("name", launcher.REQUIRED_FILES)
def test_missing_required_file_is_rejected(repo, name):
    (repo / name).unlink()
    assert launcher.main(["--repo", str(repo), "--dry-run"]) == 2


@pytest.mark.parametrize("model", ["", " ", "x" * 201, "--force", "model\n--yolo", "two models", "$(echo bad)"])
def test_bad_model_is_rejected(repo, model):
    assert launcher.main(["--repo", str(repo), "--model=" + model, "--dry-run"]) == 2


@pytest.mark.parametrize("task", ["", "   ", "\x00", "\x1b[0m", "a" * 16385, "\u00e9" * 8193, "\ud800"])
def test_bad_task_is_rejected(repo, task):
    assert launcher.main(["--repo", str(repo), "--task", task, "--dry-run"]) == 2


@pytest.mark.parametrize("cli", ["", " ", "--force", "agent\n--yolo", "bad\x00"])
def test_bad_cli_is_rejected(repo, cli):
    assert launcher.main(["--repo", str(repo), "--cli=" + cli, "--dry-run"]) == 2


@pytest.mark.parametrize("extra", [["--api-key", "fake"], ["--force"], ["--yolo"],
                                  ["--print"], ["--trust"], ["--approve-mcps"],
                                  ["--dry-run", "--check"], ["--mo", "plan"]])
def test_unsupported_options_are_not_forwarded(repo, extra):
    with pytest.raises(SystemExit) as error:
        launcher.main(["--repo", str(repo), *extra])
    assert error.value.code == 2


def test_missing_executable_stops(repo, monkeypatch):
    calls = setup_mock(monkeypatch, installed=False)
    assert launcher.main(["--repo", str(repo), "--check"]) == 127
    assert calls == []


@pytest.mark.parametrize("help_text", ["Usage: unrelated agent --help", HELP.replace("--sandbox", "--no-sandbox-option"), ""])
def test_wrong_or_old_cli_rejected(repo, monkeypatch, help_text):
    calls = setup_mock(monkeypatch, help_text=help_text)
    assert launcher.main(["--repo", str(repo), "--check"]) == 4
    assert len(calls) == 1  # Same executable found twice is deduplicated.


def test_nonzero_help_is_not_accepted(repo, monkeypatch):
    calls = setup_mock(monkeypatch, help_code=1)
    assert launcher.main(["--repo", str(repo), "--check"]) == 4
    assert len(calls) == 1


def test_requested_mode_requires_cli_support(repo, monkeypatch):
    calls = setup_mock(monkeypatch, help_text=HELP.replace("--mode <mode>", ""))
    assert launcher.main(["--repo", str(repo), "--mode", "plan", "--check"]) == 4
    assert len(calls) == 1


def test_fallback_skips_unrelated_agent(repo, monkeypatch):
    calls = []
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/fake/" + name)
    def run(command, **kwargs):
        calls.append(command)
        text = ("Other agent" if command[0] == "/fake/agent" else HELP) if command[-1] == "--help" else "Authenticated"
        return subprocess.CompletedProcess(command, 0, text, "")
    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.main(["--repo", str(repo), "--check"]) == 0
    assert len(calls) == 3
    assert calls[-1] == ["/fake/cursor-agent", "status"]


def test_explicit_binary_has_no_fallback(repo, monkeypatch):
    which_calls = []
    monkeypatch.setattr(launcher.shutil, "which", lambda name: which_calls.append(name))
    assert launcher.main(["--repo", str(repo), "--cli", "/user/My Tools/cursor-agent", "--check"]) == 127
    assert which_calls == ["/user/My Tools/cursor-agent"]


@pytest.mark.parametrize("status,code", [("Not authenticated", 0), ("Logged in using API key", 0),
                                         ("unknown", 0), ("Authenticated", 1)])
def test_authentication_failure_never_launches_inference(repo, monkeypatch, status, code):
    calls = setup_mock(monkeypatch, status=status, status_code=code)
    assert launcher.main(["--repo", str(repo)]) == 3
    assert len(calls) == 2
    assert calls[-1][0][-1] == "status"


def test_check_sanitizes_environment_and_does_not_echo_account(repo, monkeypatch, capsys):
    calls = setup_mock(monkeypatch)
    for name in launcher.REMOVED_ENVIRONMENT_VARIABLES:
        monkeypatch.setenv(name, "sensitive-fixture")
    assert launcher.main(["--repo", str(repo), "--check"]) == 0
    output = capsys.readouterr()
    assert "fixture@example.test" not in output.out + output.err
    assert "sensitive-fixture" not in output.out + output.err
    assert json.loads(output.out)["inference_started"] is False
    assert len(calls) == 2
    for command, kw in calls:
        assert not set(launcher.REMOVED_ENVIRONMENT_VARIABLES).intersection(kw["env"])
        assert kw["cwd"] == repo.resolve()
        assert kw["stdin"] == subprocess.DEVNULL
        assert kw["timeout"] == 20


@pytest.mark.parametrize("mode", ["agent", "plan", "ask"])
def test_supervised_launch(repo, monkeypatch, mode):
    calls = setup_mock(monkeypatch)
    assert launcher.main(["--repo", str(repo), "--mode", mode, "--model", "existing-model", "--task", "Repair plate."]) == 0
    assert len(calls) == 3
    command, kw = calls[-1]
    assert "Repair plate." in command[-1]
    assert "--sandbox" in command
    assert not {"--force", "--yolo", "--print", "--trust"}.intersection(command)
    assert not kw.get("capture_output", False)
    assert "stdin" not in kw


@pytest.mark.parametrize("code,want", [(17, 17), (-15, 143), (-2, 130)])
def test_child_failure_is_propagated(repo, monkeypatch, code, want):
    setup_mock(monkeypatch, child_code=code)
    assert launcher.main(["--repo", str(repo)]) == want


def test_no_terminal_does_not_turn_on_headless(repo, monkeypatch):
    calls = setup_mock(monkeypatch, tty=False)
    assert launcher.main(["--repo", str(repo)]) == 5
    assert len(calls) == 2


@pytest.mark.parametrize("error,want", [(subprocess.TimeoutExpired("fixture", 20), 124),
                                       (FileNotFoundError("must not print secret"), 126),
                                       (PermissionError("must not print secret"), 126),
                                       (KeyboardInterrupt(), 130)])
def test_preflight_errors_do_not_leak_details(repo, monkeypatch, capsys, error, want):
    setup_mock(monkeypatch)
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(launcher.subprocess, "run", fail)
    assert launcher.main(["--repo", str(repo), "--check"]) == want
    output = capsys.readouterr()
    assert "must not print secret" not in output.out + output.err


def test_docs_and_shared_instructions_do_not_force_codex():
    agents = (ROOT / "AGENTS.md").read_text()
    assert "Codex or Cursor CLI" in agents
    assert "Use the existing subscription-authenticated Codex host" not in agents
    assert "--sandbox enabled" in (ROOT / "docs/CURSOR_ACCOUNT.md").read_text()


def fake_executable(tmp_path: Path, status="Authenticated") -> Path:
    """An actual child process implementing only the synthetic test contract."""
    path = tmp_path / "tools with spaces" / "cursor-agent"
    path.parent.mkdir()
    path.write_text("#!" + sys.executable + "\n" + textwrap.dedent(f'''\
        import json, os, sys
        from pathlib import Path
        args = sys.argv[1:]
        record = {{"args": args, "cwd": os.getcwd(),
                   "credential_overrides_present": [k for k in os.environ
                      if k.upper() in {launcher.REMOVED_ENVIRONMENT_VARIABLES!r}]}}
        with Path(os.environ["CADLOOP_FAKE_LOG"]).open("a") as f:
            f.write(json.dumps(record) + "\\n")
        if args == ["--help"]:
            print({HELP!r})
        elif args == ["status"]:
            print({status!r}, file=sys.stderr)
        else:
            raise SystemExit(19)
    '''))
    path.chmod(0o755)
    return path


@pytest.mark.skipif(os.name != "posix", reason="POSIX fake executable contract")
@pytest.mark.parametrize("status,want", [("Authenticated", 0), ("Not authenticated", 3), ("Logged in using API key", 3)])
def test_actual_subprocess_preflight_with_synthetic_cli(repo, tmp_path, status, want):
    exe = fake_executable(tmp_path, status)
    log = tmp_path / "calls.jsonl"
    env = {**os.environ, "CADLOOP_FAKE_LOG": str(log), "CURSOR_API_KEY": "fixture-not-real",
           "CURSOR_AUTH_TOKEN": "fixture-not-real"}
    result = subprocess.run([sys.executable, str(ROOT / "scripts/start_cursor.py"),
                             "--repo", str(repo), "--cli", str(exe), "--check"],
                            capture_output=True, text=True, env=env, timeout=10)
    assert result.returncode == want, result.stderr
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert [r["args"] for r in records] == [["--help"], ["status"]]
    assert all(r["cwd"] == str(repo) for r in records)
    assert all(r["credential_overrides_present"] == [] for r in records)
    assert "fixture-not-real" not in result.stdout + result.stderr


@pytest.mark.skipif(os.name != "posix", reason="POSIX PTY contract")
def test_actual_interactive_subprocess_with_synthetic_cli(repo, tmp_path):
    import pty
    exe = fake_executable(tmp_path)
    log = tmp_path / "calls.jsonl"
    marker = tmp_path / "must_not_exist"
    task = f"Inspect plate; $(touch {marker}) --force"
    master, slave = pty.openpty()
    try:
        child = subprocess.Popen([sys.executable, str(ROOT / "scripts/start_cursor.py"),
                                  "--repo", str(repo), "--cli", str(exe), "--task", task],
                                 stdin=slave, stdout=slave, stderr=slave,
                                 env={**os.environ, "CADLOOP_FAKE_LOG": str(log),
                                      "CURSOR_API_KEY": "fixture-not-real"})
        try:
            code = child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
            raise
        assert code == 19  # Fake interactive child exit, not a Cursor service result.
    finally:
        os.close(slave)
        os.close(master)
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(records) == 3
    assert task in records[-1]["args"][-1]
    assert records[-1]["args"][:4] == ["--workspace", str(repo), "--sandbox", "enabled"]
    assert not marker.exists()
    assert records[-1]["credential_overrides_present"] == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX fake executable contract")
def test_real_probe_timeout_kills_fake_process(repo, tmp_path, monkeypatch):
    exe = tmp_path / "sleeping-cli"
    exe.write_text("#!" + sys.executable + "\nimport time\ntime.sleep(3)\n")
    exe.chmod(0o755)
    monkeypatch.setattr(launcher, "PROBE_TIMEOUT_SECONDS", 0.1)
    assert launcher.main(["--repo", str(repo), "--cli", str(exe), "--check"]) == 124
