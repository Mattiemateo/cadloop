"""Minimal source/feature registry usable from build123d, CadQuery or raw OCP.

This metadata is diagnostic, never accepted as evidence of a measured dimension.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import inspect
import re
from OCP.TopoDS import TopoDS_Shape
from .errors import CadLoopError


def unwrap(shape):
    if isinstance(shape, TopoDS_Shape):
        return shape
    if hasattr(shape, "vals") and callable(shape.vals):
        values = shape.vals()  # A Workplane stack may contain multiple physical objects.
        if len(values) != 1:
            raise ValueError("Register one Workplane object at a time; multiple/empty stacks must not be silently truncated")
        shape = values[0]
    elif hasattr(shape, "val") and callable(shape.val):
        shape = shape.val()
    wrapped = getattr(shape, "wrapped", None)
    if not isinstance(wrapped, TopoDS_Shape):
        raise TypeError("Parts must be build123d Shapes, CadQuery Shapes/Workplanes or OCP shapes")
    return wrapped


@dataclass
class Scene:
    parts: dict = field(default_factory=dict)
    trace: list[dict] = field(default_factory=list)

    def add(self, name: str, shape, *, feature: str = "", parameters: tuple[str, ...] = ()):
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", name) or name in self.parts:
            raise CadLoopError("INVALID_PART_ID", "Part id is invalid or duplicated", name=name)
        raw = unwrap(shape)
        if raw.IsNull():
            raise CadLoopError("EMPTY_BODY", "Cannot register a null body", name=name)
        frame = inspect.currentframe().f_back
        self.parts[name] = raw
        self.trace.append({"part": name, "feature": feature or name,
                           "source_file": frame.f_code.co_filename.split("/")[-1],
                           "source_line": frame.f_lineno, "parameters": list(parameters),
                           "portability": "opaque_python", "evidence": "untrusted_diagnostic"})
        return shape
