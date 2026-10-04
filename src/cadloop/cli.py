"""CLI contract: JSON stdout, meaningful exit codes, no automatic API calls."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import importlib.util
import subprocess
from .project import Project
from .contracts import Proposal, Action
from .util import read_json, write_json, versions, strict_loads
from .errors import CadLoopError


def pairs(items):
    answer = {}
    for item in items or []:
        if "=" not in item:
            raise CadLoopError("INVALID_SET", "Use --set name=JSON_VALUE")
        name, value = item.split("=", 1)
        if name in answer:
            raise CadLoopError("DUPLICATE_SET", "Each parameter may be set only once")
        answer[name] = strict_loads(value)
    return answer


def execution_args(p):
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--trusted-native", action="store_true", help="Execute reviewed Python without a security sandbox")
    group.add_argument("--docker", action="store_true", help="Use the separately built cadloop-worker:0.1.1 image")
    p.add_argument("--timeout", type=float, default=45.)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cadloop", description="CAD generation with independent, revision-bound geometric feedback")
    sub = parser.add_subparsers(dest="command", required=True)
    from .planning.cli import add_commands
    add_commands(sub)
    p = sub.add_parser("start", help="Open a supervised Codex or Cursor account session")
    p.add_argument("--host", choices=("codex", "cursor"), default="codex")
    p.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2],
                   help="CADLoop checkout; defaults to this editable installation's checkout")
    p.add_argument("--model", help="An available model from the selected host account")
    p.add_argument("--dry-run", action="store_true", help="Show the launch command without checking login or starting inference")
    p = sub.add_parser("doctor", help="Inspect installed CAD runtimes; performs no downloads")
    p = sub.add_parser("init", help="Create a deliberately broken plate-stack fixture")
    p.add_argument("project", type=Path)
    p.add_argument("--backend", choices=["cadquery", "build123d"], default="cadquery")
    p = sub.add_parser("create", help="Create a NEW project from reviewed requirements and Python source")
    p.add_argument("project", type=Path)
    p.add_argument("--requirements", type=Path, required=True)
    p.add_argument("--design-dir", type=Path, required=True)
    p = sub.add_parser("import-kerf", help="Import a Kerf spec and Build123d source against separately approved requirements; executes no source")
    p.add_argument("project", type=Path)
    p.add_argument("--spec", type=Path, required=True)
    p.add_argument("--code", type=Path, required=True)
    p.add_argument("--requirements", type=Path, required=True)
    p.add_argument("--part", required=True)
    for command in ("state", "context", "inspect", "propose", "evaluate", "view", "finish", "search-parameter", "loop"):
        p = sub.add_parser(command)
        p.add_argument("project", type=Path)
        if command == "inspect":
            group = p.add_mutually_exclusive_group()
            group.add_argument("--check"); group.add_argument("--part"); group.add_argument("--source", action="store_true")
            group.add_argument("--scenario")
            p.add_argument("--path", default="model.py")
            p.add_argument("--start-line", type=int, default=1)
            p.add_argument("--max-lines", type=int, default=180)
        if command == "context":
            p.add_argument("--source-edits", action="store_true")
            p.add_argument("--include-source", action="store_true", default=None)
        if command == "propose":
            p.add_argument("--patch", type=Path)
            p.add_argument("--base")
            p.add_argument("--set", action="append", default=[])
            p.add_argument("--reason", default="Local parameter repair")
        if command in ("evaluate", "finish", "search-parameter", "loop"):
            execution_args(p)
        if command == "evaluate":
            p.add_argument("--force", action="store_true"); p.add_argument("--no-render", action="store_true")
        if command == "view":
            p.add_argument("--kind", choices=["overview", "section_xz", "report"], default="report")
        if command == "search-parameter":
            p.add_argument("parameter"); p.add_argument("--values", required=True, help="JSON array, max 12 values")
            p.add_argument("--set", action="append", default=[])
        if command == "loop":
            group = p.add_mutually_exclusive_group(required=True)
            group.add_argument("--replay", type=Path); group.add_argument("--provider-config", type=Path)
            p.add_argument("--max-steps", type=int, default=6)
    p = sub.add_parser("demo", help="Build, detect faults, search a repair, reverify, and export")
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--backend", choices=["cadquery", "build123d"], default="cadquery")
    execution_args(p)
    p = sub.add_parser("schema")
    p.add_argument("kind", choices=["action", "proposal"])
    a = parser.parse_args(argv)
    try:
        if a.command == "start":
            repo = a.repo.expanduser().resolve()
            launcher = repo / "scripts" / f"start_{a.host}.py"
            if not launcher.is_file():
                raise CadLoopError("ACCOUNT_LAUNCHER_UNAVAILABLE",
                                   "Use cadloop start --repo /path/to/cadloop with a checkout containing the account launchers")
            command = [sys.executable, str(launcher), "--repo", str(repo)]
            if a.model is not None:
                command.extend(["--model", a.model])
            if a.dry_run:
                command.append("--dry-run")
            try:
                code = subprocess.run(command, cwd=repo, check=False).returncode
                return 128 - code if code < 0 else code
            except KeyboardInterrupt:
                return 130
        if a.command.startswith("design-"):
            from .planning.cli import run_command
            out, exit_code = run_command(a)
            print(out if isinstance(out, str) else json.dumps(out, indent=2, allow_nan=False))
            return exit_code
        mode = "trusted-native" if getattr(a, "trusted_native", False) else "docker" if getattr(a, "docker", False) else None
        if a.command == "doctor":
            import shutil
            out = {"versions": versions(), "docker_available": shutil.which("docker") is not None,
                   "build123d_available": importlib.util.find_spec("build123d") is not None,
                   "cadquery_available": importlib.util.find_spec("cadquery") is not None,
                   "warning": "Installed does not mean independently benchmarked. Native mode is not sandboxed."}
        elif a.command == "schema":
            out = (Action if a.kind == "action" else Proposal).model_json_schema()
        elif a.command == "init":
            p = Project.initialize(a.project, backend=a.backend)
            out = {"status": "INITIALIZED", "project": str(p.root), "revision": p.revision(),
                   "note": "The initial fixture intentionally has a missing spacer and an 8 mm gap."}
        elif a.command == "create":
            p = Project.create(a.project, requirements=a.requirements, design_dir=a.design_dir)
            out = {"status": "INITIALIZED", "project": str(p.root), "revision": p.revision(),
                   "note": "Requirements anchored for this new project. Source was parsed, not executed."}
        elif a.command == "import-kerf":
            from .kerf import import_project
            p = import_project(a.project, spec=a.spec, code=a.code,
                               requirements=a.requirements, part=a.part)
            out = {"status": "INITIALIZED", "project": str(p.root), "revision": p.revision(),
                   "note": "Kerf source parsed, not executed. Values normalized to mm/deg/count. Evaluate with --docker."}
        elif a.command == "demo":
            from .search import search_parameter
            p = Project.initialize(a.directory, backend=a.backend)
            baseline = p.evaluate(mode=mode, timeout=a.timeout, render=True)
            search = search_parameter(p, "gap_mm", [8, 10, 12, 14], mode=mode,
                                      fixed={"include_spacer": True}, timeout=a.timeout)
            from .parametric import accepted
            final = p.finish(mode=mode, timeout=a.timeout) if accepted(search["final"]) else search["final"]
            out = {"status": final["status"], "project": str(p.root), "baseline": baseline,
                   "search": search, "final": final, "llm_calls": 0,
                   "note": "Deterministic integration demo, not an LLM performance test."}
            write_json(p.root / "demo_result.json", out)
        else:
            p = Project(a.project)
            if a.command == "state": out = p.state()
            elif a.command == "context":
                from .loop import context
                from .feedback import compact
                latest = p.latest()
                if latest is None:
                    raise CadLoopError("NO_EVALUATION", "Evaluate before requesting worker context")
                out = context(p, compact(latest[1]), allow_source_edits=a.source_edits, include_source=a.include_source)
            elif a.command == "inspect": out = p.inspect(check=a.check, part=a.part, scenario=a.scenario, source=a.source,
                                                         path=a.path, start_line=a.start_line, max_lines=a.max_lines)
            elif a.command == "propose":
                if a.patch:
                    out = p.propose(read_json(a.patch))
                else:
                    if not a.base:
                        raise CadLoopError("BASE_REVISION_REQUIRED", "Pass --base from state, or a complete --patch file")
                    out = p.propose({"base_revision": a.base, "parameters": pairs(a.set), "reason": a.reason})
            elif a.command == "evaluate": out = p.evaluate(mode=mode, timeout=a.timeout, force=a.force, render=not a.no_render)
            elif a.command == "finish": out = p.finish(mode=mode, timeout=a.timeout)
            elif a.command == "search-parameter":
                from .search import search_parameter
                out = search_parameter(p, a.parameter, strict_loads(a.values), mode=mode,
                                       fixed=pairs(a.set), timeout=a.timeout)
            elif a.command == "view":
                latest = p.latest()
                if latest is None:
                    raise CadLoopError("NO_EVALUATION", "Evaluate before requesting a view")
                run, report = latest
                path = run / ("report.html" if a.kind == "report" else f"views/{a.kind}.png")
                if not path.exists():
                    raise CadLoopError("VIEW_UNAVAILABLE", "Reevaluate with rendering enabled; check view_error.json")
                out = {"revision": report["revision"], "kind": a.kind, "path": str(path), "units": "mm"}
            elif a.command == "loop":
                from .loop import ReplayProvider, ChatProvider, ProviderConfig, repair_loop
                if a.replay:
                    provider = ReplayProvider(read_json(a.replay))
                    allow_source = False
                    steps = a.max_steps
                    include_source = None
                else:
                    cfg = ProviderConfig.model_validate(read_json(a.provider_config))
                    provider = ChatProvider(cfg, p.control / "budget.json")
                    allow_source = cfg.allow_source_edits
                    steps = min(a.max_steps, cfg.max_steps)
                    include_source = cfg.include_source_in_context or cfg.allow_source_edits
                out = repair_loop(p, provider, mode=mode, max_steps=steps,
                                  allow_source_edits=allow_source, timeout=a.timeout, include_source=include_source)
        print(json.dumps(out, indent=2, allow_nan=False))
        status = out.get("status", "")
        if a.command == "loop" and status not in ("GEOMETRY_ACCEPTED", "PARAMETRIC_ACCEPTED"):
            return 2
        return 2 if status in ("REPAIR_REQUIRED", "PARAMETRIC_REPAIR_REQUIRED", "NO_FEASIBLE_CANDIDATE", "STEP_LIMIT", "ESCALATION_REQUIRED", "FINAL_VALIDATION_FAILED") else 0
    except CadLoopError as e:
        print(json.dumps(e.as_dict(), indent=2))
        return 3
    except Exception as e:
        print(json.dumps({"status": "error", "code": "INVALID_INPUT_OR_RUNTIME_ERROR",
                          "message": str(e)}, indent=2))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
