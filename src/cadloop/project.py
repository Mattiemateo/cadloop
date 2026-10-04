"""Revision-bound transactions, protected requirements, sealed run artifacts."""
from __future__ import annotations
import ast
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid
from .contracts import Requirements, Proposal
from .errors import CadLoopError
from .util import (read_json, write_json, digest, tree_hashes, within, file_hash,
                   versions, package_digest, project_lock)
from .execution import run_stage, runtime_identity
from .feedback import compact
from .parametric import accepted, run_scenarios, apply_gate


class Project:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.control = self.root / ".cadloop"
        self.design = self.root / "design"
        if not (self.control / "anchor.json").is_file():
            raise CadLoopError("PROJECT_NOT_INITIALIZED", "Run cadloop init before using this directory.")

    @classmethod
    def initialize(cls, root: str | Path, *, backend: str = "cadquery"):
        root = Path(root).resolve()
        if root.exists() and any(root.iterdir()):
            raise CadLoopError("DIRECTORY_NOT_EMPTY", "Initialization will not overwrite an existing directory.")
        if backend not in ("cadquery", "build123d"):
            raise CadLoopError("BACKEND_UNSUPPORTED", "Choose cadquery or build123d")
        template = Path(__file__).parent / "templates" / "plate_stack"
        root.mkdir(parents=True, exist_ok=True)
        (root / "design").mkdir()
        shutil.copy2(template / "requirements.json", root / "requirements.json")
        shutil.copy2(template / "design" / "parameters.json", root / "design" / "parameters.json")
        shutil.copy2(template / "design" / f"model_{backend}.py", root / "design" / "model.py")
        (root / ".cadloop").mkdir()
        write_json(root / ".cadloop" / "anchor.json",
                   {"schema_version": 1, "requirement_sha256": file_hash(root / "requirements.json"),
                    "backend": backend, "created_ns": time.time_ns()})
        write_json(root / ".cadloop" / "receipts.json", {})
        (root / ".gitignore").write_text(".cadloop/\nexports/\n__pycache__/\n")
        p = cls(root)
        p.requirements()
        return p

    @classmethod
    def create(cls, root: str | Path, *, requirements: str | Path, design_dir: str | Path):
        """Create a NEW project from human-reviewed requirements and design source.

        This does not repin or weaken an existing project's requirements.
        """
        root, source = Path(root).resolve(), Path(design_dir).resolve()
        if root.exists() and any(root.iterdir()):
            raise CadLoopError("DIRECTORY_NOT_EMPTY", "A reviewed-project import never overwrites existing files")
        if root.is_relative_to(source):
            raise CadLoopError("UNSAFE_PATH", "New project must not be inside its input design directory")
        data = read_json(Path(requirements))
        req = Requirements.model_validate(data)
        hashes = tree_hashes(source)
        if "model.py" not in hashes or "parameters.json" not in hashes:
            raise CadLoopError("DESIGN_INCOMPLETE", "Provide model.py and parameters.json")
        if len(hashes) > 40 or any(not name.endswith(".py") and name != "parameters.json" for name in hashes):
            raise CadLoopError("DESIGN_UNSUPPORTED", "v0 design imports contain Python modules and parameters.json only")
        if sum((source / name).stat().st_size for name in hashes) > 500_000:
            raise CadLoopError("SOURCE_TOO_LARGE", "Source exceeds the v0 budget")
        parameters = req.validate_parameters(read_json(source / "parameters.json"))
        for name in hashes:
            if name.endswith(".py"):
                ast.parse((source / name).read_text(), filename=name)
        root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, root / "design", ignore=shutil.ignore_patterns("__pycache__"))
        write_json(root / "design" / "parameters.json", parameters)
        write_json(root / "requirements.json", data)
        (root / ".cadloop").mkdir()
        write_json(root / ".cadloop" / "anchor.json",
                   {"schema_version": 1, "requirement_sha256": file_hash(root / "requirements.json"),
                    "backend": "reviewed_custom_python", "created_ns": time.time_ns()})
        write_json(root / ".cadloop" / "receipts.json", {})
        (root / ".gitignore").write_text(".cadloop/\nexports/\n__pycache__/\n")
        return cls(root)

    def requirements(self):
        anchor = read_json(self.control / "anchor.json")
        if file_hash(self.root / "requirements.json") != anchor["requirement_sha256"]:
            raise CadLoopError("REQUIREMENTS_CHANGED", "Protected requirements changed. Review them in a new project; the worker cannot weaken them.")
        return Requirements.model_validate(read_json(self.root / "requirements.json"))

    def parameters(self):
        p = read_json(self.design / "parameters.json")
        self.requirements().validate_parameters(p)
        return p

    def revision(self):
        self.parameters()
        hashes = tree_hashes(self.design)
        if len(hashes) > 40 or sum((self.design / p).stat().st_size for p in hashes) > 500_000:
            raise CadLoopError("SOURCE_TOO_LARGE", "Source exceeds the v0 project budget")
        return digest({"design": hashes, "requirements": file_hash(self.root / "requirements.json"),
                       "environment": versions(), "controller": package_digest()})

    def event(self, kind, data):
        with (self.control / "events.jsonl").open("a") as f:
            f.write(json.dumps({"time_ns": time.time_ns(), "kind": kind, **data}, allow_nan=False) + "\n")

    def snapshot(self, revision):
        target = self.control / "snapshots" / revision
        if not target.exists():
            shutil.copytree(self.design, target, ignore=shutil.ignore_patterns("__pycache__"))
        return target

    def propose(self, proposal: Proposal | dict):
        proposal = Proposal.model_validate(proposal)
        with project_lock(self.control):
            revision = self.revision()
            if revision != proposal.base_revision:
                raise CadLoopError("STALE_REVISION", "Proposal was based on a different design revision", current_revision=revision)
            old = self.parameters()
            requirements = self.requirements()
            new = requirements.validate_parameters({**old, **proposal.parameters})
            # Integral floats and ints compare equal in Python, but only an int
            # is usable by range/index operations in authoring code. Preserve
            # type-only repairs of parameters stored by older controllers.
            parameters_changed = new != old or any(
                spec.kind == "integer" and type(old[name]) is not int
                for name, spec in requirements.parameters.items())
            if not proposal.edits and not parameters_changed:
                raise CadLoopError("NO_CHANGE", "The proposal does not change the design")
            self.snapshot(revision)
            staging = Path(tempfile.mkdtemp(prefix="proposal-", dir=self.control))
            staged = staging / "design"
            backup = staging / "backup"
            try:
                shutil.copytree(self.design, staged, ignore=shutil.ignore_patterns("__pycache__"))
                if parameters_changed:
                    write_json(staged / "parameters.json", new)
                for edit in proposal.edits:
                    if not edit.path.endswith(".py") or len(Path(edit.path).parts) > 3:
                        raise CadLoopError("EDIT_NOT_ALLOWED", "Source edits must target a Python file inside design/")
                    path = within(staged, edit.path)
                    original = path.read_text()
                    if original.count(edit.old) != 1:
                        raise CadLoopError("EDIT_AMBIGUOUS", "Source edit must match exactly once")
                    modified = original.replace(edit.old, edit.new, 1)
                    ast.parse(modified, filename=edit.path)
                    path.write_text(modified)
                hashes = tree_hashes(staged)
                if len(hashes) > 40 or sum((staged / p).stat().st_size for p in hashes) > 500_000:
                    raise CadLoopError("SOURCE_TOO_LARGE", "Proposed source exceeds the v0 project budget")
                if hashes == tree_hashes(self.design):
                    raise CadLoopError("NO_CHANGE", "The source proposal leaves the design unchanged")
                self.design.rename(backup)
                try:
                    staged.rename(self.design)
                except BaseException:
                    backup.rename(self.design)
                    raise
            finally:
                shutil.rmtree(staging, ignore_errors=True)
            candidate = self.revision()
            self.snapshot(candidate)
            self.event("proposal", {"base_revision": revision, "revision": candidate,
                                    "parameters": proposal.parameters, "source_paths": [e.path for e in proposal.edits],
                                    "reason": proposal.reason})
            return {"status": "CANDIDATE_STAGED", "revision": candidate,
                    "base_revision": revision, "geometry_accepted": False}

    def _seal(self, run):
        hashes = tree_hashes(run)
        hashes.pop("receipt.json", None)
        receipt = {"schema_version": 1, "files": hashes}
        write_json(run / "receipt.json", receipt)
        receipts = read_json(self.control / "receipts.json")
        receipts[run.name] = file_hash(run / "receipt.json")
        write_json(self.control / "receipts.json", receipts)

    def verify_receipt(self, run):
        receipts = read_json(self.control / "receipts.json")
        if run.name not in receipts or file_hash(run / "receipt.json") != receipts[run.name]:
            raise CadLoopError("ARTIFACT_TAMPERED", "Run receipt does not match the controller record")
        expected = read_json(run / "receipt.json")["files"]
        actual = tree_hashes(run)
        actual.pop("receipt.json", None)
        if actual != expected:
            raise CadLoopError("ARTIFACT_TAMPERED", "Run artifacts were changed, added or removed",
                               changed=sorted(k for k in set(actual)|set(expected) if actual.get(k) != expected.get(k)))

    def latest(self, *, require_current=True):
        pointer = self.control / "latest.json"
        if not pointer.exists():
            return None
        data = read_json(pointer)
        run = self.control / "runs" / data["run_id"]
        if run.parent != self.control / "runs" or not run.is_dir() or run.is_symlink():
            raise CadLoopError("UNSAFE_PATH", "Invalid run pointer")
        self.verify_receipt(run)
        report = read_json(run / "verification" / "report.json")
        if require_current and report["revision"] != self.revision():
            raise CadLoopError("STALE_REVISION", "Latest geometry does not belong to the current source; evaluate it first")
        return run, report

    def _render_preview(self, run, *, timeout, mode="trusted-native", runtime=None):
        options = {"image": runtime["image_id"]} if mode == "docker" else {}
        try:
            execution = run_stage("render", run, mode=mode, timeout=timeout, **options)
            write_json(run / "preview_execution.json", execution)
            if execution["exit_code"] != 0:
                write_json(run / "view_error.json", {
                    "code":"VIEW_TIMEOUT" if execution["timed_out"] else "VIEW_FAILED",
                    "message":"The preview worker failed; independent geometric measurements are unchanged.",
                    "execution":execution})
            elif mode == "docker":
                preview = run / "preview"
                tree_hashes(preview)  # Reject symlinks before moving renderer output.
                if read_json(preview / "views/manifest.json")["revision"] != read_json(run / "verification/report.json")["revision"]:
                    raise CadLoopError("STALE_REVISION", "Renderer returned a different revision")
                if not (preview / "views/overview.png").is_file() or not (preview / "views/section_xz.png").is_file():
                    raise CadLoopError("VIEW_UNAVAILABLE", "Renderer did not produce required previews")
                report_html = within(preview, "report.html")
                shutil.rmtree(run / "views", ignore_errors=True)
                shutil.move(str(preview / "views"), run / "views")
                shutil.move(str(report_html), run / "report.html")
        finally:
            if mode == "docker":
                shutil.rmtree(run / "preview", ignore_errors=True)
            shutil.rmtree(run / "tmp", ignore_errors=True)

    def evaluate(self, *, mode: str, timeout=45., force=False, render=True):
        from .worker import make_report
        from .checks import result
        if mode not in ("trusted-native", "docker"):
            raise CadLoopError("EXECUTION_MODE_REQUIRED", "Explicitly select trusted-native or Docker execution")
        if type(timeout) not in (int, float) or not 0 < timeout <= 300:
            raise CadLoopError("INVALID_TIMEOUT", "Worker timeout must be in (0, 300] seconds")
        with project_lock(self.control):
            revision = self.revision()
            req = self.requirements()
            runtime, runtime_error = None, None
            try:
                runtime = runtime_identity(mode)
            except Exception as exc:
                runtime_error = exc
            stage_options = {"image": runtime["image_id"]} if mode == "docker" and runtime else {}
            if not force:
                latest = self.latest(require_current=False)
                if latest and latest[1]["revision"] == revision:
                    cached_run, cached_report = latest
                    execution = read_json(cached_run / "execution.json")
                    stages = execution.get("stages", [])
                    reuse = (runtime is not None and execution.get("runtime") == runtime
                             and execution.get("mode") == mode and len(stages) == 2
                             and all(s.get("exit_code") == 0 and not s.get("timed_out") for s in stages)
                             and cached_report["summary"]["indeterminate"] == 0)
                    has_views = (cached_run / "views" / "overview.png").is_file() and (cached_run / "report.html").is_file()
                    if reuse and render and not has_views:
                        # Derive a NEW sealed view checkpoint; do not mutate old evidence
                        # or rerun CAD merely because an image was requested later.
                        view_run = self.control / "runs" / (revision[:12] + "-" + uuid.uuid4().hex[:8])
                        shutil.copytree(cached_run, view_run)
                        (view_run / "receipt.json").unlink(missing_ok=True)
                        (view_run / "view_error.json").unlink(missing_ok=True)
                        try:
                            self._render_preview(view_run, timeout=timeout, mode=mode, runtime=runtime)
                        except Exception as e:
                            write_json(view_run / "view_error.json", {"code":"VIEW_UNAVAILABLE", "message":str(e)})
                        write_json(view_run / "derived_from.json", {"run_id":cached_run.name,
                                   "operation":"render_only", "geometry_reused":True})
                        self._seal(view_run)
                        write_json(self.control / "latest.json", {"run_id":view_run.name, "revision":revision})
                        if accepted(cached_report):
                            write_json(self.control / "last_accepted.json", {"run_id":view_run.name, "revision":revision})
                        self.event("view_checkpoint", {"run_id":view_run.name, "source_run_id":cached_run.name})
                        cached_run = view_run
                    if reuse:
                        return {**compact(cached_report), "run_id": cached_run.name, "cached": True,
                                "run_directory": str(cached_run)}
            run_id = revision[:12] + "-" + uuid.uuid4().hex[:8]
            run = self.control / "runs" / run_id
            (run / "input").mkdir(parents=True)
            shutil.copytree(self.design, run / "input" / "design", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copy2(self.root / "requirements.json", run / "input" / "requirements.json")
            write_json(run / "input" / "meta.json", {"schema_version": 1, "revision": revision,
                                                     "versions": versions(), "controller_digest": package_digest()})
            before = tree_hashes(run / "input")
            stages = []
            report = None
            outcomes = []
            try:
                if runtime_error:
                    raise runtime_error
                build_stage = run_stage("build", run, mode=mode, timeout=timeout, **stage_options)
                stages.append(build_stage)
                if build_stage["exit_code"] != 0:
                    raise CadLoopError("BUILD_TIMEOUT" if build_stage["timed_out"] else "BUILD_FAILED",
                                       "CAD build failed; inspect build logs", execution=build_stage)
                if tree_hashes(run / "input") != before:
                    raise CadLoopError("INPUT_MUTATED", "The build worker altered its input files")
                verification = run_stage("verify", run, mode=mode, timeout=timeout, **stage_options)
                stages.append(verification)
                if verification["exit_code"] != 0:
                    raise CadLoopError("VERIFY_TIMEOUT" if verification["timed_out"] else "VERIFY_FAILED",
                                       "Trusted verification did not complete", execution=verification)
                report = read_json(run / "verification" / "report.json")
                if report["revision"] != revision:
                    raise CadLoopError("STALE_REVISION", "Verifier returned the wrong revision")
                if tree_hashes(run / "input") != before or self.revision() != revision:
                    raise CadLoopError("INPUT_MUTATED", "Input or source changed during evaluation")
                geometry_before = tree_hashes(run / "geometry")
                verification_before = tree_hashes(run / "verification")
                if report["geometry_accepted"] and req.parametric_tests:
                    outcomes = run_scenarios(run, req, revision, mode=mode, timeout=timeout, runtime=runtime)
                if (tree_hashes(run / "input") != before or self.revision() != revision or
                        tree_hashes(run / "geometry") != geometry_before or
                        tree_hashes(run / "verification") != verification_before):
                    raise CadLoopError("INPUT_MUTATED", "Nominal source or evidence changed during parameter tests")
            except Exception as e:
                checks = [result("AUTO_execution", "indeterminate", getattr(e, "code", "EXECUTION_ERROR"),
                                 str(e), e.details if isinstance(e, CadLoopError) else {})]
                checks.extend(result(c.id, "indeterminate", "BUILD_UNAVAILABLE", c.description,
                                     hint=c.edit_hint) for c in req.checks)
                report = make_report(revision, req, checks)
            report = apply_gate(report, req, outcomes)
            write_json(run / "verification" / "report.json", report)
            write_json(run / "execution.json", {"stages": stages, "mode": mode, "runtime": runtime,
                                                 "native_security_warning": mode == "trusted-native"})
            write_json(run / "feedback.json", compact(report))
            # Rendering is trusted, separate from generated code; it cannot change acceptance.
            if render and (run / "geometry" / "scene.json").exists():
                try:
                    self._render_preview(run, timeout=timeout, mode=mode, runtime=runtime)
                except Exception as e:
                    write_json(run / "view_error.json", {"code": "VIEW_UNAVAILABLE", "message": str(e)})
            shutil.rmtree(run / "tmp", ignore_errors=True)
            self._seal(run)
            write_json(self.control / "latest.json", {"run_id": run_id, "revision": revision})
            if accepted(report):
                write_json(self.control / "last_accepted.json", {"run_id": run_id, "revision": revision})
            self.event("evaluation", {"revision": revision, "run_id": run_id, "status": report["status"]})
            return {**compact(report), "run_id": run_id, "cached": False, "run_directory": str(run)}

    def inspect(self, *, check=None, part=None, scenario=None, source=False, path="model.py", start_line=1, max_lines=180):
        if source:
            if (type(start_line) is not int or start_line < 1 or type(max_lines) is not int
                    or not 1 <= max_lines <= 180 or not path.endswith(".py")):
                raise CadLoopError("SOURCE_WINDOW_INVALID", "Use a Python path, positive start line and 1..180 lines")
            filename = within(self.design, path)
            lines = filename.read_text(encoding="utf-8").splitlines()
            if start_line > max(len(lines), 1):
                raise CadLoopError("SOURCE_WINDOW_INVALID", "Start line is beyond this source file")
            end = min(start_line-1+max_lines, len(lines))
            return {"revision": self.revision(), "path": "design/" + path,
                    "source": "\n".join(f"{i+1}: {lines[i]}" for i in range(start_line-1,end)),
                    "start_line": start_line, "end_line": end, "total_lines": len(lines),
                    "next_start_line": end+1 if end < len(lines) else None,
                    "truncated": end < len(lines)}
        latest = self.latest()
        if latest is None:
            raise CadLoopError("NO_EVALUATION", "Evaluate the model first")
        run, report = latest
        if scenario:
            matches = [item for item in report.get("parametric_tests", []) if item["id"] == scenario]
            if not matches:
                raise CadLoopError("SCENARIO_NOT_RUN", "Scenario is unknown or nominal geometry prevented its execution")
            evidence = within(run, matches[0]["run_directory"] + "/verification/report.json")
            return {"revision": report["revision"], "scenario": scenario,
                    "parameters": matches[0]["parameters"], "report": read_json(evidence)}
        if check:
            matches = [c for c in report["checks"] if c["id"] == check]
            if not matches:
                raise CadLoopError("CHECK_NOT_FOUND", "Unknown check id")
            return {"revision": report["revision"], "check": matches[0]}
        if part:
            metrics = read_json(run / "verification" / "metrics.json")
            if part not in metrics:
                raise CadLoopError("PART_NOT_FOUND", "Part is missing or unknown")
            return {"revision": report["revision"], "part": part, "metrics": metrics[part]}
        return {"revision": report["revision"], "report": report}

    def state(self):
        revision = self.revision()
        latest = self.latest(require_current=False)
        return {"schema_version": 1, "revision": revision, "parameters": self.parameters(),
                "requirements": self.requirements().model_dump(),
                "latest_feedback": compact(latest[1]) if latest else None,
                "latest_is_current": bool(latest and latest[1]["revision"] == revision),
                "capabilities": ["dimension", "through_holes_z", "coaxial", "plane_contact",
                                 "clearance", "all_pairs_no_overlap", "parameter_and_source_patches", "required_parameter_responses"],
                "engineering_approved": False}

    def finish(self, *, mode, timeout=45.):
        with project_lock(self.control):
            return self._finish_locked(mode=mode, timeout=timeout)

    def _finish_locked(self, *, mode, timeout=45.):
        # Never trust a cached pass or the model's finish request. Rebuild and recheck.
        feedback = self.evaluate(mode=mode, timeout=timeout, force=True, render=True)
        if not accepted(feedback):
            return {**feedback, "exported": False}
        run = self.control / "runs" / feedback["run_id"]
        self.verify_receipt(run)
        report = read_json(run / "verification" / "report.json")
        if report["revision"] != self.revision():
            raise CadLoopError("STALE_REVISION", "Source changed before export")
        target = self.root / "exports" / run.name
        target.mkdir(parents=True, exist_ok=False)
        for folder in ("input", "geometry", "verification", "views", "parametric_tests"):
            if (run / folder).exists():
                shutil.copytree(run / folder, target / folder)
        for name in ("report.html", "feedback.json", "receipt.json", "execution.json",
                     "preview_execution.json", "view_error.json", "derived_from.json"):
            if (run / name).exists():
                shutil.copy2(run / name, target / ("source_run_receipt.json" if name == "receipt.json" else name))
        write_json(target / "export_manifest.json", {"revision": report["revision"], "files": tree_hashes(target),
                                                     "geometry_accepted": True, "engineering_approved": False,
                                                     "parametric_accepted": report.get("parametric_accepted"),
                                                     "task_accepted": accepted(report), "scope": report["scope"]})
        return {**feedback, "exported": True, "export_directory": str(target)}
