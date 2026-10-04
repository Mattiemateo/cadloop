"""Rank useful multiple-choice decisions; design freedom is not ambiguity."""
from __future__ import annotations

import math

from .contracts import DesignContract
from .audit import critical_claim_ids, clearance_limit_known


IMPACT_WEIGHT = {"LOW": .25, "MEDIUM": .50, "HIGH": .75, "CRITICAL": 1.0}
CHANGE_COST_WEIGHT = {"LOW": .40, "MEDIUM": .70, "HIGH": 1.0}


def question_score(candidate) -> float:
    return ((1.0 - candidate.confidence) * IMPACT_WEIGHT[candidate.impact]
            * CHANGE_COST_WEIGHT[candidate.change_cost])


def rank_questions(contract: DesignContract | dict, threshold=.18, limit=3) -> list[dict]:
    """All active questions are auditable; only the first three enter one round."""
    contract = DesignContract.model_validate(contract.model_dump() if isinstance(contract, DesignContract) else contract)
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Question threshold must be finite and between 0 and 1")
    if limit is not None and (type(limit) is not int or not 1 <= limit <= 3):
        raise ValueError("A review round permits one to three questions")
    answered = {decision.question_id for decision in contract.accepted_decisions}
    hard = {requirement.id for requirement in contract.requirements if requirement.hard}
    interfaces = {interface.id: interface for interface in contract.interfaces}
    parameters = {parameter.id: parameter for parameter in contract.parameters}
    components = {component.id for component in contract.components}
    critical = critical_claim_ids(contract)
    unknown_clearances = {constraint.id: set(constraint.parameter_refs)
                          for constraint in contract.constraints
                          if constraint.impact == "CRITICAL" and constraint.kind == "minimum_clearance"
                          and not clearance_limit_known(contract, constraint)}
    unknown_dimensions = {
        ref for interface in contract.interfaces if interface.impact == "CRITICAL"
        for ref in interface.required_parameter_refs
        if not ((parameters[ref].mode == "FIXED" and parameters[ref].value is not None)
                or (parameters[ref].mode == "BOUNDED" and
                    (parameters[ref].minimum is not None or parameters[ref].maximum is not None))
                or (parameters[ref].mode == "DERIVED" and parameters[ref].derived_from))
    }
    ranked = []
    for candidate in contract.decision_candidates:
        if candidate.id in answered:
            continue
        affects = set(candidate.affects)
        reasons = []
        hard_conflict = affects & hard or any(
            set(interface.requirement_refs) & hard for interface in interfaces.values()
            if interface.id in affects or set(interface.parameter_refs) & affects)
        if candidate.source_conflict and hard_conflict:
            reasons.append("SOURCE_CONFLICT_HARD_REQUIREMENT")
        if any(interface.impact == "CRITICAL" and not interface.resolved
               for identifier, interface in interfaces.items() if identifier in affects):
            reasons.append("CRITICAL_INTERFACE_UNKNOWN")
        if any(identifier in critical for identifier in affects):
            reasons.append("CRITICAL_INFERENCE_UNAPPROVED")
        if affects & unknown_dimensions:
            reasons.append("CRITICAL_MATING_DIMENSION_UNKNOWN")
        if any(identifier in affects or refs & affects for identifier, refs in unknown_clearances.items()):
            reasons.append("CRITICAL_CLEARANCE_UNKNOWN")
        if candidate.impact == "CRITICAL" and affects & components:
            reasons.append("CRITICAL_TOPOLOGY_AMBIGUOUS")
        freedom = affects and affects <= parameters.keys() and all(
            parameters[identifier].mode in ("FREE", "OPTIMIZED") for identifier in affects)
        score = question_score(candidate)
        if reasons or (not freedom and score >= threshold):
            ranked.append({**candidate.model_dump(mode="json"), "score": score,
                           "blocking_reasons": sorted(reasons)})
    ranked.sort(key=lambda question: (-bool(question["blocking_reasons"]), -question["score"], question["id"]))
    return ranked if limit is None else ranked[:limit]
