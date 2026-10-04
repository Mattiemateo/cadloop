"""Bounded subprocess execution; an explicit opt-in is required for native code."""
from __future__ import annotations
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from .errors import CadLoopError
from .util import digest

WORKER_IMAGE = "cadloop-worker:0.1.1"
EXECUTION_POLICY_VERSION = 1
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")


def runtime_identity(mode: str, *, image: str = WORKER_IMAGE) -> dict:
    """Return the execution policy and immutable worker image for one evaluation."""
    if mode not in ("trusted-native", "docker"):
        raise CadLoopError("EXECUTION_MODE_REQUIRED", "Explicitly select trusted-native or Docker execution")
    identity = {"mode": mode, "policy_version": EXECUTION_POLICY_VERSION}
    if mode == "trusted-native":
        return identity
    if shutil.which("docker") is None:
        raise CadLoopError("DOCKER_UNAVAILABLE", "Docker is not installed; native execution is not enabled automatically.")
    try:
        inspected = subprocess.run(["docker", "image", "inspect", "--format={{.Id}}", image],
                                   capture_output=True, text=True, timeout=15, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CadLoopError("DOCKER_IMAGE_UNAVAILABLE", "Cannot resolve the Docker worker image") from exc
    image_id = inspected.stdout.strip()
    if not _IMAGE_ID.fullmatch(image_id):
        raise CadLoopError("DOCKER_IMAGE_INVALID", "Docker returned an invalid worker image ID")
    policy_run = Path("/__cadloop_policy__")
    policy = {stage: docker_command(stage, policy_run, image_id, "cadloop-policy")
              for stage in ("build", "verify", "render")}
    return {**identity, "image_id": image_id,
            "policy_fingerprint": digest({"version": EXECUTION_POLICY_VERSION, "commands": policy})}


def docker_command(stage: str, run: Path, image: str, name: str) -> list[str]:
    if stage not in ("build", "verify", "render"):
        raise ValueError("Unknown worker stage")
    out_name = {"build":"geometry", "verify":"verification", "render":"preview"}[stage]
    args = ["docker", "run", "--rm", "--name", name, "--network=none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=96",
            "--memory=3g", "--cpus=2", "--user", f"{os.getuid()}:{os.getgid()}",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m",
            "--mount", f"type=bind,src={run / 'input'},dst=/input,readonly",
            "--mount", f"type=bind,src={run / out_name},dst=/output"]
    if stage in ("verify", "render"):
        args += ["--mount", f"type=bind,src={run / 'geometry'},dst=/geometry,readonly"]
    if stage == "render":
        args += ["--mount", f"type=bind,src={run / 'verification'},dst=/verification,readonly"]
    args += [image, "python", "-m", "cadloop.worker", stage,
             "--input", "/input", "--output", "/output"]
    if stage in ("verify", "render"):
        args += ["--geometry", "/geometry"]
    if stage == "render":
        args += ["--report", "/verification/report.json"]
    return args


def run_stage(stage: str, run: Path, *, mode: str, timeout: float = 45.,
              image: str = WORKER_IMAGE) -> dict:
    if stage not in ("build", "verify", "render"):
        raise CadLoopError("STAGE_UNSUPPORTED", "Unknown worker stage")
    if mode not in ("trusted-native", "docker"):
        raise CadLoopError("EXECUTION_MODE_REQUIRED",
                           "Choose Docker, or explicitly opt into trusted-native mode for reviewed code.")
    if not 0 < timeout <= 300:
        raise CadLoopError("INVALID_TIMEOUT", "Worker timeout must be in (0, 300] seconds")
    out_name = {"build":"geometry", "verify":"verification",
                "render": "preview" if mode == "docker" else "views"}[stage]
    for folder in (out_name, "logs", "tmp"):
        (run / folder).mkdir(parents=True, exist_ok=True)
    name = "cadloop-" + run.name.lower().replace("_", "-")[:50] + "-" + stage
    if mode == "docker":
        if shutil.which("docker") is None:
            raise CadLoopError("DOCKER_UNAVAILABLE", "Docker is not installed; native execution is not enabled automatically.")
        if not _IMAGE_ID.fullmatch(image):
            image = runtime_identity("docker", image=image)["image_id"]
        args = docker_command(stage, run, image, name)
        env = os.environ.copy()  # Docker client only; no env is forwarded into its worker.
    else:
        args = [sys.executable, "-m", "cadloop.worker", stage,
                "--input", str(run / "input"), "--output", str(run / out_name)]
        if stage == "verify":
            args += ["--geometry", str(run / "geometry")]
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
               "HOME": str(run / "tmp"), "TMPDIR": str(run / "tmp"),
               "MPLCONFIGDIR": str(run / "tmp"), "LANG": "C.UTF-8",
               "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
        # Native mode does NOT protect the filesystem or block networking.
    started = time.monotonic()
    stdout, stderr = run / "logs" / f"{stage}.stdout", run / "logs" / f"{stage}.stderr"
    timed_out = False
    with stdout.open("wb") as out, stderr.open("wb") as err:
        proc = subprocess.Popen(args, stdout=out, stderr=err, cwd=run / "tmp", env=env,
                                start_new_session=True)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            if mode == "docker":
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
            code = -9
        finally:
            # Reap any child process left behind by a worker, including on success.
            if os.name == "posix":
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    return {"stage": stage, "mode": mode, "exit_code": code, "timed_out": timed_out,
            "elapsed_seconds": round(time.monotonic()-started, 4),
            "stdout": stdout.relative_to(run).as_posix(),
            "stderr": stderr.relative_to(run).as_posix(),
            "stderr_tail": stderr.read_text(errors="replace")[-1800:] if code else "",
            "sandboxed": mode == "docker"}
