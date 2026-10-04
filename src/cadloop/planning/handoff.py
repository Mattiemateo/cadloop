"""Deterministic modeling handoff and a narrow adapter to existing requirements."""
from __future__ import annotations

from cadloop.contracts import Param, Requirements
from .contracts import DesignContract, ParameterSpec, VerificationIntent
from .diagrams import parameter_label

SECTIONS = (
    "GOAL", "DESIGN INTENT", "COMPONENTS / APPROVED REFERENCES", "COORDINATE FRAMES",
    "FIXED INTERFACES", "HARD REQUIREMENTS", "FIXED DIMENSIONS", "BOUNDED PARAMETERS",
    "DERIVED RELATIONSHIPS", "FREE DESIGN VARIABLES", "OPTIMIZATION OBJECTIVES",
    "MANUFACTURING CONSTRAINTS", "ASSEMBLY / ACCESS REQUIREMENTS", "KEEP-OUTS / MOTION ENVELOPES",
    "PARAMETERS THAT MUST REMAIN EDITABLE", "PROTECTED REQUIREMENTS", "VERIFICATION INTENT",
    "APPROVED ASSUMPTIONS", "PROHIBITED INTERPRETATIONS",
)


def _refs(items: list[str]) -> str:
    return ", ".join(items) or "none supplied"


def compile_handoff(contract: DesignContract) -> str:
    """Compile canonical parameter values once; all other sections refer to IDs."""
    contract = DesignContract.model_validate(contract.model_dump())
    sections = {section: [] for section in SECTIONS}
    sections["GOAL"] = [f"Task `{contract.task_id}`; contract revision `{contract.revision}`."]
    sections["DESIGN INTENT"] = [contract.intent or "No additional design intent supplied."]
    source_by_id = {s.id: s for s in contract.sources}
    for component in contract.components:
        sources = []
        for ref in component.source_refs:
            source = source_by_id[ref]
            sources.append(f"{source.id} ({source.kind})" + (f": {source.reference}" if source.reference else ""))
        sections["COMPONENTS / APPROVED REFERENCES"].append(
            f"`{component.id}`: {component.name}; role: {component.role}; "
            f"fixed geometry: {str(component.fixed_geometry).lower()}; sources: {_refs(sources)}. "
            + " ".join(component.notes))
    for frame in contract.coordinate_frames:
        axes = "; ".join(f"{axis}: {description}" for axis, description in sorted(frame.axis_descriptions.items()))
        sections["COORDINATE FRAMES"].append(
            f"`{frame.id}`: {frame.description}; parent: {frame.parent_ref or 'root'}; "
            f"origin references: {_refs(frame.origin_parameter_refs)}; {axes}.")
    for interface in contract.interfaces:
        sections["FIXED INTERFACES"].append(
            f"`{interface.id}`: {interface.component_a} ↔ {interface.component_b}; {interface.kind}; "
            f"resolved: {str(interface.resolved).lower()}; parameter references: {_refs(interface.parameter_refs)}; "
            f"requirement references: {_refs(interface.requirement_refs)}. " + " ".join(interface.notes))
    for requirement in contract.requirements:
        if requirement.hard:
            sections["HARD REQUIREMENTS"].append(
                f"`{requirement.id}` [{requirement.impact}]: {requirement.text}; sources: {_refs(requirement.source_refs)}.")
            sections["PROTECTED REQUIREMENTS"].append(f"`{requirement.id}` — preserve its required behavior and provenance.")
    modes = {"FIXED": "FIXED DIMENSIONS", "BOUNDED": "BOUNDED PARAMETERS",
             "DERIVED": "DERIVED RELATIONSHIPS", "FREE": "FREE DESIGN VARIABLES",
             "OPTIMIZED": "OPTIMIZATION OBJECTIVES"}
    for parameter in contract.parameters:
        text = parameter_label(parameter)
        if parameter.mode == "BOUNDED" and parameter.value is not None:
            bounds = []
            if parameter.minimum is not None:
                bounds.append(f"minimum={parameter.minimum:g}")
            if parameter.maximum is not None:
                bounds.append(f"maximum={parameter.maximum:g}")
            text += f"; approved bounds ({parameter.unit}): {', '.join(bounds)}"
        if parameter.mode == "DERIVED" and parameter.value is not None:
            text += f"; derived from {_refs(parameter.derived_from)}"
        if parameter.objective:
            text += f"; objective: {parameter.objective}"
        text += f"; sources: {_refs(parameter.source_refs)}; impact: {parameter.impact}"
        sections[modes[parameter.mode]].append(text)
        if parameter.editable:
            sections["PARAMETERS THAT MUST REMAIN EDITABLE"].append(f"`{parameter.id}` ({parameter.mode}); preserve its approved mode/bounds.")
    for objective in contract.optimization_objectives:
        sections["OPTIMIZATION OBJECTIVES"].append(
            f"`{objective.id}`: {objective.direction}: {objective.text}; parameter references: {_refs(objective.parameter_refs)}.")
    manufacturing = contract.manufacturing
    sections["MANUFACTURING CONSTRAINTS"] = [
        f"Processes: {_refs(manufacturing.processes)}; material references: {_refs(manufacturing.material_parameter_refs)}; "
        f"parameter references: {_refs(manufacturing.parameter_refs)}.", *manufacturing.notes]
    sections["ASSEMBLY / ACCESS REQUIREMENTS"] = list(manufacturing.assembly_access)
    for constraint in contract.constraints:
        key = "KEEP-OUTS / MOTION ENVELOPES" if constraint.kind in ("keepout", "inside", "outside") else "DERIVED RELATIONSHIPS"
        sections[key].append(
            f"`{constraint.id}`: {constraint.kind}; components: {_refs(constraint.component_refs)}; "
            f"parameters: {_refs(constraint.parameter_refs)}; interfaces: {_refs(constraint.interface_refs)}. {constraint.text}")
    for intent in contract.verification_intent:
        sections["VERIFICATION INTENT"].append(
            f"`{intent.id}`: {intent.text}; kind: {intent.kind}; geometry required: {str(intent.geometry_required).lower()}; "
            f"components: {_refs(intent.component_refs)}; parameters: {_refs(intent.parameter_refs)}; "
            f"requirements: {_refs(intent.requirement_refs)}.")
    adapted = compile_requirements(contract)
    for unsupported in adapted["unsupported"]:
        sections["VERIFICATION INTENT"].append(
            f"UNSUPPORTED `{unsupported['id']}`: {unsupported['message']}; "
            f"critical geometric requirement: {str(unsupported['critical']).lower()}. Requires explicit downstream review.")
    sections["VERIFICATION INTENT"].append("Planning approval is not geometric acceptance; independently verify exported BREP/STEP after modeling.")
    sections["APPROVED ASSUMPTIONS"] = [f"`{a.id}`: {a.text}; sources: {_refs(a.source_refs)}." for a in contract.assumptions if a.accepted]
    sections["PROHIBITED INTERPRETATIONS"] = [
        *manufacturing.prohibited_interpretations,
        "Never invent a dimension to bypass unresolved critical planning issues.",
        "Do not replace subjective stiffness, safety or manufacturability requirements with invented geometric thresholds.",
        "Do not treat concept sketches, inferred values or a frozen contract as proof of engineering performance.",
    ]
    lines = ["# CADLoop modeling handoff", "", "Canonical values are listed once below; referenced IDs retain the same meaning in every section.", ""]
    for section in SECTIONS:
        lines.extend([f"## {section}", ""])
        lines.extend(f"- {item}" for item in sections[section] or ["None supplied."])
        lines.append("")
    return "\n".join(lines)


