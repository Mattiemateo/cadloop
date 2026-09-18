"""Bounded subprocess execution; an explicit opt-in is required for native code."""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from .errors import CadLoopError


def docker_command(stage: str, run: Path, image: str, name: str) -> list[str]:
    if stage not in ("build", "verify"):
        raise ValueError("Unknown worker stage")
    out_name = {"build":"geometry", "verify":"verification", "render":"views"}[stage]
    args = ["docker", "run", "--rm", "--name", name, "--network=none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=96",
            "--memory=3g", "--cpus=2", "--user", f"{os.getuid()}:{os.getgid()}",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m",
            "--mount", f"type=bind,src={run / 'input'},dst=/input,readonly",
            "--mount", f"type=bind,src={run / out_name},dst=/output"]
    if stage == "verify":
        args += ["--mount", f"type=bind,src={run / 'geometry'},dst=/geometry,readonly"]
    args += [image, "python", "-m", "cadloop.worker", stage,
             "--input", "/input", "--output", "/output"]
    if stage == "verify":
        args += ["--geometry", "/geometry"]
    return args


def run_stage(stage: str, run: Path, *, mode: str, timeout: float = 45.,
              image: str = "cadloop-worker:0.1.1") -> dict:
    if stage not in ("build", "verify", "render"):
        raise CadLoopError("STAGE_UNSUPPORTED", "Unknown worker stage")
    if stage == "render" and mode == "docker":
        raise CadLoopError("HOST_PREVIEW_DISABLED", "Containerized rendering is not validated; host parsing is disabled")
    if mode not in ("trusted-native", "docker"):
        raise CadLoopError("EXECUTION_MODE_REQUIRED",
                           "Choose Docker, or explicitly opt into trusted-native mode for reviewed code.")
    if not 0 < timeout <= 300:
        raise CadLoopError("INVALID_TIMEOUT", "Worker timeout must be in (0, 300] seconds")
    out_name = {"build":"geometry", "verify":"verification", "render":"views"}[stage]
    for folder in (out_name, "logs", "tmp"):
        (run / folder).mkdir(parents=True, exist_ok=True)
    name = "cadloop-" + run.name.lower().replace("_", "-")[:50] + "-" + stage
    if mode == "docker":
        if shutil.which("docker") is None:
            raise CadLoopError("DOCKER_UNAVAILABLE", "Docker is not installed; native execution is not enabled automatically.")
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
