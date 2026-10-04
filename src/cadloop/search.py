"""Bounded parameter search; no model guesses or changes to requirements."""
from __future__ import annotations
from .errors import CadLoopError
from .util import project_lock
from .parametric import accepted


def search_parameter(project, parameter: str, values: list, *, mode: str,
                     fixed: dict | None = None, timeout=45., max_evaluations=12):
    with project_lock(project.control):
        return _search_locked(project, parameter, values, mode=mode, fixed=fixed,
                              timeout=timeout, max_evaluations=max_evaluations)


def _search_locked(project, parameter, values, *, mode, fixed, timeout, max_evaluations):
    if not isinstance(values, list) or not values or len(values) > min(max_evaluations, 12):
        raise CadLoopError("SEARCH_LIMIT", "Supply between one and twelve candidate values")
    base = project.parameters()
    if parameter not in base:
        raise CadLoopError("PARAMETER_UNKNOWN", "Unknown search parameter")
    fixed = fixed or {}
    if parameter in fixed:
        raise CadLoopError("SEARCH_CONFLICT", "The search parameter cannot also be fixed")
    # Stable deduplication: repeated candidates waste builds but add no evidence.
    candidates = []
    requirements = project.requirements()
    for value in values:
        params = requirements.validate_parameters({**base, **fixed, parameter: value})
        if params not in candidates:
            candidates.append(params)
    records = []
    winner = None
    restored_final = None
    def restore_base(reason):
        changes = {k: v for k, v in base.items() if project.parameters()[k] != v}
        if changes:
            project.propose({"base_revision": project.revision(), "parameters": changes,
                             "reason": reason})
    try:
        for params in candidates:
            changes = {k: v for k, v in params.items() if project.parameters()[k] != v}
            if changes:
                project.propose({"base_revision": project.revision(), "parameters": changes,
                                 "reason": f"Bounded deterministic search: {parameter}={params[parameter]}"})
            report = project.evaluate(mode=mode, timeout=timeout, render=False)
            records.append({"value": params[parameter], "run_id": report["run_id"],
                            "revision": report["revision"], "status": report["status"],
                            "summary": report["summary"], "blocker_ids": report["blocker_ids"]})
            if accepted(report):
                winner = params
                break
        if winner is None:
            restore_base("No feasible candidate; restore the starting design.")
        # Final validation is part of the transaction too: exceptions and
        # interruptions here must restore the original parameters.
        final = project.evaluate(mode=mode, timeout=timeout, force=True, render=True)
        confirmed = winner is not None and accepted(final)
        if winner is not None and not confirmed:
            restore_base("Final candidate validation failed; restore the starting design.")
            restored_final = project.evaluate(mode=mode, timeout=timeout, force=True, render=True)
    except BaseException:
        restore_base("Restore base parameters after interrupted search.")
        raise
    status = ("FEASIBLE_CANDIDATE_FOUND" if confirmed else
              "FINAL_VALIDATION_FAILED" if winner is not None else "NO_FEASIBLE_CANDIDATE")
    project.event("parameter_search", {"parameter": parameter, "attempts": records, "found": confirmed,
                                      "final_status": final["status"]})
    return {"status": status, "parameter": parameter,
            "value": winner[parameter] if confirmed else None,
            "attempts": records, "final": final, "llm_calls": 0,
            **({"restored_final": restored_final} if restored_final is not None else {})}