def _numeric(parameter: ParameterSpec, *, unit: str = "mm") -> float:
    if parameter.kind not in ("number", "integer") or parameter.unit != unit or parameter.value is None:
        raise ValueError("Referenced geometric target must be an explicit numeric value in the required unit")
    return float(parameter.value)


def _check(intent: VerificationIntent, parameters: dict[str, ParameterSpec]) -> dict:
    check = {"id": intent.id, "description": intent.text}
    if intent.kind == "dimension":
        if len(intent.component_refs) != 1 or len(intent.parameter_refs) != 1 or intent.axis is None:
            raise ValueError("Dimension verification needs one component, one parameter and an explicit axis")
        parameter = parameters[intent.parameter_refs[0]]
        if parameter.kind not in ("number", "integer") or parameter.unit != "mm":
            raise ValueError("Dimension targets require numeric mm parameters")
        if parameter.mode == "FIXED":
            value = _numeric(parameter)
            lo, hi = value - intent.tolerance_mm, value + intent.tolerance_mm
        elif parameter.mode == "BOUNDED" and parameter.minimum is not None and parameter.maximum is not None:
            lo, hi = parameter.minimum, parameter.maximum
        else:
            raise ValueError("Dimension target must be FIXED or have both approved BOUNDED limits")
        return check | {"kind": "dimension", "part": intent.component_refs[0], "axis": intent.axis,
                        "minimum": lo, "maximum": hi}
    if intent.kind == "clearance":
        if len(intent.component_refs) != 2 or len(intent.parameter_refs) != 1:
            raise ValueError("Clearance verification needs two components and one minimum-clearance parameter")
        parameter = parameters[intent.parameter_refs[0]]
        if parameter.kind not in ("number", "integer") or parameter.unit != "mm":
            raise ValueError("Clearance targets require numeric mm parameters")
        if parameter.mode == "FIXED":
            minimum, maximum = _numeric(parameter), None
        elif parameter.mode == "BOUNDED" and parameter.minimum is not None:
            minimum, maximum = parameter.minimum, parameter.maximum
        else:
            raise ValueError("Clearance target needs an explicit approved minimum")
        if minimum < 0:
            raise ValueError("Clearance cannot be negative")
        return check | {"kind": "clearance", "a": intent.component_refs[0], "b": intent.component_refs[1],
                        "minimum": minimum, "maximum": maximum}
    if intent.kind == "through_holes_z":
        if len(intent.component_refs) != 1 or not intent.hole_refs or intent.tolerance_mm > 0.1:
            raise ValueError("Analytic Z holes need one component, explicit centers/radii and tolerance <= 0.1 mm")
        holes = []
        for hole in intent.hole_refs:
            refs = [parameters[ref] for ref in (hole.x_parameter, hole.y_parameter, hole.radius_parameter)]
            if any(p.mode != "FIXED" for p in refs):
                raise ValueError("Analytic hole targets must be FIXED; derived feature resolution is not implemented")
            x, y, radius = map(_numeric, refs)
            if radius <= 0:
                raise ValueError("Hole radius must be positive")
            holes.append({"x": x, "y": y, "radius": radius})
        return check | {"kind": "through_holes_z", "part": intent.component_refs[0], "holes": holes,
                        "tolerance": intent.tolerance_mm}
    raise ValueError("Manual or subjective verification cannot be compiled into a geometric check")


