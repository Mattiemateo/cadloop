"""Closed planning contracts and ID-addressed, deterministic decision updates."""
from __future__ import annotations

from graphlib import CycleError, TopologicalSorter
import re
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator, model_validator

from cadloop.contracts import NAME, Strict

Identifier = Annotated[str, Field(pattern=NAME)]
Scalar = StrictFloat | StrictInt | StrictBool | StrictStr | None
Impact = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
ChangeCost = Literal["LOW", "MEDIUM", "HIGH"]
ParameterMode = Literal["FIXED", "BOUNDED", "DERIVED", "FREE", "OPTIMIZED"]
PlanningStatus = Literal["DRAFT", "REVIEW_REQUIRED", "NEEDS_INPUT", "REVIEWABLE", "FROZEN"]
Provenance = Literal["USER", "ATTACHMENT_MEASURED", "APPROVED_REFERENCE", "EXTERNAL_REFERENCE", "MODEL_INFERRED", "DEFAULT"]
ViewName = Literal["front", "side", "top"]
Confidence = Annotated[StrictFloat, Field(ge=0, le=1)]
Coordinate = Annotated[StrictFloat, Field(ge=0, le=1000)]


class SourceSpec(Strict):
    id: Identifier
    kind: Provenance
    description: str = Field(min_length=1, max_length=16000)
    reference: str | None = None


class ComponentSpec(Strict):
    id: Identifier
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    source_refs: list[Identifier] = Field(default_factory=list)
    fixed_geometry: StrictBool = False
    notes: list[str] = Field(default_factory=list)


class ParameterSpec(Strict):
    id: Identifier
    name: str = Field(min_length=1)
    kind: Literal["number", "integer", "boolean", "enum", "string"]
    mode: ParameterMode
    value: Scalar = None
    unit: Literal["mm", "deg", "count", "boolean", "text"]
    minimum: StrictFloat | None = None
    maximum: StrictFloat | None = None
    enum_values: list[Scalar] = Field(default_factory=list)
    derived_from: list[Identifier] = Field(default_factory=list)
    objective: str | None = None
    source_refs: list[Identifier] = Field(default_factory=list)
    confidence: Confidence = 1.0
    impact: Impact = "MEDIUM"
    editable: StrictBool = True

    @model_validator(mode="after")
    def typed_value(self):
        numeric = self.kind in ("number", "integer")
        if numeric:
            if self.unit not in ("mm", "deg", "count"):
                raise ValueError("Numeric planning parameters use existing mm, deg or count units")
            if self.value is not None and (type(self.value) not in (int, float) or
                    self.kind == "integer" and int(self.value) != self.value):
                raise ValueError("Expected a numeric value compatible with parameter kind")
        elif self.kind == "boolean":
            if self.unit != "boolean" or self.value is not None and type(self.value) is not bool:
                raise ValueError("Boolean parameters require boolean units and values")
        elif self.unit != "text" or self.value is not None and type(self.value) is not str:
            raise ValueError("Enum and string parameters require text units and values")
        if not numeric and (self.minimum is not None or self.maximum is not None):
            raise ValueError("Only numeric parameters have numeric bounds")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Inverted parameter bounds")
        if self.value is not None and numeric:
            if self.minimum is not None and self.value < self.minimum or self.maximum is not None and self.value > self.maximum:
                raise ValueError("Parameter value outside approved bounds")
        if self.kind == "enum":
            if not self.enum_values or any(type(v) is not str for v in self.enum_values):
                raise ValueError("Enum parameters need string choices")
            if len(self.enum_values) != len(set(self.enum_values)):
                raise ValueError("Duplicate enum choices")
            if self.value is not None and self.value not in self.enum_values:
                raise ValueError("Value is not an enum choice")
        elif self.enum_values:
            raise ValueError("Only enum parameters contain enum choices")
        if self.mode == "BOUNDED" and not numeric:
            raise ValueError("BOUNDED parameters require numeric bounds")
        if self.mode == "BOUNDED" and self.minimum is None and self.maximum is None:
            raise ValueError("BOUNDED parameters require at least one bound")
        if self.mode == "DERIVED" and not self.derived_from:
            raise ValueError("DERIVED parameters require parameter references")
        if self.mode == "OPTIMIZED" and not self.objective:
            raise ValueError("OPTIMIZED parameters require an objective")
        return self


