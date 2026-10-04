"""Exercise the actual Docker profile with harmless sentinels and a timed-out child.

Run with the controller's Python. No account files or real secrets are read.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from cadloop.execution import docker_command, run_stage
from cadloop.util import read_json, write_json

PROBE = '''import os, socket, sys
from pathlib import Path
import json
checks = {}
for name, path in [("root_readonly", "/opt/cadloop/isolation-probe"),
                   ("input_readonly", "/input/isolation-probe")]:
    try:
        Path(path).write_text("probe")
        checks[name] = False
    except OSError:
        checks[name] = True
checks["host_sentinel_hidden"] = not Path(sys.argv[1]).exists()
checks["host_environment_hidden"] = "CADLOOP_ISOLATION_SENTINEL" not in os.environ
checks["no_account_mount"] = not Path("/Users").exists() and ".codex" not in Path("/proc/self/mountinfo").read_text()
checks["no_docker_socket"] = not Path("/var/run/docker.sock").exists()
checks["unprivileged"] = os.getuid() != 0
status = Path("/proc/self/status").read_text()
checks["no_new_privileges"] = "NoNewPrivs:\\t1" in status
checks["no_capabilities"] = "CapEff:\\t0000000000000000" in status
checks["pids_limited"] = Path("/sys/fs/cgroup/pids.max").read_text().strip() == "96"
checks["memory_limited"] = Path("/sys/fs/cgroup/memory.max").read_text().strip() == str(3 * 1024**3)
checks["cpus_limited"] = Path("/sys/fs/cgroup/cpu.max").read_text().split() == ["200000", "100000"]
with socket.socket() as connection:
    connection.settimeout(1)
    try:
        connection.connect(("1.1.1.1", 443))
        checks["network_blocked"] = False
    except OSError:
        checks["network_blocked"] = True
Path("/output/probe.json").write_text(json.dumps(checks))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="cadloop-worker:0.1.1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    image_id = subprocess.check_output(["docker", "image", "inspect", args.image,
                                        "--format", "{{.Id}}"], text=True, timeout=15).strip()
    with tempfile.TemporaryDirectory(prefix="cadloop-isolation-") as directory:
        root = Path(directory).resolve()
        sentinel = root / "host-only.txt"
        sentinel.write_text("Harmless isolation sentinel, not an account secret.")
        run = root / ("probe-" + root.name.removeprefix("cadloop-isolation-")).replace("_", "-")
        (run / "input/design").mkdir(parents=True)
        (run / "geometry").mkdir()
        (run / "input/probe.py").write_text(PROBE)
        name = root.name + "-probe"
        command = docker_command("build", run, image_id, name)
        command = command[:command.index(image_id) + 1] + ["python", "/input/probe.py", str(sentinel)]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=30,
                           env={**os.environ, "CADLOOP_ISOLATION_SENTINEL": "harmless-sentinel"})
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
        checks = read_json(run / "geometry/probe.json")
        # Keep a real child alive until run_stage must terminate the container.
        child = "from pathlib import Path; import time\nwhile True:\n Path('/output/child-alive').write_text(str(time.time_ns()))\n time.sleep(.05)\n"
        (run / "input/design/model.py").write_text(
            f"import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', {child!r}])\ntime.sleep(60)\n")
        write_json(run / "input/design/parameters.json", {})
        execution = run_stage("build", run, mode="docker", timeout=5, image=image_id)
        heartbeat = run / "geometry/child-alive"
        before = heartbeat.read_text() if heartbeat.exists() else None
        time.sleep(.3)
        checks["child_really_started"] = before is not None
        checks["child_stopped"] = before is not None and heartbeat.read_text() == before
        checks["timeout_reported"] = execution["timed_out"] and execution["exit_code"] != 0
        remaining = subprocess.check_output(["docker", "ps", "-aq", "--filter", f"name=^/cadloop-{run.name}-build$"],
                                            text=True, timeout=15).strip()
        checks["timed_out_container_removed"] = not remaining
        result = {"image": image_id, "checks": checks, "passed": all(checks.values()),
                  "timeout_execution": execution, "scope": "worker isolation; host agent is not isolated"}
        write_json(args.output, result)
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