def compile_requirements(contract: DesignContract) -> dict:
    """Translate only explicit supported semantics; leave all other intent visible."""
    contract = DesignContract.model_validate(contract.model_dump())
    parameters = {p.id: p for p in contract.parameters}
    requirements = {r.id: r for r in contract.requirements}
    unsupported = []
    checks = []
    translated_requirements = set()
    for intent in contract.verification_intent:
        try:
            check = _check(intent, parameters)
        except ValueError as exc:
            unsupported.append({"code": "PLANNING_VERIFICATION_UNSUPPORTED", "id": intent.id,
                                "message": str(exc), "critical": intent.geometry_required})
        else:
            checks.append(check)
            translated_requirements.update(intent.requirement_refs)
    # Hard statements without a verification intent stay protected text, never fake checks.
    for requirement in contract.requirements:
        if requirement.id not in translated_requirements:
            unsupported.append({"code": "PLANNING_REQUIREMENT_HANDOFF_ONLY", "id": requirement.id,
                                "message": "Requirement has no fully translated geometric verification intent",
                                "critical": any(intent.geometry_required
                                                for intent in contract.verification_intent if requirement.id in intent.requirement_refs)})
    adapted_parameters = {}
    for parameter in contract.parameters:
        if parameter.kind == "boolean":
            if parameter.mode == "FREE":
                adapted_parameters[parameter.id] = Param(kind="boolean", unit="boolean", description=parameter.name).model_dump()
            elif parameter.mode == "FIXED":
                unsupported.append({"code": "PLANNING_PARAMETER_UNSUPPORTED", "id": parameter.id,
                                    "message": "Existing boolean parameters cannot enforce a fixed truth value; retain this value in the handoff and author an independent enforcement check",
                                    "critical": parameter.impact == "CRITICAL" or any(
                                        intent.geometry_required and parameter.id in intent.parameter_refs
                                        and any(requirements[ref].hard and requirements[ref].impact == "CRITICAL"
                                                for ref in intent.requirement_refs)
                                        for intent in contract.verification_intent)})
        elif parameter.kind in ("number", "integer") and parameter.mode in ("FIXED", "BOUNDED"):
            lo, hi = parameter.minimum, parameter.maximum
            if parameter.mode == "FIXED" and parameter.value is not None:
                lo = hi = parameter.value
            if lo is not None and hi is not None:
                adapted_parameters[parameter.id] = Param(kind=parameter.kind, unit=parameter.unit,
                                                         minimum=lo, maximum=hi, description=parameter.name).model_dump()
            elif parameter.mode == "BOUNDED":
                # Existing Requirements require two finite bounds. Never erase
                # the supplied side or invent the missing one: until a reviewed
                # revision supplies it, import cannot enforce this parameter.
                unsupported.append({"code": "PLANNING_PARAMETER_UNSUPPORTED", "id": parameter.id,
                                    "message": "Existing numeric parameters require both bounds; preserve the approved one-sided limit and obtain a reviewed opposite bound before materialization",
                                    "critical": True})
    if not checks:
        return {"requirements": None, "unsupported": unsupported}
    data = {
        "name": contract.task_id, "description": contract.intent or contract.brief,
        "expected_parts": [c.id for c in contract.components], "parameters": adapted_parameters,
        "checks": checks, "engineering_blockers": [
            "Frozen planning intent is not engineering approval; verify material, manufacture, strength and assembly independently.",
            *[f"{item['code']} {item['id']}: {item['message']}" for item in unsupported],
        ],
    }
    return {"requirements": Requirements.model_validate(data).model_dump(), "unsupported": unsupported}