class RequirementSpec(Strict):
    id: Identifier
    text: str = Field(min_length=1)
    hard: StrictBool = True
    impact: Impact = "MEDIUM"
    source_refs: list[Identifier] = Field(default_factory=list)


class InterfaceSpec(Strict):
    id: Identifier
    component_a: Identifier
    component_b: Identifier
    kind: Literal["mating", "bolt_pattern", "bearing_bore", "shaft_axis", "mounting_face", "clearance_envelope", "alignment", "clamp", "other"]
    parameter_refs: list[Identifier] = Field(default_factory=list)
    required_parameter_refs: list[Identifier] = Field(default_factory=list)
    requirement_refs: list[Identifier] = Field(default_factory=list)
    impact: Impact = "MEDIUM"
    source_refs: list[Identifier] = Field(default_factory=list)
    resolved: StrictBool = False
    notes: list[str] = Field(default_factory=list)


class ConstraintSpec(Strict):
    id: Identifier
    kind: Literal["coincident", "concentric", "parallel", "perpendicular", "minimum_clearance", "inside", "outside", "symmetry", "keepout"]
    component_refs: list[Identifier] = Field(default_factory=list)
    parameter_refs: list[Identifier] = Field(default_factory=list)
    interface_refs: list[Identifier] = Field(default_factory=list)
    requirement_refs: list[Identifier] = Field(default_factory=list)
    source_refs: list[Identifier] = Field(default_factory=list)
    impact: Impact = "MEDIUM"
    text: str = ""


class ManufacturingSpec(Strict):
    processes: list[Literal["3d_print", "laser_cut", "machining", "other"]] = Field(default_factory=list)
    material_parameter_refs: list[Identifier] = Field(default_factory=list)
    parameter_refs: list[Identifier] = Field(default_factory=list)
    source_refs: list[Identifier] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    assembly_access: list[str] = Field(default_factory=list)
    prohibited_interpretations: list[str] = Field(default_factory=list)


class OptimizationObjective(Strict):
    id: Identifier
    text: str = Field(min_length=1)
    parameter_refs: list[Identifier] = Field(default_factory=list)
    direction: Literal["minimize", "maximize", "prefer"] = "minimize"
    source_refs: list[Identifier] = Field(default_factory=list)


class AssumptionSpec(Strict):
    id: Identifier
    text: str = Field(min_length=1)
    impact: Impact = "MEDIUM"
    source_refs: list[Identifier] = Field(default_factory=list)
    accepted: StrictBool = False


class SetUpdate(Strict):
    op: Literal["set"] = "set"
    path: str = Field(min_length=1)
    value: Scalar

    @field_validator("path")
    @classmethod
    def safe_path(cls, path):
        _path_parts(path)
        return path


class DecisionOption(Strict):
    id: Identifier
    label: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=600)
    recommended: StrictBool = False
    approved_source_refs: list[Identifier] = Field(default_factory=list)
    updates: list[SetUpdate] = Field(max_length=32)

    @model_validator(mode="after")
    def meaningful_choice(self):
        if not self.updates and not self.approved_source_refs:
            raise ValueError("A decision option must update intent or explicitly approve source evidence")
        return self


class DecisionCandidate(Strict):
    id: Identifier
    question: str = Field(min_length=1, max_length=600)
    confidence: Confidence
    impact: Impact
    change_cost: ChangeCost
    affects: list[Identifier] = Field(min_length=1)
    source_conflict: StrictBool = False
    options: list[DecisionOption] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def unique_options(self):
        if len({o.id for o in self.options}) != len(self.options):
            raise ValueError("Duplicate decision option IDs")
        recommended = sum(o.recommended for o in self.options)
        if recommended > 1 or not self.source_conflict and recommended != 1:
            raise ValueError("Exactly one recommendation is required except for source conflicts")
        return self


