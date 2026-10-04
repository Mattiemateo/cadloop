"""Fixed synthetic checker benchmark; no inference or public benchmark tasks."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time

from cadloop.execution import runtime_identity
from cadloop.kerf import import_project
from cadloop.util import file_hash, package_digest, read_json, write_json


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "kerf_carrier"
CASES = {
    "responsive": (True, None, None),
    "responsive_buildpart": (True, "result = carrier(params)",
                              "from build123d import BuildPart, add\nshape = carrier(params)\nwith BuildPart() as part:\n    add(shape)"),
    "ignored_length": (False, 'p["length"]', "50"),
    "ignored_bore": (False, 'p["bore_diameter"] / 2', "11"),
    "moved_mounts_equal_mass": (False, '(-p["mount_x"], p["mount_x"])', "(-16, 16)"),
    "thickness_breaks_mounts": (False, '(-p["mount_x"], p["mount_x"])',
                                '(-(p["mount_x"] + p["thickness"] - 8), p["mount_x"] + p["thickness"] - 8)'),
}


def fingerprint(data: bytes) -> str:
    return sha256(data).hexdigest()


def canonical(data) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def fixtures():
    """Freeze all targets before any worker runs; nominal bore is the approved 22 mm."""
    source = (EXAMPLE / "model.py").read_text()
    spec = read_json(EXAMPLE / "spec.json")
    for parameter in spec["parameters"]:
        if parameter["name"] == "bore_diameter":
            parameter["value"] = 22
    requirements = read_json(EXAMPLE / "requirements.json")
    length = next(c for c in requirements["checks"] if c["id"] == "length")
    thickness = next(c for c in requirements["checks"] if c["id"] == "thickness")
    holes = next(c for c in requirements["checks"] if c["id"] == "interfaces")
    requirements["parametric_tests"] = [
        {"id": "length_54", "description": "Length grows from 50 to 54 mm; other targets remain protected.",
         "parameters": {"length": 54},
         "overrides": [{**length, "minimum": 53.99, "maximum": 54.01,
                        "description": "Length 54.00 +/- 0.01 mm"}]},
        {"id": "bore_24", "description": "Central bore grows from 22 to 24 mm; mounting holes remain protected.",
         "parameters": {"bore_diameter": 24},
         "overrides": [{**holes, "description": "24 mm central bore; four 4 mm mounts at (+/-18, +/-13) mm",
                        "holes": [{**h, "radius": 12} if h["x"] == h["y"] == 0 else h
                                         for h in holes["holes"]]}]},
        {"id": "thickness_10", "description": "Thickness grows from 8 to 10 mm; hole positions remain protected.",
         "parameters": {"thickness": 10},
         "overrides": [{**thickness, "minimum": 9.99, "maximum": 10.01,
                        "description": "Thickness 10.00 +/- 0.01 mm"}]},
    ]
    programs = {}
    for name, (_, old, new) in CASES.items():
        if old is None:
            programs[name] = source
        else:
            if source.count(old) != 1:
                raise ValueError(f"Fixture replacement is no longer unique: {name}")
            programs[name] = source.replace(old, new, 1)
    return spec, requirements, programs


def p95(values):
    return sorted(values)[math.ceil(0.95 * len(values)) - 1]


def summarize(records):
    if not records:
        raise ValueError("Empty benchmark suite")
    total = len(records)
    out = {"attempts": total, "cases": len({r["case"] for r in records}),
           "infrastructure_errors": sum(r["error"] is not None for r in records),
           "scenario_infrastructure_attempts": sum(bool(r.get("scenario_infrastructure")) for r in records),
           "scenario_indeterminate_attempts": sum(bool(r.get("scenario_indeterminate")) for r in records)}
    for arm, field in (("legacy_geometry_only", "geometry_accepted"),
                       ("required_response", "task_accepted")):
        out[arm] = {
            "correct": sum(r["error"] is None and r[field] is r["expected_valid"] for r in records),
            "denominator": total,
            "false_accepts": sum(not r["expected_valid"] and r[field] is True for r in records),
            "false_rejects": sum(r["expected_valid"] and r[field] is not True for r in records),
        }
    for field in ("nominal_worker_seconds", "scenario_worker_seconds", "controller_overhead_seconds",
                  "total_wall_seconds"):
        values = [r[field] for r in records if r.get(field) is not None]
        out[field] = {"median": statistics.median(values) if values else None,
                      "p95_nearest_rank": p95(values) if values else None,
                      "measured": len(values), "denominator": total}
    return out


def equal_mass_evidence(records):
    pairs = []
    for repeat in sorted({r["repeat"] for r in records}):
        by_case = {r["case"]: r for r in records if r["repeat"] == repeat}
        a = by_case["responsive"].get("nominal_metrics", {}).get("carrier")
        b = by_case["moved_mounts_equal_mass"].get("nominal_metrics", {}).get("carrier")
        pairs.append({"repeat": repeat, "same_bounds_and_volume": None if not a or not b else
                      a["bounds_mm"] == b["bounds_mm"] and
                      abs(a["volume_mm3"] - b["volume_mm3"]) < 1e-6,
                      "responsive_volume_mm3": a["volume_mm3"] if a else None,
                      "moved_volume_mm3": b["volume_mm3"] if b else None})
    return pairs


def run_case(root, name, repeat, spec_path, req_path, source, fingerprints):
    attempt = root / f"repeat-{repeat:02d}" / name
    attempt.mkdir(parents=True, exist_ok=False)
    source_path = attempt / "source.py"
    source_path.write_text(source)
    expected = CASES[name][0]
    record = {"case": name, "repeat": repeat, "expected_valid": expected,
              "source_sha256": fingerprint(source.encode()), **fingerprints,
              "geometry_accepted": None, "parametric_accepted": None, "task_accepted": None,
              "parametric_tests": None, "nominal_worker_seconds": None,
              "scenario_worker_seconds": None, "controller_overhead_seconds": None,
              "scenario_indeterminate": [], "scenario_infrastructure": [],
              "total_wall_seconds": None, "error": None,
              "usage": {"input_tokens": None, "output_tokens": None, "cost": None}}
    started = time.perf_counter()
    try:
        if (file_hash(spec_path) != fingerprints["spec_sha256"] or
                file_hash(req_path) != fingerprints["requirements_sha256"] or
                file_hash(source_path) != record["source_sha256"] or
                file_hash(Path(__file__)) != fingerprints["driver_sha256"] or
                package_digest() != fingerprints["controller_digest"]):
            raise ValueError("Source, requirements, spec, or controller changed after the plan was frozen")
        project = import_project(attempt / "project", spec=spec_path, code=source_path,
                                 requirements=req_path, part="carrier")
        state = project.state()
        record["revision"] = state["revision"]
        record["initial_parameters"] = state["parameters"]
        result = project.evaluate(mode="docker", force=True, render=False)
        record.update({field: result.get(field) for field in
                       ("geometry_accepted", "parametric_accepted", "task_accepted", "parametric_tests")})
        record["run_directory"] = result.get("run_directory")
        if result.get("geometry_accepted") and len(record["parametric_tests"] or []) != fingerprints["scenario_count"]:
            raise ValueError("Required scenario outcomes are missing")
        if result.get("run_directory"):
            run = Path(result["run_directory"])
            execution = read_json(run / "execution.json")
            if execution.get("runtime") != fingerprints["runtime"] or execution.get("mode") != "docker":
                raise ValueError("Actual worker runtime differs from frozen plan")
            record["runtime"] = execution["runtime"]
            record["nominal_worker_seconds"] = sum(s["elapsed_seconds"] for s in execution.get("stages", []))
            record["nominal_checks"] = [c for c in project.inspect()["report"]["checks"]
                                        if not c["id"].startswith("AUTO_parametric_")]
            record["nominal_metrics"] = read_json(run / "verification" / "metrics.json")
            record["scenario_worker_seconds"] = 0.
            for outcome in record["parametric_tests"] or []:
                scenario_run = run / outcome["run_directory"]
                scenario_execution = read_json(scenario_run / "execution.json")
                if scenario_execution.get("runtime") != fingerprints["runtime"]:
                    raise ValueError("Scenario worker runtime differs from frozen plan")
                record["scenario_worker_seconds"] += sum(s["elapsed_seconds"]
                                                          for s in scenario_execution.get("stages", []))
                if outcome["summary"]["indeterminate"]:
                    record["scenario_indeterminate"].append(
                        {"id": outcome["id"], "blocker_ids": outcome["blocker_ids"]})
                if any(identifier in outcome["blocker_ids"] for identifier in ("AUTO_execution", "AUTO_artifacts")):
                    record["scenario_infrastructure"].append(
                        {"id": outcome["id"], "blocker_ids": outcome["blocker_ids"]})
        if type(record["geometry_accepted"]) is not bool or type(record["task_accepted"]) is not bool:
            raise ValueError("Evaluation did not return both acceptance decisions")
    except Exception as exc:
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        record["total_wall_seconds"] = time.perf_counter() - started
        if record["nominal_worker_seconds"] is not None and record["scenario_worker_seconds"] is not None:
            record["controller_overhead_seconds"] = max(0., record["total_wall_seconds"]
                                                        - record["nominal_worker_seconds"]
                                                        - record["scenario_worker_seconds"])
        write_json(attempt / "result.json", record)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--seed", type=int, default=29)
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    spec, requirements, programs = fixtures()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "spec.json", spec)
    write_json(output / "requirements.json", requirements)
    runtime = runtime_identity("docker")
    repo_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    fingerprints = {"task_sha256": fingerprint(canonical({"programs": programs, "spec": spec,
                                                              "requirements": requirements})),
                    "spec_sha256": file_hash(output / "spec.json"),
                    "requirements_sha256": file_hash(output / "requirements.json"),
                    "driver_sha256": file_hash(Path(__file__)),
                    "worker_image_id": runtime["image_id"], "runtime": runtime,
                    "scenario_count": len(requirements["parametric_tests"]),
                    "policy_fingerprint": runtime["policy_fingerprint"], "repository_commit": repo_commit,
                    "controller_digest": package_digest(), "python_version": sys.version.split()[0],
                    "execution_mode": "docker", "model": None, "host": None}
    rng = random.Random(args.seed)
    records = []
    order = []
    for repeat in range(1, args.repeat + 1):
        names = list(programs)
        rng.shuffle(names)
        order.append(names)
    write_json(output / "plan.json", {"seed": args.seed, "repeat_count": args.repeat,
                                      "order": order, "fingerprints": fingerprints,
                                      "cases": {name: {"expected_valid": CASES[name][0],
                                                       "source_sha256": fingerprint(source.encode())}
                                                for name, source in programs.items()}})
    for repeat, names in enumerate(order, 1):
        for name in names:
            record = run_case(output, name, repeat, output / "spec.json",
                              output / "requirements.json", programs[name], fingerprints)
            records.append(record)
            print(json.dumps({key: record[key] for key in ("repeat", "case", "expected_valid",
                                                           "geometry_accepted", "task_accepted", "error",
                                                           "total_wall_seconds")}), flush=True)
    report = {"scope": "fixed synthetic checker benchmark; no model calls or holdout claims",
              "timing_note": "Two classifiers share one run; controller overhead is total attempt wall time minus worker stage times and includes project setup and artifact reads.",
              "seed": args.seed, "repeat_count": args.repeat, "order": order,
              "fingerprints": fingerprints, "summary": summarize(records),
              "equal_mass_evidence": equal_mass_evidence(records), "results": records}
    report["benchmark_passed"] = (report["summary"]["infrastructure_errors"] == 0 and
                                  report["summary"]["scenario_infrastructure_attempts"] == 0 and
                                  report["summary"]["scenario_indeterminate_attempts"] == 0 and
                                  report["summary"]["required_response"]["correct"] == len(records) and
                                  report["summary"]["legacy_geometry_only"]["false_accepts"] > 0 and
                                  all(p["same_bounds_and_volume"] is True for p in report["equal_mass_evidence"]))
    write_json(output / "report.json", report)
    print(json.dumps({"output": str(output / "report.json"), "benchmark_passed": report["benchmark_passed"],
                      "summary": report["summary"]}, indent=2), flush=True)
    return 0 if report["benchmark_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
