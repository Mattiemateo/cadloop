"""Required parameter-response tests over isolated copies of nominal inputs."""
from __future__ import annotations

from pathlib import Path
import shutil

from .errors import CadLoopError
from .execution import run_stage
from .feedback import compact
from .util import digest, read_json, tree_hashes, write_json


def accepted(report):
    """Legacy nominal contracts have no required parametric tests."""
    return report.get("task_accepted", report["geometry_accepted"])


def run_scenarios(run: Path, requirements, revision: str, *, mode, timeout, runtime):
    from .checks import required_check_ids, result
    nominal = read_json(run / "input/design/parameters.json")
    outcomes = []
    options = {"image": runtime["image_id"]} if mode == "docker" else {}
    for scenario in requirements.parametric_tests:
        directory = scenario.id[:20] + "-" + digest({"run": run.name, "scenario": scenario.id})[:12]
        target = run / "parametric_tests" / directory
        shutil.copytree(run / "input", target / "input")
        values = {**nominal, **scenario.parameters}
        req = requirements.for_scenario(scenario)
        scenario_revision = digest({"nominal_revision": revision, "scenario": scenario.model_dump(),
                                    "parameters": values, "runtime": runtime})
        write_json(target / "input/design/parameters.json", values)
        write_json(target / "input/requirements.json", req.model_dump())
        write_json(target / "input/meta.json", {"schema_version": 1, "revision": scenario_revision,
                   "nominal_revision": revision, "scenario": scenario.model_dump(), "runtime": runtime})
        before = tree_hashes(target / "input")
        stages = []
        try:
            req.validate_parameters(values)
            if values == nominal:
                raise CadLoopError("PARAMETRIC_NO_CHANGE", "Scenario must change at least one nominal parameter")
            for stage in ("build", "verify"):
                execution = run_stage(stage, target, mode=mode, timeout=timeout, **options)
                stages.append(execution)
                if execution["exit_code"] != 0:
                    raise CadLoopError("PARAMETRIC_EXECUTION_FAILED", "Required scenario worker failed", execution=execution)
                if tree_hashes(target / "input") != before:
                    raise CadLoopError("INPUT_MUTATED", "Scenario worker altered its approved inputs")
            report = read_json(target / "verification/report.json")
            if report["revision"] != scenario_revision:
                raise CadLoopError("STALE_REVISION", "Scenario verifier returned stale evidence")
            ids = [check["id"] for check in report["checks"]]
            if report["geometry_accepted"] and (len(ids) != len(set(ids)) or set(ids) != required_check_ids(req)
                                               or any(c["status"] != "pass" for c in report["checks"])):
                raise CadLoopError("CHECK_COVERAGE_INVALID", "Scenario acceptance requires every expected check exactly once")
        except Exception as exc:
            from .worker import make_report
            report = make_report(scenario_revision, req, [result("AUTO_execution", "indeterminate",
                getattr(exc, "code", "PARAMETRIC_EXECUTION_FAILED"), str(exc),
                exc.details if isinstance(exc, CadLoopError) else {})])
            write_json(target / "verification/report.json", report)
        finally:
            shutil.rmtree(target / "tmp", ignore_errors=True)
        write_json(target / "execution.json", {"mode": mode, "runtime": runtime, "stages": stages})
        outcomes.append({"id": scenario.id, "description": scenario.description,
                         "parameters": scenario.parameters, "scenario_sha256": digest(scenario.model_dump()),
                         "run_directory": target.relative_to(run).as_posix(), **compact(report)})
    return outcomes


def apply_gate(report, requirements, outcomes):
    """Nominal geometry and required response are separately reported."""
    from .checks import result
    required = requirements.parametric_tests
    report["parametric_tests"] = outcomes
    if not required:
        report.update(parametric_accepted=None, task_accepted=report["geometry_accepted"])
        return report
    complete = [item["id"] for item in outcomes] == [test.id for test in required]
    passed = complete and all(item["geometry_accepted"] for item in outcomes)
    report["parametric_accepted"] = passed
    report["task_accepted"] = report["geometry_accepted"] and passed
    for scenario in required:
        outcome = next((item for item in outcomes if item["id"] == scenario.id), None)
        status = ("pass" if outcome["geometry_accepted"] else
                  "indeterminate" if outcome["summary"]["indeterminate"] else "fail") if outcome else "indeterminate"
        report["checks"].append(result("AUTO_parametric_" + scenario.id, status,
            "OK" if status == "pass" else "PARAMETRIC_RESPONSE_FAILED", scenario.description,
            {"scenario": scenario.id, "parameters": scenario.parameters,
             "blocker_ids": outcome["blocker_ids"] if outcome else ["SCENARIO_NOT_RUN"],
             "run_directory": outcome["run_directory"] if outcome else None},
            hint=f"Inspect --scenario {scenario.id}; preserve nominal targets and unchanged interfaces."))
    if not complete and outcomes:
        report["checks"].append(result("AUTO_parametric_coverage", "fail", "CHECK_COVERAGE_INVALID",
                                      "Required scenarios must appear exactly once in approved order"))
    report["summary"] = {status: sum(c["status"] == status for c in report["checks"])
                         for status in ("pass", "fail", "indeterminate", "not_applicable")}
    if report["geometry_accepted"]:
        report["status"] = "PARAMETRIC_ACCEPTED" if report["task_accepted"] else "PARAMETRIC_REPAIR_REQUIRED"
    report["scope"] = "nominal_geometry_and_declared_parameter_responses"
    return report