class AcceptedDecision(Strict):
    id: Identifier
    question_id: Identifier
    option_id: Identifier
    updates: list[SetUpdate]
    source_refs: list[Identifier] = Field(default_factory=list)
    previous_revision: str = Field(min_length=1)
    timestamp: str = Field(min_length=1)


class CoordinateFrame(Strict):
    id: Identifier
    description: str = Field(min_length=1)
    parent_ref: Identifier | None = None
    origin_parameter_refs: list[Identifier] = Field(default_factory=list)
    axis_descriptions: dict[Literal["x", "y", "z"], str] = Field(default_factory=dict)
    source_refs: list[Identifier] = Field(default_factory=list)


class HoleParameterRefs(Strict):
    x_parameter: Identifier
    y_parameter: Identifier
    radius_parameter: Identifier


class VerificationIntent(Strict):
    id: Identifier
    text: str = Field(min_length=1)
    requirement_refs: list[Identifier] = Field(default_factory=list)
    parameter_refs: list[Identifier] = Field(default_factory=list)
    component_refs: list[Identifier] = Field(default_factory=list)
    geometry_required: StrictBool = False
    kind: Literal["dimension", "clearance", "through_holes_z", "manual"] = "manual"
    axis: Literal["x", "y", "z"] | None = None
    tolerance_mm: StrictFloat = Field(default=0.01, gt=0, le=1)
    hole_refs: list[HoleParameterRefs] = Field(default_factory=list)


class DiagramPrimitive(Strict):
    id: Identifier
    type: Literal["rectangle", "circle", "line", "axis", "arrow", "dimension", "label", "keepout", "motion_arc", "component_envelope"]
    x: Coordinate = 0.0
    y: Coordinate = 0.0
    x2: Coordinate | None = None
    y2: Coordinate | None = None
    width: Coordinate | None = None
    height: Coordinate | None = None
    radius: Coordinate | None = None
    start_angle_deg: StrictFloat = Field(default=0.0, ge=-360, le=360)
    end_angle_deg: StrictFloat = Field(default=90.0, ge=-360, le=360)
    text: str | None = None
    parameter_ref: Identifier | None = None
    component_ref: Identifier | None = None
    requirement_ref: Identifier | None = None

    @model_validator(mode="after")
    def primitive_fields(self):
        if self.type in ("rectangle", "component_envelope", "keepout") and (not self.width or not self.height):
            raise ValueError("Rectangular primitives need positive layout width and height")
        if self.type in ("circle", "motion_arc") and not self.radius:
            raise ValueError("Circular primitives need a positive layout radius")
        if self.type == "motion_arc" and abs(self.end_angle_deg - self.start_angle_deg) > 360:
            raise ValueError("A motion arc spans at most one turn")
        if self.type in ("line", "axis", "arrow", "dimension") and (self.x2 is None or self.y2 is None):
            raise ValueError("Line primitives need an explicit endpoint")
        if self.type == "dimension" and self.parameter_ref is None:
            raise ValueError("Engineering dimensions require a canonical parameter reference")
        if self.type == "label" and not any((self.text, self.parameter_ref, self.component_ref, self.requirement_ref)):
            raise ValueError("A label needs annotation text or a contract reference")
        return self


class DiagramSpec(Strict):
    layout_units: Literal["normalized"] = "normalized"
    views: dict[ViewName, list[DiagramPrimitive]] = Field(default_factory=dict)


MUTABLE_FIELDS = {
    "parameters": {"value", "minimum", "maximum", "mode", "objective", "confidence", "editable"},
    "interfaces": {"resolved"},
    "assumptions": {"accepted"},
}


