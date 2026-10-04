import subprocess
from types import SimpleNamespace

import pytest

from cadloop import execution
from cadloop.errors import CadLoopError
from cadloop.execution import docker_command, runtime_identity, run_stage
from cadloop.util import read_json, write_json


IMAGE_ID = "sha256:" + "a" * 64


def test_runtime_identity_resolves_docker_image_once(monkeypatch):
    calls = []
    monkeypatch.setattr("cadloop.execution.shutil.which", lambda _: "/usr/bin/docker")
    def inspect(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=IMAGE_ID + "\n")
    monkeypatch.setattr("cadloop.execution.subprocess.run", inspect)
    identity = runtime_identity("docker")
    assert identity["mode"] == "docker" and identity["policy_version"] == 1
    assert identity["image_id"] == IMAGE_ID and len(identity["policy_fingerprint"]) == 64
    assert len(calls) == 1
    assert calls[0][0] == ["docker", "image", "inspect", "--format={{.Id}}", "cadloop-worker:0.1.1"]
    assert calls[0][1]["check"] is True
    assert runtime_identity("trusted-native") == {"mode": "trusted-native", "policy_version": 1}
    assert len(calls) == 1


def test_policy_fingerprint_tracks_docker_options(monkeypatch):
    monkeypatch.setattr("cadloop.execution.shutil.which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr("cadloop.execution.subprocess.run", lambda *a, **kw: SimpleNamespace(stdout=IMAGE_ID))
    before = runtime_identity("docker")["policy_fingerprint"]
    original = execution.docker_command
    monkeypatch.setattr(execution, "docker_command",
                        lambda *args: original(*args) + (["changed-render-option"] if args[0] == "render" else []))
    assert runtime_identity("docker")["policy_fingerprint"] != before


def test_docker_render_uses_isolated_preview_output(tmp_path):
    command = docker_command("render", tmp_path, IMAGE_ID, "preview-test")
    mounts = [command[i + 1] for i, arg in enumerate(command[:-1]) if arg == "--mount"]
    assert f"type=bind,src={tmp_path / 'preview'},dst=/output" in mounts
    assert f"type=bind,src={tmp_path / 'input'},dst=/input,readonly" in mounts
    assert f"type=bind,src={tmp_path / 'geometry'},dst=/geometry,readonly" in mounts
    assert f"type=bind,src={tmp_path / 'verification'},dst=/verification,readonly" in mounts
    assert command[-2:] == ["--report", "/verification/report.json"]


def test_changed_tag_changes_runtime_identity(monkeypatch):
    monkeypatch.setattr("cadloop.execution.shutil.which", lambda _: "/usr/bin/docker")
    images = iter((IMAGE_ID, "sha256:" + "b" * 64))
    monkeypatch.setattr("cadloop.execution.subprocess.run",
                        lambda *a, **kw: SimpleNamespace(stdout=next(images)))
    assert runtime_identity("docker") != runtime_identity("docker")


@pytest.mark.parametrize("failure,code", [
    (subprocess.CalledProcessError(1, "docker"), "DOCKER_IMAGE_UNAVAILABLE"),
    (SimpleNamespace(stdout="cadloop-worker:0.1.1\n"), "DOCKER_IMAGE_INVALID"),
])
def test_runtime_identity_fails_closed(monkeypatch, failure, code):
    monkeypatch.setattr("cadloop.execution.shutil.which", lambda _: "/usr/bin/docker")
    def inspect(*args, **kwargs):
        if isinstance(failure, Exception):
            raise failure
        return failure
    monkeypatch.setattr("cadloop.execution.subprocess.run", inspect)
    with pytest.raises(CadLoopError) as exc:
        runtime_identity("docker")
    assert exc.value.code == code


def test_direct_docker_stage_runs_resolved_image(monkeypatch, tmp_path):
    launched = []
    monkeypatch.setattr("cadloop.execution.shutil.which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr("cadloop.execution.subprocess.run", lambda *a, **kw: SimpleNamespace(stdout=IMAGE_ID))
    class Process:
        pid = 12345
        def wait(self, timeout):
            return 0
    monkeypatch.setattr("cadloop.execution.subprocess.Popen",
                        lambda args, **kwargs: launched.append(args) or Process())
    monkeypatch.setattr("cadloop.execution.os.killpg", lambda *a: None)
    stage = run_stage("build", tmp_path / "run", mode="docker")
    assert stage["exit_code"] == 0
    assert launched[0][launched[0].index("python") - 1] == IMAGE_ID
    monkeypatch.setattr("cadloop.execution.subprocess.run",
                        lambda *a, **kw: pytest.fail("Pinned image must not be inspected again"))
    run_stage("verify", tmp_path / "run2", mode="docker", image=IMAGE_ID)
    assert launched[1][launched[1].index("python") - 1] == IMAGE_ID


def _fake_project_stages(project, monkeypatch, *, after_build=None, render_exit=None,
                         render_html=True, after_render=None):
    from cadloop.checks import required_check_ids, result
    from cadloop.worker import make_report
    calls = []
    def stage(name, run, *, mode, image, timeout):
        assert mode == "docker"
        calls.append((name, image))
        if name == "build":
            write_json(run / "geometry/scene.json", {"test": True})
            if after_build:
                after_build()
        elif name == "verify":
            req = project.requirements()
            checks = [result(check_id, "pass", "OK", "Mocked pass")
                      for check_id in required_check_ids(req)]
            revision = read_json(run / "input/meta.json")["revision"]
            write_json(run / "verification/report.json", make_report(revision, req, checks))
        else:
            if render_exit and render_exit[0]:
                (run / "preview").mkdir()
                (run / "preview/partial.png").write_bytes(b"partial")
                return {"stage": name, "exit_code": 1, "timed_out": False}
            revision = read_json(run / "verification/report.json")["revision"]
            write_json(run / "preview/views/manifest.json", {"revision": revision})
            (run / "preview/views/overview.png").write_bytes(b"\x89PNG test")
            (run / "preview/views/section_xz.png").write_bytes(b"\x89PNG test")
            if render_html:
                (run / "preview/report.html").write_text("<html>Test preview</html>")
            if after_render:
                after_render(run)
        return {"stage": name, "exit_code": 0, "timed_out": False}
    monkeypatch.setattr("cadloop.project.run_stage", stage)
    return calls


@pytest.mark.integration
def test_project_cache_requires_same_image_and_policy(project, monkeypatch):
    image = [IMAGE_ID]
    policy = ["policy-a"]
    monkeypatch.setattr("cadloop.project.runtime_identity",
                        lambda mode: {"mode": mode, "image_id": image[0], "policy_fingerprint": policy[0]})
    calls = _fake_project_stages(project, monkeypatch)
    first = project.evaluate(mode="docker", render=False)
    cached = project.evaluate(mode="docker", render=False)
    assert first["geometry_accepted"] and not first["cached"]
    assert cached["cached"] and cached["run_id"] == first["run_id"]
    assert calls == [("build", IMAGE_ID), ("verify", IMAGE_ID)]
    image[0] = "sha256:" + "b" * 64
    changed_image = project.evaluate(mode="docker", render=False)
    assert not changed_image["cached"] and changed_image["run_id"] != first["run_id"]
    policy[0] = "policy-b"
    changed_policy = project.evaluate(mode="docker", render=False)
    assert not changed_policy["cached"] and changed_policy["run_id"] != changed_image["run_id"]
    assert calls == [("build", IMAGE_ID), ("verify", IMAGE_ID),
                     ("build", image[0]), ("verify", image[0]),
                     ("build", image[0]), ("verify", image[0])]
    assert read_json(project.control / "runs" / changed_policy["run_id"] / "execution.json")["runtime"]["policy_fingerprint"] == "policy-b"


@pytest.mark.integration
def test_tag_drift_keeps_both_stages_on_one_image(project, monkeypatch):
    current = [IMAGE_ID]
    next_image = "sha256:" + "b" * 64
    monkeypatch.setattr("cadloop.project.runtime_identity",
                        lambda mode: {"mode": mode, "image_id": current[0], "policy_fingerprint": current[0]})
    calls = _fake_project_stages(project, monkeypatch, after_build=lambda: current.__setitem__(0, next_image))
    first = project.evaluate(mode="docker", render=False)
    assert first["geometry_accepted"] and calls == [("build", IMAGE_ID), ("verify", IMAGE_ID)]
    second = project.evaluate(mode="docker", render=False)
    assert not second["cached"] and calls[-2:] == [("build", next_image), ("verify", next_image)]


@pytest.mark.integration
def test_missing_docker_image_cannot_reuse_cached_pass(project, monkeypatch):
    monkeypatch.setattr("cadloop.project.runtime_identity",
                        lambda mode: {"mode": mode, "image_id": IMAGE_ID, "policy_fingerprint": "policy-a"})
    calls = _fake_project_stages(project, monkeypatch)
    first = project.evaluate(mode="docker", render=False)
    assert first["geometry_accepted"]
    def unavailable(_mode):
        raise CadLoopError("DOCKER_IMAGE_UNAVAILABLE", "Image is missing")
    monkeypatch.setattr("cadloop.project.runtime_identity", unavailable)
    second = project.evaluate(mode="docker", render=False)
    assert not second["cached"] and not second["geometry_accepted"]
    assert second["blockers"][0]["code"] == "DOCKER_IMAGE_UNAVAILABLE"
    assert calls == [("build", IMAGE_ID), ("verify", IMAGE_ID)]


@pytest.mark.integration
def test_docker_preview_promotion_and_failure_leave_acceptance(project, monkeypatch):
    monkeypatch.setattr("cadloop.project.runtime_identity",
                        lambda mode: {"mode": mode, "image_id": IMAGE_ID, "policy_fingerprint": "policy-a"})
    render_exit = [0]
    calls = _fake_project_stages(project, monkeypatch, render_exit=render_exit)
    first = project.evaluate(mode="docker", render=True)
    run = project.control / "runs" / first["run_id"]
    assert first["geometry_accepted"] and (run / "views/overview.png").is_file()
    assert (run / "report.html").is_file() and not (run / "preview").exists()
    project.latest()
    render_exit[0] = 1
    failed_view = project.evaluate(mode="docker", render=True, force=True)
    failed_run = project.control / "runs" / failed_view["run_id"]
    assert failed_view["geometry_accepted"] and read_json(failed_run / "view_error.json")["code"] == "VIEW_FAILED"
    assert not (failed_run / "report.html").exists() and not (failed_run / "preview").exists()
    assert calls[-3:] == [("build", IMAGE_ID), ("verify", IMAGE_ID), ("render", IMAGE_ID)]
    project.latest()


@pytest.mark.integration
@pytest.mark.parametrize("malformed", ["missing_html", "symlink"])
def test_malformed_docker_preview_is_discarded(project, monkeypatch, tmp_path, malformed):
    monkeypatch.setattr("cadloop.project.runtime_identity",
                        lambda mode: {"mode": mode, "image_id": IMAGE_ID, "policy_fingerprint": "policy-a"})
    def poison(run):
        if malformed == "symlink":
            (run / "preview/views/extra.png").symlink_to(tmp_path / "outside.png")
    _fake_project_stages(project, monkeypatch, render_html=malformed != "missing_html",
                         after_render=poison)
    evaluated = project.evaluate(mode="docker", render=True)
    run = project.control / "runs" / evaluated["run_id"]
    assert evaluated["geometry_accepted"]
    assert read_json(run / "view_error.json")["code"] == "VIEW_UNAVAILABLE"
    assert not (run / "views").exists() and not (run / "report.html").exists()
    assert not (run / "preview").exists() and not (run / "tmp").exists()
    project.latest()
