"""Closed contracts: unknown operations and non-finite values fail validation."""
from __future__ import annotations
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
import math
import re

NAME = r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Param(Strict):
    kind: Literal["number", "integer", "boolean"]
    unit: Literal["mm", "deg", "count", "boolean"]
    minimum: float | None = None
    maximum: float | None = None
    description: str

    @model_validator(mode="after")
    def ordered(self):
        if self.kind == "boolean":
            if self.unit != "boolean" or self.minimum is not None or self.maximum is not None:
                raise ValueError("Boolean parameters cannot have numeric bounds")
        elif self.minimum is None or self.maximum is None or self.minimum > self.maximum:
            raise ValueError("Numeric parameters require ordered bounds")
        return self

    def validate_value(self, value):
        if self.kind == "boolean":
            if type(value) is not bool:
                raise ValueError("Expected a boolean")
        else:
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Expected a finite number, not a boolean or a string")
            if self.kind == "integer" and int(value) != value:
                raise ValueError("Expected an integer")
            if not self.minimum <= value <= self.maximum:
                raise ValueError(f"Value must be in [{self.minimum}, {self.maximum}]")


class CylinderRef(Strict):
    kind: Literal["cylinder"]
    part: str
    center_xy: tuple[float, float] | None = None
    radius: float = Field(gt=0)
    tolerance: float = Field(default=0.001, gt=0, le=0.1)


class PlaneRef(Strict):
    kind: Literal["plane"]
    part: str
    axis: Literal["x", "y", "z"]
    side: Literal["min", "max"]
    tolerance: float = Field(default=0.0001, gt=0, le=0.1)


Ref = Annotated[Union[CylinderRef, PlaneRef], Field(discriminator="kind")]


class BaseCheck(Strict):
    id: str = Field(pattern=NAME)
    description: str
    edit_hint: str = "Inspect the implicated geometry and its source."


class DimensionCheck(BaseCheck):
    kind: Literal["dimension"]
    part: str
    axis: Literal["x", "y", "z"]
    minimum: float
    maximum: float


class Hole(Strict):
    x: float
    y: float
    radius: float = Field(gt=0)


class HolesCheck(BaseCheck):
    kind: Literal["through_holes_z"]
    part: str
    holes: list[Hole]
    tolerance: float = Field(default=0.001, gt=0, le=0.1)


class ClearanceCheck(BaseCheck):
    kind: Literal["clearance"]
    a: str
    b: str
    minimum: float = Field(ge=0)
    maximum: float | None = Field(default=None, ge=0)


class CoaxialCheck(BaseCheck):
    kind: Literal["coaxial"]
    a: str
    b: str
    max_offset: float = Field(gt=0)
    max_angle_deg: float = Field(gt=0)


class ContactCheck(BaseCheck):
    kind: Literal["plane_contact"]
    a: str
    b: str
    max_gap: float = Field(default=0.001, gt=0)
    min_area: float = Field(gt=0)


Check = Annotated[Union[DimensionCheck, HolesCheck, ClearanceCheck, CoaxialCheck, ContactCheck],
                  Field(discriminator="kind")]


class Requirements(Strict):
    schema_version: Literal[1] = 1
    name: str
    description: str
    units: Literal["mm"] = "mm"
    expected_parts: list[str] = Field(min_length=1, max_length=32)
    parameters: dict[str, Param]
    refs: dict[str, Ref] = Field(default_factory=dict)
    checks: list[Check] = Field(min_length=1, max_length=128)
    numerical_mm: float = Field(default=1e-6, gt=0, le=1e-3)
    max_overlap_mm3: float = Field(default=1e-5, gt=0, le=0.01)
    engineering_blockers: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def references(self):
        if len(self.expected_parts) != len(set(self.expected_parts)):
            raise ValueError("Duplicate part ids")
        for n in [*self.expected_parts, *self.parameters, *self.refs]:
            if not re.fullmatch(NAME, n):
                raise ValueError(f"Invalid identifier: {n}")
        from itertools import combinations
        automatic = [f"AUTO_overlap_{a}_{b}" for a,b in combinations(self.expected_parts, 2)]
        if len(automatic) != len(set(automatic)):
            raise ValueError("Part names generate ambiguous automatic pair IDs; rename the conflicting parts")
        ids = [c.id for c in self.checks]
        if len(ids) != len(set(ids)) or any(i.startswith("AUTO_") for i in ids):
            raise ValueError("Duplicate or reserved check id")
        for ref in self.refs.values():
            if ref.part not in self.expected_parts:
                raise ValueError("Reference points to unknown part")
        for c in self.checks:
            if hasattr(c, "part") and c.part not in self.expected_parts:
                raise ValueError("Check points to unknown part")
            if c.kind == "dimension" and c.minimum > c.maximum:
                raise ValueError("Inverted dimension bounds")
            if c.kind == "clearance":
                if c.a not in self.expected_parts or c.b not in self.expected_parts or c.a == c.b:
                    raise ValueError("Clearance needs two distinct known parts")
                if c.maximum is not None and c.maximum < c.minimum:
                    raise ValueError("Inverted clearance bounds")
            if c.kind in ("plane_contact", "coaxial"):
                if c.a not in self.refs or c.b not in self.refs:
                    raise ValueError("Unknown named reference")
                expected = "plane" if c.kind == "plane_contact" else "cylinder"
                if self.refs[c.a].kind != expected or self.refs[c.b].kind != expected:
                    raise ValueError("Reference kind does not match check")
        return self

    def validate_parameters(self, p: dict):
        if set(p) != set(self.parameters):
            raise ValueError("Parameter keys must exactly match the approved schema")
        for key, spec in self.parameters.items():
            try:
                spec.validate_value(p[key])
            except ValueError as e:
                raise ValueError(f"{key}: {e}") from e


class SourceEdit(Strict):
    path: str
    old: str = Field(min_length=1, max_length=12000)
    new: str = Field(max_length=12000)


class Proposal(Strict):
    base_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    parameters: dict[str, float | int | bool] = Field(default_factory=dict)
    edits: list[SourceEdit] = Field(default_factory=list, max_length=3)
    reason: str = Field(min_length=1, max_length=1200)

    @field_validator("parameters", mode="before")
    @classmethod
    def typed_numbers(cls, v):
        if not isinstance(v, dict):
            raise ValueError("Parameters must be an object")
        for x in v.values():
            if type(x) not in (int, float, bool) or (type(x) is float and not math.isfinite(x)):
                raise ValueError("Only finite numeric or boolean parameter values are accepted")
        return v


class Action(Strict):
    kind: Literal["propose", "finish", "stop"]
    proposal: Proposal | None = None
    reason: str = Field(default="", max_length=1200)

    @model_validator(mode="after")
    def has_proposal(self):
        if (self.kind == "propose") != (self.proposal is not None):
            raise ValueError("Only propose actions carry a proposal")
        return self
