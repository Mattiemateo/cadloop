"""Offline concept sketches from a closed set of normalized layout primitives."""
from __future__ import annotations

import html
import math

from cadloop.errors import CadLoopError
from .contracts import DesignContract, DiagramPrimitive, ParameterSpec

VIEWS = ("front", "side", "top")


def _number(value: float | int) -> str:
    return format(value, ".12g")


def parameter_label(parameter: ParameterSpec) -> str:
    """The same canonical value formatter is used in sketches and the handoff."""
    if parameter.value is not None:
        value = (str(parameter.value).lower() if isinstance(parameter.value, bool)
                 else _number(parameter.value) if isinstance(parameter.value, (int, float))
                 else parameter.value)
        suffix = f" {parameter.unit}" if parameter.unit not in ("text", "boolean") else ""
        return f"{parameter.id} = {value}{suffix}"
    if parameter.mode == "BOUNDED":
        bounds = []
        if parameter.minimum is not None:
            bounds.append(f">= {_number(parameter.minimum)} {parameter.unit}")
        if parameter.maximum is not None:
            bounds.append(f"<= {_number(parameter.maximum)} {parameter.unit}")
        return f"{parameter.id}: {', '.join(bounds)}"
    if parameter.mode == "DERIVED":
        return f"{parameter.id}: derived from {', '.join(parameter.derived_from)}"
    return f"{parameter.id}: {parameter.mode}"


def _escape(text: str) -> str:
    # XML 1.0 forbids these characters even after ordinary HTML escaping.
    if any(not (ord(c) in (9, 10, 13) or 0x20 <= ord(c) <= 0xD7FF
                    or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF)
           for c in text):
        raise CadLoopError("PLANNING_DIAGRAM_TEXT", "Concept text contains forbidden XML characters")
    return html.escape(text, quote=True)


def _annotation(primitive: DiagramPrimitive, contract: DesignContract) -> str:
    if primitive.parameter_ref:
        return parameter_label(next(p for p in contract.parameters if p.id == primitive.parameter_ref))
    if primitive.component_ref:
        item = next(c for c in contract.components if c.id == primitive.component_ref)
        return f"{item.id}: {item.name}"
    if primitive.requirement_ref:
        item = next(r for r in contract.requirements if r.id == primitive.requirement_ref)
        return f"{item.id}: {item.text}"
    return primitive.text or ""


def _text(x: float, y: float, text: str) -> str:
    return (f'<text x="{_number(x)}" y="{_number(y)}" font-size="18" '
            f'fill="#17212b" stroke="none">{_escape(text)}</text>')


def _primitive(p: DiagramPrimitive, contract: DesignContract) -> list[str]:
    out = []
    x, y = _number(p.x), _number(p.y)
    if p.type in ("rectangle", "component_envelope", "keepout"):
        style = ' fill="#edf3f8"' if p.type == "component_envelope" else ' fill="none"'
        if p.type == "keepout":
            style = ' fill="#fff0ed" stroke="#a23b2a" stroke-dasharray="10 6"'
        out.append(f'<rect x="{x}" y="{y}" width="{_number(p.width)}" '
                   f'height="{_number(p.height)}"{style}/>')
    elif p.type == "circle":
        out.append(f'<circle cx="{x}" cy="{y}" r="{_number(p.radius)}" fill="none"/>')
    elif p.type in ("line", "axis", "arrow", "dimension"):
        style = ' stroke-dasharray="14 5 3 5"' if p.type == "axis" else ""
        if p.type in ("arrow", "dimension"):
            style += ' marker-end="url(#arrow)"'
        if p.type == "dimension":
            style += ' marker-start="url(#arrow)"'
        out.append(f'<line x1="{x}" y1="{y}" x2="{_number(p.x2)}" '
                   f'y2="{_number(p.y2)}"{style}/>')
    elif p.type == "motion_arc":
        # Generated path data contains finite numbers only, never caller-supplied SVG.
        sweep = p.end_angle_deg - p.start_angle_deg
        segments = max(1, min(36, math.ceil(abs(sweep) / 180)))
        start = math.radians(p.start_angle_deg % 360)
        sx, sy = p.x + p.radius * math.cos(start), p.y + p.radius * math.sin(start)
        path = f"M {_number(sx)} {_number(sy)}"
        for i in range(1, segments + 1):
            angle = math.radians((p.start_angle_deg + sweep * i / segments) % 360)
            ex, ey = p.x + p.radius * math.cos(angle), p.y + p.radius * math.sin(angle)
            large = int(abs(sweep / segments) > 180)
            path += (f" A {_number(p.radius)} {_number(p.radius)} 0 {large} "
                     f"{int(sweep >= 0)} {_number(ex)} {_number(ey)}")
        out.append(f'<path d="{path}" fill="none" stroke-dasharray="6 4" marker-end="url(#arrow)"/>')
    annotation = _annotation(p, contract)
    if annotation:
        if p.type == "dimension":
            out.append(_text((p.x + p.x2) / 2, (p.y + p.y2) / 2 - 12, annotation))
        else:
            out.append(_text(p.x, p.y - 12 if p.type != "label" else p.y, annotation))
    return out


def render_svgs(contract: DesignContract) -> dict[str, str]:
    """Return byte-stable UTF-8 SVG text; concept layout is explicitly not CAD."""
    contract = DesignContract.model_validate(contract.model_dump())
    result = {}
    for view in VIEWS:
        lines = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1100" role="img">',
            f"<title>{_escape(contract.task_id)} — {view} concept</title>",
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
            '<path d="M 0 0 L 10 5 L 0 10 z" fill="#17212b"/></marker></defs>',
            '<rect width="1000" height="1100" fill="white"/>',
            '<g stroke="#17212b" stroke-width="2" font-family="sans-serif">',
        ]
        primitives = contract.diagram_spec.views.get(view, [])
        for primitive in primitives:
            lines.extend(_primitive(primitive, contract))
        if not primitives:
            lines.append(_text(40, 80, "No concept primitives supplied for this view."))
        lines.extend([
            "</g>",
            _text(30, 1040, f"{view.upper()} | planning revision {contract.revision}"),
            _text(30, 1070, "Normalized concept layout; labels use contract values. Not CAD or strength evidence."),
            "</svg>",
        ])
        result[view] = "\n".join(lines) + "\n"
    return result
