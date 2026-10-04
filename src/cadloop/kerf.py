"""Import Kerf plans without running its provider loop or trusting its verdicts."""
from __future__ import annotations

import ast
import math
from pathlib import Path
import tempfile

from .contracts import Requirements
from .errors import CadLoopError
from .project import Project
from .util import digest, file_hash, read_json, write_json

KERF_COMMIT = "7ff449c9cf6ecf409d4faba209119646440b92f2"
LENGTH_MM = {"mm": 1., "cm": 10., "m": 1000., "in": 25.4, "ft": 304.8}


def normalize_spec(data: dict, requirements: Requirements) -> dict:
    """Normalize independent values; approved bounds remain authoritative.

    Kerf 1.0.0 has no typed derived/boolean/enum parameter contract. Expressions
    are rejected until they can also be enforced on every subsequent proposal.
    """
    try:
        from kerf_schemas import ParameterSpec
    except ImportError as exc:
        raise CadLoopError("KERF_SCHEMA_UNAVAILABLE",
                           "Install schemas/python/kerf_schemas from the pinned Kerf checkout; see docs/KERF.md") from exc
    if not isinstance(data, dict) or "schema_version" not in data:
        raise CadLoopError("KERF_SCHEMA_VERSION_REQUIRED", "Provide explicit Kerf schema_version 1.0.0")
    spec = ParameterSpec.model_validate(data, strict=True)
    names = [p.name for p in spec.parameters]
    missing = set(requirements.parameters) - set(names)
    if missing:
        raise CadLoopError("NEEDS_INPUT", "Resolve missing approved parameters explicitly; no clarification defaults are accepted", parameters=sorted(missing))
    if len(names) != len(set(names)) or set(names) != set(requirements.parameters):
        raise CadLoopError("KERF_PARAMETER_MISMATCH", "Unique Kerf parameter names must exactly match approved requirements")
    for raw, feature in zip(data["feature_sequence"], spec.feature_sequence):
        if "parameters" not in raw or not set(feature.parameters) <= set(names):
            raise CadLoopError("KERF_FEATURE_REFERENCE", "Every feature must declare parameters referencing the table")
    values = {}
    for parameter in spec.parameters:
        unit = parameter.unit
        if unit in LENGTH_MM:
            normalized_unit, scale = "mm", LENGTH_MM[unit]
        elif unit in ("deg", "rad", "count"):
            normalized_unit, scale = ("deg", 180. / math.pi) if unit == "rad" else (unit, 1.)
        else:
            raise CadLoopError("KERF_UNIT_UNSUPPORTED", "Supported units: mm, cm, m, in, ft, deg, rad, count", parameter=parameter.name)
        approved = requirements.parameters[parameter.name]
        if approved.unit != normalized_unit or (unit == "count" and approved.kind != "integer"):
            raise CadLoopError("KERF_UNIT_MISMATCH", "Kerf units must match the approved parameter kind and unit", parameter=parameter.name)
        value = parameter.value * scale
        approved.validate_value(value)
        constraints = parameter.constraints
        if constraints:
            if constraints.expression is not None:
                raise CadLoopError("KERF_EXPRESSION_UNSUPPORTED", "Relational/derived expressions need an enforceable contract; they cannot be silently dropped")
            for bound in (constraints.min, constraints.max):
                if bound is not None and not math.isfinite(bound * scale):
                    raise CadLoopError("KERF_NONFINITE_BOUND", "Constraint bounds must be finite")
            if ((constraints.min is not None and approved.minimum < constraints.min * scale) or
                    (constraints.max is not None and approved.maximum > constraints.max * scale)):
                raise CadLoopError("KERF_BOUND_MISMATCH", "Approved bounds must preserve all Kerf bounds; review conflicting inputs in a new specification", parameter=parameter.name)
        values[parameter.name] = int(value) if approved.kind == "integer" else value
    requirements.validate_parameters(values)
    return values


def import_project(root: str | Path, *, spec: str | Path, code: str | Path,
                   requirements: str | Path, part: str) -> Project:
    """Parse and stage a single-body Build123d program. Never execute it here."""
    spec, code, requirements = Path(spec), Path(code), Path(requirements)
    raw_spec = read_json(spec)
    req = Requirements.model_validate(read_json(requirements))
    if req.expected_parts != [part]:
        raise CadLoopError("KERF_PART_MISMATCH", "This adapter imports one named body; expected_parts must contain exactly --part")
    parameters = normalize_spec(raw_spec, req)
    source_hash = file_hash(code)
    if code.stat().st_size > 400_000:
        raise CadLoopError("SOURCE_TOO_LARGE", "Kerf source exceeds the import budget")
    source = code.read_text(encoding="utf-8")
    ast.parse(source, filename="kerf_model.py")
    provenance = {
        "adapter_version": 1, "compatible_kerf_commit": KERF_COMMIT,
        "original_spec": raw_spec, "spec_sha256": digest(raw_spec),
        "original_code_sha256": source_hash, "requirements_sha256": file_hash(requirements),
        "parameter_units": {name: p.unit for name, p in req.parameters.items()},
        "planning_evidence": "untrusted_diagnostic", "native_feature_tree": False,
    }
    # Keep provenance in the design snapshot so revisions, receipts and exports
    # bind it. The original source stays intact for scoped source repairs.
    wrapper = f'''"""Kerf import: params use mm, degrees and integer counts."""
from pathlib import Path
import runpy
from cadloop.authoring import Scene

IMPORT_PROVENANCE = {provenance!r}


def build(params):
    namespace = runpy.run_path(str(Path(__file__).with_name("kerf_model.py")),
                              init_globals={{"params": params}}, run_name="__kerf_generated__")
    if "result" in namespace:
        shape = namespace["result"]
    elif "part" in namespace:
        candidate = namespace["part"]
        shape = getattr(candidate, "part", candidate)
    else:
        raise ValueError("Kerf source must assign result or a BuildPart named part")
    scene = Scene()
    scene.add({part!r}, shape, feature="kerf_result", parameters=tuple(params))
    scene.trace.append({{"kerf_import": IMPORT_PROVENANCE, "evidence": "untrusted_diagnostic"}})
    return scene
'''
    with tempfile.TemporaryDirectory(prefix="cadloop-kerf-") as directory:
        design = Path(directory)
        (design / "model.py").write_text(wrapper, encoding="utf-8")
        (design / "kerf_model.py").write_text(source, encoding="utf-8")
        write_json(design / "parameters.json", parameters)
        return Project.create(root, requirements=requirements, design_dir=design)
