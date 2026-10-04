"""Deterministic acceptance checks for engineering intent, not CAD geometry."""
from __future__ import annotations

import re

from pydantic import ValidationError

from .contracts import DesignContract


TRUSTED_PROVENANCE = {"USER", "ATTACHMENT_MEASURED", "APPROVED_REFERENCE"}


def approved_sources(contract: DesignContract) -> set[str]:
    """Approval is controller-owned; an agent proposal cannot add decisions."""
    approved = {s.id for s in contract.sources if s.kind in TRUSTED_PROVENANCE}
    for decision in contract.accepted_decisions:
        approved.update(decision.source_refs)
    accepted_assumptions = {
        update.path.split("/")[2]
        for decision in contract.accepted_decisions for update in decision.updates
        if update.path.startswith("/assumptions/") and update.path.endswith("/accepted")
        and update.value is True
    }
    for assumption in contract.assumptions:
        if assumption.accepted and assumption.id in accepted_assumptions:
            approved.update(assumption.source_refs)
    return approved


def parameter_approved(contract: DesignContract, parameter, approved: set[str], visited=None) -> bool:
    if set(parameter.source_refs) & approved:
        return True
    updates = {update.path: update.value for decision in contract.accepted_decisions for update in decision.updates}
    prefix = f"/parameters/{parameter.id}/"
    if parameter.mode == "BOUNDED":
        bounds = {field: getattr(parameter, field) for field in ("minimum", "maximum")
                  if getattr(parameter, field) is not None}
        return bool(bounds) and all(prefix + field in updates and updates[prefix + field] == value
                                    for field, value in bounds.items())
    if parameter.value is not None and prefix + "value" in updates and updates[prefix + "value"] == parameter.value:
        return True
    if parameter.mode == "DERIVED" and parameter.derived_from:
        visited = set() if visited is None else visited
        if parameter.id in visited:
            return False
        by_id = {item.id: item for item in contract.parameters}
        return all(parameter_approved(contract, by_id[ref], approved, visited | {parameter.id})
                   for ref in parameter.derived_from)
    return False


def critical_claim_ids(contract: DesignContract) -> set[str]:
    """Facts that require source evidence or an explicit user decision."""
    approved = approved_sources(contract)
    required = {parameter for interface in contract.interfaces if interface.impact == "CRITICAL"
                for parameter in interface.required_parameter_refs}
    required.update(parameter for constraint in contract.constraints if constraint.impact == "CRITICAL"
                    for parameter in constraint.parameter_refs)
    claims = {
        parameter.id for parameter in contract.parameters
        if (parameter.impact == "CRITICAL" or parameter.id in required)
        and parameter.mode not in ("FREE", "OPTIMIZED")
        and not parameter_approved(contract, parameter, approved)
    }
    claims.update(requirement.id for requirement in contract.requirements
                  if requirement.hard and requirement.impact == "CRITICAL"
                  and not set(requirement.source_refs) & approved)
    claims.update(interface.id for interface in contract.interfaces
                  if interface.impact == "CRITICAL" and not set(interface.source_refs) & approved
                  and not any(update.path == f"/interfaces/{interface.id}/resolved" and update.value is True
                              for decision in contract.accepted_decisions for update in decision.updates))
    claims.update(constraint.id for constraint in contract.constraints
                  if constraint.impact == "CRITICAL" and not set(constraint.source_refs) & approved)
    claims.update(assumption.id for assumption in contract.assumptions
                  if assumption.impact == "CRITICAL" and not assumption.accepted)
    return claims


def clearance_limit_known(contract: DesignContract, constraint) -> bool:
    parameters = {p.id: p for p in contract.parameters}
    return any(
        p.kind in ("number", "integer") and p.unit == "mm" and
        ((p.mode == "FIXED" and p.value is not None and p.value >= 0)
         or (p.mode == "BOUNDED" and p.minimum is not None and p.minimum >= 0)
         or (p.mode == "DERIVED" and p.derived_from))
        for p in (parameters[ref] for ref in constraint.parameter_refs))


def _history_contracts(history) -> dict[str, dict]:
    if history is None:
        return {}
    if isinstance(history, dict):
        return {revision: item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for revision, item in history.items()}
    return {item.revision if hasattr(item, "revision") else item["revision"]:
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in history}