def _path_parts(path):
    pieces = path.split("/")
    if (len(pieces) != 4 or pieces[0] or pieces[1] not in MUTABLE_FIELDS or
            pieces[3] not in MUTABLE_FIELDS[pieces[1]] or not re.fullmatch(NAME, pieces[2])):
        raise ValueError("Unsafe planning update path")
    return pieces[1:]


def update_target(contract: "DesignContract", path: str):
    """Resolve an allowlisted field by stable ID; JSON pointer indexing is forbidden."""
    collection, identifier, field = _path_parts(path)
    item = next((item for item in getattr(contract, collection) if item.id == identifier), None)
    if item is None:
        raise ValueError("Planning update target is unknown")
    return collection, item, field


class DesignContract(Strict):
    schema_version: Literal[1] = 1
    task_id: Identifier
    revision: str = Field(min_length=1)
    brief: str = Field(min_length=1)
    intent: str = ""
    sources: list[SourceSpec] = Field(default_factory=list)
    components: list[ComponentSpec] = Field(default_factory=list)
    interfaces: list[InterfaceSpec] = Field(default_factory=list)
    parameters: list[ParameterSpec] = Field(default_factory=list)
    requirements: list[RequirementSpec] = Field(default_factory=list)
    constraints: list[ConstraintSpec] = Field(default_factory=list)
    manufacturing: ManufacturingSpec = Field(default_factory=ManufacturingSpec)
    optimization_objectives: list[OptimizationObjective] = Field(default_factory=list)
    assumptions: list[AssumptionSpec] = Field(default_factory=list)
    decision_candidates: list[DecisionCandidate] = Field(default_factory=list)
    accepted_decisions: list[AcceptedDecision] = Field(default_factory=list)
    coordinate_frames: list[CoordinateFrame] = Field(default_factory=list)
    diagram_spec: DiagramSpec = Field(default_factory=DiagramSpec)
    verification_intent: list[VerificationIntent] = Field(default_factory=list)
    status: PlanningStatus = "DRAFT"

    @model_validator(mode="after")
    def identities_and_references(self):
        collections = ("sources", "components", "interfaces", "parameters", "requirements", "constraints",
                       "optimization_objectives", "assumptions", "decision_candidates", "accepted_decisions",
                       "coordinate_frames", "verification_intent")
        known = {name: {item.id for item in getattr(self, name)} for name in collections}
        all_ids = [item.id for name in collections for item in getattr(self, name)]
        all_ids.extend(p.id for view in self.diagram_spec.views.values() for p in view)
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("Planning IDs must be globally unique")

        def refs(values, category, description):
            if len(values) != len(set(values)) or not set(values) <= known[category]:
                raise ValueError(f"Duplicate or unresolved {description}")

        for name in collections:
            for item in getattr(self, name):
                if hasattr(item, "source_refs"):
                    refs(item.source_refs, "sources", f"source references on {item.id}")
                for field, category in (("parameter_refs", "parameters"), ("requirement_refs", "requirements"),
                                        ("component_refs", "components"), ("interface_refs", "interfaces")):
                    if hasattr(item, field):
                        refs(getattr(item, field), category, f"{field} on {item.id}")
        for parameter in self.parameters:
            refs(parameter.derived_from, "parameters", f"derived references on {parameter.id}")
            if parameter.id in parameter.derived_from:
                raise ValueError("A parameter cannot derive from itself")
        def no_cycles(edges, description):
            try:
                tuple(TopologicalSorter(edges).static_order())
            except CycleError as exc:
                raise ValueError(f"Cyclic {description}") from exc

        no_cycles({p.id: p.derived_from for p in self.parameters}, "parameter derivation")
        for interface in self.interfaces:
            if interface.component_a not in known["components"] or interface.component_b not in known["components"] or interface.component_a == interface.component_b:
                raise ValueError("Interfaces need two distinct known components")
            refs(interface.required_parameter_refs, "parameters", f"required mating dimensions on {interface.id}")
            if not set(interface.required_parameter_refs) <= set(interface.parameter_refs):
                raise ValueError("Required mating dimensions must belong to the interface")
        refs(self.manufacturing.source_refs, "sources", "manufacturing source references")
        refs(self.manufacturing.parameter_refs, "parameters", "manufacturing parameter references")
        refs(self.manufacturing.material_parameter_refs, "parameters", "material parameter references")
        for frame in self.coordinate_frames:
            refs(frame.origin_parameter_refs, "parameters", f"frame origin on {frame.id}")
            if frame.parent_ref is not None and (frame.parent_ref not in known["coordinate_frames"] or frame.parent_ref == frame.id):
                raise ValueError("Unknown or self-referential coordinate frame parent")
        no_cycles({f.id: [f.parent_ref] if f.parent_ref else [] for f in self.coordinate_frames}, "coordinate frame parent")
        for intent in self.verification_intent:
            for hole in intent.hole_refs:
                for parameter in (hole.x_parameter, hole.y_parameter, hole.radius_parameter):
                    refs([parameter], "parameters", f"verification hole on {intent.id}")
        for view in self.diagram_spec.views.values():
            for primitive in view:
                for field, category in (("parameter_ref", "parameters"), ("component_ref", "components"), ("requirement_ref", "requirements")):
                    value = getattr(primitive, field)
                    if value is not None and value not in known[category]:
                        raise ValueError(f"Unresolved diagram {field}")
        for candidate in self.decision_candidates:
            if len(candidate.affects) != len(set(candidate.affects)) or not set(candidate.affects) <= set(all_ids):
                raise ValueError("Duplicate or unresolved decision affects")
            for option in candidate.options:
                refs(option.approved_source_refs, "sources", f"approved sources on option {option.id}")
                paths = [update.path for update in option.updates]
                if len(paths) != len(set(paths)):
                    raise ValueError("Duplicate update paths within a decision option")
                changed_targets = {}
                for update in option.updates:
                    _, target, field = update_target(self, update.path)
                    if target.id not in candidate.affects:
                        raise ValueError("Decision updates must target a declared affected item")
                    changed = changed_targets.setdefault(target.id, (target, target.model_dump()))[1]
                    changed[field] = update.value
                for target, changed in changed_targets.values():
                    type(target).model_validate(changed)
        if len({d.question_id for d in self.accepted_decisions}) != len(self.accepted_decisions):
            raise ValueError("A planning question cannot have multiple accepted answers")
        for decision in self.accepted_decisions:
            paths = [update.path for update in decision.updates]
            if len(paths) != len(set(paths)):
                raise ValueError("Duplicate accepted decision update paths")
            for update in decision.updates:
                update_target(self, update.path)
        # Accepted question/option references are historical; audit checks their immutable revisions.
        return self


class PlanningProposal(Strict):
    schema_version: Literal[1] = 1
    base_revision: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=4000)
    contract: DesignContract
    decision_candidates: list[DecisionCandidate] | None = None
    diagram_spec: DiagramSpec | None = None

    @model_validator(mode="after")
    def coherent_packet(self):
        if self.contract.revision != self.base_revision:
            raise ValueError("Contract revision must match proposal base revision")
        if self.decision_candidates is not None and self.decision_candidates != self.contract.decision_candidates:
            raise ValueError("Proposal decision candidates disagree with the contract")
        if self.diagram_spec is not None and self.diagram_spec != self.contract.diagram_spec:
            raise ValueError("Proposal diagram specification disagrees with the contract")
        return self


def apply_updates(contract: DesignContract, updates: list[SetUpdate]) -> DesignContract:
    """Apply one transaction without mutating the input, then fully validate it."""
    data = contract.model_dump()
    paths = [update.path for update in updates]
    if len(paths) != len(set(paths)):
        raise ValueError("Conflicting planning updates target the same field")
    for update in updates:
        collection, target, field = update_target(contract, update.path)
        item = next(item for item in data[collection] if item["id"] == target.id)
        item[field] = update.value
    return DesignContract.model_validate(data)
