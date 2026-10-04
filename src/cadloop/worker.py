"""Separate entrypoints for generated-code execution and trusted verification."""
from __future__ import annotations
# Apply limits inside the fresh interpreter, never in Popen(preexec_fn): Python
# preexec callbacks can deadlock when the controller has rendering/kernel threads.
import os
if __name__ == "__main__" and os.name == "posix":
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64_000_000, 64_000_000))
import argparse
import importlib.util
import json
import sys
import traceback
from pathlib import Path
from .util import read_json, write_json, within
from .authoring import Scene
from .contracts import Requirements
from .errors import CadLoopError
from . import kernel as k
from .checks import run_checks, result, required_check_ids


def build(input_dir: Path, output: Path):
    design = input_dir / "design"
    parameters = read_json(design / "parameters.json")
    # The subprocess is deliberately separate from the verifier. Native mode is
    # for reviewed scripts only; use the Docker worker for untrusted generated code.
    sys.path.insert(0, str(design))
    spec = importlib.util.spec_from_file_location("cadloop_generated_model", design / "model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scene = module.build(parameters)
    if isinstance(scene, dict):
        s = Scene()
        for name, shape in scene.items():
            s.add(name, shape)
        scene = s
    if not isinstance(scene, Scene) or not scene.parts or len(scene.parts) > 32:
        raise CadLoopError("INVALID_SCENE", "build(parameters) must return Scene or a nonempty dict of up to 32 parts")
    output.mkdir(parents=True, exist_ok=True)
    for name, raw in scene.parts.items():
        k.write_brep(raw, output / "parts" / f"{name}.brep")
    assembly = k.compound(scene.parts.values())
    k.write_brep(assembly, output / "assembly.brep")
    k.write_step(assembly, output / "assembly.step")
    write_json(output / "scene.json", {"schema_version": 1, "units": "mm",
                                      "parts": {name: f"parts/{name}.brep" for name in scene.parts}})
    write_json(output / "feature_trace.json", {"features": scene.trace,
                                               "native_feature_tree": False})


def load_geometry(root: Path):
    manifest = read_json(within(root, "scene.json"))
    if set(manifest) != {"schema_version", "units", "parts"} or manifest["schema_version"] != 1 or manifest["units"] != "mm":
        raise CadLoopError("INVALID_SCENE", "Unsupported scene schema or units")
    mapping = manifest["parts"]
    if not isinstance(mapping, dict) or not 1 <= len(mapping) <= 32:
        raise CadLoopError("INVALID_SCENE", "Scene part count is outside supported bounds")
    import re
    parts = {}
    for name, filename in mapping.items():
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", name) or filename != f"parts/{name}.brep":
            raise CadLoopError("UNSAFE_PATH", "Invalid part id or body path in scene")
        parts[name] = k.read_brep(within(root, filename))
    actual = {str(p.relative_to(root)) for p in (root / "parts").iterdir()}
    if actual != set(mapping.values()):
        raise CadLoopError("ARTIFACT_INVENTORY_MISMATCH", "Unregistered files in parts directory")
    return parts


def verify(input_dir: Path, geometry: Path, output: Path):
    req = Requirements.model_validate(read_json(input_dir / "requirements.json"))
    revision = read_json(input_dir / "meta.json")["revision"]
    checks = []
    parts = {}
    try:
        parts = load_geometry(geometry)
        aggregate = k.compound(parts.values())
        source_metrics = k.metrics(aggregate)
        # Validate both deliverable formats independently. A self-declared success
        # from the build process is never accepted as geometric evidence.
        for name, reader in (("assembly.brep", k.read_brep), ("assembly.step", k.read_step)):
            try:
                assembled = reader(within(geometry, name))
                ma, mb = source_metrics, k.metrics(assembled)
                missing_volume = k.difference_volume(aggregate, assembled)
                added_volume = k.difference_volume(assembled, aggregate)
                okay = (ma["solid_count"] == mb["solid_count"] and mb["valid"] and
                        not mb["contains_free_topology"] and mb["volume_mm3"] > 0 and
                        0 <= missing_volume < req.max_overlap_mm3 and
                        0 <= added_volume < req.max_overlap_mm3)
                checks.append(result("AUTO_export_" + name.replace(".", "_"),
                                     "pass" if okay else "fail", "OK" if okay else "EXPORT_MISMATCH",
                                     f"{name} agrees with registered geometry",
                                     {"source_solids": ma["solid_count"], "export_solids": mb["solid_count"],
                                      "missing_volume_mm3": missing_volume, "added_volume_mm3": added_volume,
                                      "method": "solid_count_and_bidirectional_BREP_boolean_difference"}))
            except Exception as e:
                checks.append(result("AUTO_export_" + name.replace(".", "_"), "indeterminate",
                                     getattr(e, "code", "KERNEL_INDETERMINATE"), str(e)))
    except Exception as e:
        checks.append(result("AUTO_artifacts", "indeterminate", getattr(e, "code", "ARTIFACT_ERROR"), str(e)))
    measurements = {}
    checks.extend(run_checks(parts, req, metrics_out=measurements))
    report = make_report(revision, req, checks)
    write_json(output / "report.json", report)
    write_json(output / "metrics.json", measurements)
    return report


def make_report(revision, req, checks):
    from collections import Counter
    checks = list(checks)
    expected_ids = required_check_ids(req)
    counts = Counter(c["id"] for c in checks)
    missing = sorted(expected_ids - set(counts))
    duplicate = sorted(name for name,count in counts.items() if count != 1)
    if missing or duplicate:
        checks.append(result("AUTO_check_coverage", "fail", "CHECK_COVERAGE_INVALID",
                             "Required custom and automatic checks must each appear exactly once",
                             {"missing": missing, "duplicate": duplicate}))
    accepted = bool(checks) and all(c["status"] == "pass" for c in checks)
    return {"schema_version": 1, "revision": revision, "units": "mm",
            "status": "GEOMETRY_ACCEPTED" if accepted else "REPAIR_REQUIRED",
            "geometry_accepted": accepted, "engineering_approved": False,
            "engineering_blockers": req.engineering_blockers,
            "scope": "nominal_geometry_only", "checks": checks,
            "summary": {x: sum(c["status"] == x for c in checks)
                        for x in ("pass", "fail", "indeterminate", "not_applicable")},
            "numerical_mm": req.numerical_mm,
            "coverage_limits": ["No physical fit, material strength, fastener or motion certification.",
                                "Hole inspection supports unsplit complete analytic Z bores only.",
                                "Dimension checks use axis-aligned BREP bounds, not arbitrary wall thickness.",
                                "No native Onshape feature tree is generated."]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["build", "verify", "render"])
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--geometry", type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    try:
        if a.stage == "build":
            build(a.input, a.output)
        elif a.stage == "verify":
            verify(a.input, a.geometry, a.output)
        else:
            from .views import render_report
            run = a.input.parent
            if (a.geometry is None) != (a.report is None):
                raise CadLoopError("VIEW_INPUT_INVALID", "Render requires both geometry and report paths")
            if a.report is None:
                render_report(run, read_json(run / "verification" / "report.json"))
            else:
                render_report(run, read_json(a.report), output_root=a.output, geometry_dir=a.geometry)
        print(json.dumps({"status": "completed", "stage": a.stage}))
    except BaseException as e:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"status": "error", "code": getattr(e, "code", "WORKER_ERROR"),
                          "message": str(e)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