def audit(contract: DesignContract | dict, accepted_history=None) -> dict:
    """Return freeze blockers without evaluating arbitrary source or geometry."""
    try:
        contract = DesignContract.model_validate(contract.model_dump() if isinstance(contract, DesignContract) else contract)
    except ValidationError as exc:
        return {"status": "REVIEW_REQUIRED", "blocking": [{
            "code": "PLANNING_SCHEMA_INVALID", "id": "contract", "message": str(exc)
        }], "warnings": []}
    blocking, warnings = [], []

    def issue(code, identifier, message, *, needs_input=False, **evidence):
        blocking.append({"code": code, "id": identifier, "message": message,
                         "needs_input": needs_input, **evidence})

    if not contract.intent.strip():
        issue("DESIGN_INTENT_MISSING", "intent", "Describe the intended design.")
    if not contract.components:
        issue("COMPONENTS_MISSING", "components", "Define the components before review.")
    for absent, code, identifier, message in (
        (not contract.requirements, "REQUIREMENTS_MISSING", "requirements", "No engineering requirements have been declared."),
        (not contract.verification_intent, "VERIFICATION_INTENT_MISSING", "verification_intent", "No verification intent has been declared."),
        (not contract.manufacturing.processes, "MANUFACTURING_PROCESS_UNSPECIFIED", "manufacturing", "Manufacturing process remains unspecified."),
    ):
        if absent:
            warnings.append({"code": code, "id": identifier, "message": message})
    from .diagrams import diagram_views
    views, diagram_issues = diagram_views(contract)
    blocking.extend(diagram_issues)
    if any(not view for view in views.values()):
        issue("DIAGRAM_VIEWS_MISSING", "diagram_spec", "Provide front, side and top concept views.")
    for primitive in contract.diagram_spec.all_primitives():
        if (primitive.text and (primitive.type == "dimension" or
                re.search(r"(?<![\w.])[-+]?\d+(?:\.\d+)?\s*(?:mm|deg|count|in)\b|\d\s*°", primitive.text))
                and primitive.parameter_ref is None):
            issue("DIAGRAM_LITERAL_ENGINEERING_VALUE", primitive.id,
                  "Engineering diagram values must reference canonical parameters.")
        if primitive.type == "dimension" and primitive.text:
            issue("DIAGRAM_DIMENSION_TEXT_OVERRIDE", primitive.id,
                  "Dimension labels are generated from canonical parameter references.")

    approved = approved_sources(contract)
    critical = critical_claim_ids(contract)
    for requirement in contract.requirements:
        if requirement.hard and not requirement.source_refs:
            issue("HARD_REQUIREMENT_PROVENANCE_MISSING", requirement.id,
                  "Hard requirements need source provenance.", needs_input=True)
        elif requirement.id in critical:
            issue("CRITICAL_INFERENCE_UNAPPROVED", requirement.id,
                  "Explicitly approve the source of this critical requirement.", needs_input=True)
    parameters = {p.id: p for p in contract.parameters}
    for parameter in contract.parameters:
        if parameter.mode == "FIXED" and parameter.value is None:
            issue("FIXED_PARAMETER_UNKNOWN", parameter.id,
                  "A fixed parameter requires an explicit value.",
                  needs_input=parameter.impact in ("HIGH", "CRITICAL"))
        if parameter.id in critical:
            issue("CRITICAL_INFERENCE_UNAPPROVED", parameter.id,
                  "Explicitly approve the source or value of this critical dimension.", needs_input=True)
        elif parameter.source_refs and not parameter_approved(contract, parameter, approved):
            warnings.append({"code": "UNAPPROVED_NONCRITICAL_VALUE", "id": parameter.id,
                             "message": "This noncritical design choice remains inferred or defaulted."})
    for interface in contract.interfaces:
        if interface.impact != "CRITICAL":
            continue
        if not interface.resolved:
            issue("CRITICAL_INTERFACE_UNKNOWN", interface.id,
                  "Resolve the critical component interface.", needs_input=True)
        if interface.id in critical:
            issue("CRITICAL_INFERENCE_UNAPPROVED", interface.id,
                  "Approve the source or selected relationship of this critical interface.", needs_input=True)
        for ref in interface.required_parameter_refs:
            parameter = parameters[ref]
            known = ((parameter.mode == "FIXED" and parameter.value is not None)
                     or (parameter.mode == "BOUNDED" and
                         (parameter.minimum is not None or parameter.maximum is not None))
                     or (parameter.mode == "DERIVED" and bool(parameter.derived_from)))
            if not known:
                issue("CRITICAL_MATING_DIMENSION_UNKNOWN", parameter.id,
                      "A required mating dimension must be fixed, bounded or derived.",
                      needs_input=True, interface_id=interface.id)
        if interface.kind in ("mating", "bolt_pattern", "bearing_bore", "shaft_axis", "mounting_face", "clearance_envelope", "clamp") and not interface.parameter_refs:
            issue("CRITICAL_INTERFACE_DIMENSIONS_MISSING", interface.id,
                  "Reference the parameters defining this interface.", needs_input=True)
    for assumption in contract.assumptions:
        if assumption.impact == "CRITICAL" and not assumption.accepted:
            issue("CRITICAL_ASSUMPTION_UNAPPROVED", assumption.id,
                  "Approve or replace this critical assumption.", needs_input=True)
    for constraint in contract.constraints:
        if constraint.impact != "CRITICAL":
            continue
        if constraint.id in critical:
            issue("CRITICAL_INFERENCE_UNAPPROVED", constraint.id,
                  "Approve the source defining this critical relationship.", needs_input=True)
        components = set(constraint.component_refs)
        for ref in constraint.interface_refs:
            interface = next(item for item in contract.interfaces if item.id == ref)
            components.update((interface.component_a, interface.component_b))
        expected = 1 if constraint.kind == "keepout" else 2
        if len(components) < expected:
            issue("CRITICAL_RELATIONSHIP_UNDEFINED", constraint.id,
                  "Identify the components participating in this critical relationship.", needs_input=True)
        if constraint.kind == "minimum_clearance":
            if not clearance_limit_known(contract, constraint):
                issue("CRITICAL_CLEARANCE_UNKNOWN", constraint.id,
                      "Reference a fixed, derived or minimum-bounded clearance in mm.", needs_input=True)
    for candidate in contract.decision_candidates:
        if candidate.source_conflict and candidate.id not in {d.question_id for d in contract.accepted_decisions}:
            warnings.append({"code": "UNRESOLVED_SOURCE_CONFLICT", "id": candidate.id,
                             "message": "This source conflict remains explicitly unresolved until answered."})

    histories = _history_contracts(accepted_history)
    current = contract.model_dump(mode="json")
    for decision in contract.accepted_decisions:
        past = histories.get(decision.previous_revision)
        choices = [past] if past else [current] if accepted_history is None else []
        candidates = [candidate for past in choices
                      for candidate in past.get("decision_candidates", [])
                      if candidate["id"] == decision.question_id]
        options = [option for candidate in candidates for option in candidate["options"]
                   if option["id"] == decision.option_id]
        expected = [update.model_dump(mode="json") for update in decision.updates]
        if not any(option["updates"] == expected and option.get("approved_source_refs", []) == decision.source_refs
                   for option in options):
            issue("ACCEPTED_DECISION_HISTORY_INVALID", decision.id,
                  "The accepted option does not match its planning history.")
    # A later explicit decision may supersede an earlier value; the final write
    # to each stable path must still match the current canonical contract.
    updates = {update.path: update for decision in contract.accepted_decisions
               for update in decision.updates}
    for path, update in updates.items():
        _, collection, identifier, field = path.split("/")
        objects = current[collection]
        obj = next((item for item in objects if item["id"] == identifier), None)
        if obj is None or obj.get(field) != update.value:
            issue("ACCEPTED_DECISION_CHANGED", identifier,
                  "An accepted decision was changed without a new user decision.", path=path)

    from .questions import rank_questions
    for question in rank_questions(contract, limit=None):
        issue("UNANSWERED_DECISION", question["id"], question["question"],
              needs_input=True, score=question["score"],
              blocking_reasons=question["blocking_reasons"])

    # Critical verification intent remains explicit when no geometric adapter
    # exists. A planning freeze cannot imply an unsupported verifier passed.
    for intent in contract.verification_intent:
        item = intent.model_dump(mode="json")
        if (item.get("geometry_required", False) and item.get("kind") == "manual"
                and set(item.get("requirement_refs", [])) & {r.id for r in contract.requirements if r.impact == "CRITICAL"}):
            warnings.append({"code": "CRITICAL_VERIFICATION_UNSUPPORTED", "id": intent.id,
                             "message": "The modeling handoff must retain this unsupported geometric verification requirement."})
    blocking.sort(key=lambda item: (item["code"], item["id"]))
    warnings.sort(key=lambda item: (item["code"], item["id"]))
    status = ("NEEDS_INPUT" if any(item["needs_input"] for item in blocking)
              else "REVIEW_REQUIRED" if blocking else "REVIEWABLE")
    if not blocking and contract.status == "FROZEN":
        status = "FROZEN"
    return {"status": status, "blocking": blocking, "warnings": warnings}
