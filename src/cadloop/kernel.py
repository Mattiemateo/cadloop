"""Trusted BREP queries. This module never executes a design script.

Supported feature inspection in v0: axis-aligned planar faces and complete,
unsplit analytic Z-cylinder bores. Other topology is explicitly indeterminate.
"""
from __future__ import annotations
import math
from pathlib import Path
from itertools import combinations
from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS_Shape, TopoDS_Compound, TopoDS
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX, TopAbs_REVERSED
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from OCP.gp import gp_Pnt, gp_Vec, gp_Trsf, gp_Ax2, gp_Dir
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
from OCP.IFSelect import IFSelect_RetDone
from .errors import CadLoopError


def xyz(p) -> list[float]:
    return [float(p.X()), float(p.Y()), float(p.Z())]


def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def norm(v):
    return math.sqrt(dot(v, v))


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def explore(shape, kind):
    ex = TopExp_Explorer(shape, kind)
    while ex.More():
        yield ex.Current()
        ex.Next()


def compound(shapes):
    builder = BRep_Builder()
    result = TopoDS_Compound()
    builder.MakeCompound(result)
    for shape in shapes:
        builder.Add(result, shape)
    return result


def read_brep(path: Path):
    if path.is_symlink() or path.stat().st_size > 50_000_000:
        raise CadLoopError("UNSAFE_ARTIFACT", "BREP exceeds the supported size or is a symlink")
    shape = TopoDS_Shape()
    if not BRepTools.Read_s(shape, str(path), BRep_Builder()) or shape.IsNull():
        raise CadLoopError("BREP_IMPORT_FAILED", "Cannot import non-null BREP", file=path.name)
    return shape


def write_brep(shape, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not BRepTools.Write_s(shape, str(path)):
        raise CadLoopError("BREP_EXPORT_FAILED", "BREP export failed")


def write_step(shape, path: Path):
    writer = STEPControl_Writer()
    if writer.Transfer(shape, STEPControl_AsIs) != IFSelect_RetDone:
        raise CadLoopError("STEP_EXPORT_FAILED", "STEP transfer failed")
    if writer.Write(str(path)) != IFSelect_RetDone:
        raise CadLoopError("STEP_EXPORT_FAILED", "STEP write failed")


def read_step(path: Path):
    reader = STEPControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone or reader.TransferRoots() < 1:
        raise CadLoopError("STEP_IMPORT_FAILED", "STEP import failed")
    s = reader.OneShape()
    if s.IsNull():
        raise CadLoopError("STEP_IMPORT_FAILED", "STEP import produced a null shape")
    return s


def volume(shape) -> float:
    # A contact face has no solid volume. Never integrate an open face as a solid.
    total = 0.0
    for solid in explore(shape, TopAbs_SOLID):
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(solid, props, True, False, False)
        total += props.Mass()
    if not math.isfinite(total):
        raise CadLoopError("KERNEL_INDETERMINATE", "Non-finite volume")
    return float(total)


def area(shape) -> float:
    p = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, p)
    if not math.isfinite(p.Mass()):
        raise CadLoopError("KERNEL_INDETERMINATE", "Non-finite area")
    return float(p.Mass())


def bounds(shape) -> dict:
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, b, False, False)
    if b.IsVoid() or b.IsOpen():
        raise CadLoopError("EMPTY_BODY", "No finite bounding box")
    v = b.Get()
    if not all(math.isfinite(x) for x in v):
        raise CadLoopError("KERNEL_INDETERMINATE", "Non-finite bounding box")
    return {"min": list(v[:3]), "max": list(v[3:]),
            "size": [v[i+3]-v[i] for i in range(3)]}


def metrics(shape) -> dict:
    solids = list(explore(shape, TopAbs_SOLID))
    # build123d may wrap one solid in a Compound. Accept that wrapper, but not
    # extra free faces, wires, edges or vertices alongside the physical solid.
    counts = {}
    free = False
    for label, kind in (("face", TopAbs_FACE), ("edge", TopAbs_EDGE), ("vertex", TopAbs_VERTEX)):
        all_count = sum(1 for _ in explore(shape, kind))
        contained = sum(sum(1 for _ in explore(s, kind)) for s in solids)
        counts[label + "_count"] = all_count
        free = free or all_count != contained
    return {"valid": bool(BRepCheck_Analyzer(shape, True).IsValid()),
            "solid_count": len(solids), "contains_free_topology": free, **counts,
            "volume_mm3": volume(shape), "bounds_mm": bounds(shape)}


def boolean_shape(a, b, *, operation="common"):
    factory = BRepAlgoAPI_Common if operation == "common" else BRepAlgoAPI_Cut
    op = factory(a, b)
    if not op.IsDone():
        raise CadLoopError("KERNEL_INDETERMINATE", f"Boolean {operation} did not complete")
    # These optional C++ flags are not exposed by every OCP wheel.
    if hasattr(op, "HasErrors") and op.HasErrors():
        raise CadLoopError("KERNEL_INDETERMINATE", f"Boolean {operation} reported errors")
    result = op.Shape()
    if result.IsNull() or not BRepCheck_Analyzer(result, True).IsValid():
        raise CadLoopError("KERNEL_INDETERMINATE", f"Boolean {operation} produced invalid output")
    return result


def common_volume(a, b) -> float:
    return volume(boolean_shape(a, b))


def difference_volume(a, b) -> float:
    return volume(boolean_shape(a, b, operation="cut"))


def distance(a, b) -> dict:
    tool = BRepExtrema_DistShapeShape(a, b)
    if not tool.IsDone() or tool.NbSolution() < 1:
        raise CadLoopError("KERNEL_INDETERMINATE", "BREP distance solver did not complete")
    value = float(tool.Value())
    if not math.isfinite(value) or value < 0:
        raise CadLoopError("KERNEL_INDETERMINATE", "Invalid distance result")
    return {"distance_mm": value, "point_a_mm": xyz(tool.PointOnShape1(1)),
            "point_b_mm": xyz(tool.PointOnShape2(1)),
            "method": "BRepExtrema_DistShapeShape", "frame": "world"}


def disjoint_bounds(a, b, epsilon=1e-6) -> bool:
    ba, bb = bounds(a), bounds(b)
    return any(ba["max"][i] + epsilon < bb["min"][i] or
               bb["max"][i] + epsilon < ba["min"][i] for i in range(3))


def cylinders(shape) -> list[dict]:
    found = []
    for idx, raw_face in enumerate(explore(shape, TopAbs_FACE)):
        face = TopoDS.Face_s(raw_face)
        surf = BRepAdaptor_Surface(face, True)
        if surf.GetType() != GeomAbs_Cylinder:
            continue
        c = surf.Cylinder()
        u0, u1 = surf.FirstUParameter(), surf.LastUParameter()
        v0, v1 = surf.FirstVParameter(), surf.LastVParameter()
        p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
        surf.D1((u0+u1)/2, (v0+v1)/2, p, du, dv)
        normal = du.Crossed(dv)
        if face.Orientation() == TopAbs_REVERSED:
            normal.Reverse()
        axis, origin = xyz(c.Axis().Direction()), xyz(c.Axis().Location())
        radial = sub(xyz(p), origin)
        projection = dot(radial, axis)
        radial = [radial[i] - projection*axis[i] for i in range(3)]
        sign = dot(xyz(normal), radial)
        b = bounds(face)
        found.append({"face_index": idx, "radius_mm": c.Radius(), "axis": axis,
                      "axis_origin_mm": origin, "inward": sign < 0,
                      "full_circle": abs(abs(u1-u0)-2*math.pi) < 1e-6,
                      "bounds_mm": b, "method": "analytic_cylindrical_surface"})
    return found


def bore_obstruction(shape, cylinder: dict, z_min: float, z_max: float,
                     numerical_mm: float) -> dict:
    """Test the continuous bore lumen, not just the UV/bounding span of its wall.

    A cylindrical face can retain full U/V extents while a bridge trims out part
    of its wall. A slightly inset solid cylinder detects material anywhere along
    the supported straight bore. The radial guard is numerical, not a fit offset.
    """
    guard = max(10 * numerical_mm, 1e-6)
    radius = cylinder["radius_mm"] - guard
    if radius <= guard or z_max <= z_min:
        raise CadLoopError("FEATURE_UNSUPPORTED", "Bore is too small for the configured numerical guard")
    x, y = cylinder["axis_origin_mm"][:2]
    tool = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(x, y, z_min-guard), gp_Dir(0,0,1)),
                                    radius, z_max-z_min+2*guard)
    tool.Build()
    if not tool.IsDone():
        raise CadLoopError("KERNEL_INDETERMINATE", "Bore probe construction failed")
    return {"obstruction_mm3": common_volume(shape, tool.Shape()),
            "probe_radius_mm": radius, "radial_guard_mm": guard,
            "z_span_mm": [z_min, z_max],
            "method": "continuous_inset_cylinder_BREP_common"}


def holes_z(shape, epsilon=0.001) -> list[dict]:
    result = []
    for c in cylinders(shape):
        if not c["inward"]:
            continue
        if abs(abs(c["axis"][2])-1) > 1e-8 or not c["full_circle"]:
            raise CadLoopError("FEATURE_UNSUPPORTED", "Bore is not a complete, unsplit analytic Z cylinder")
        result.append(c)
    return result


def cylinder_ref(shape, ref, *, observed=None):
    matches = [c for c in (holes_z(shape) if observed is None else observed) if
               abs(c["radius_mm"]-ref.radius) <= ref.tolerance and
               (ref.center_xy is None or math.hypot(c["axis_origin_mm"][0]-ref.center_xy[0],
                          c["axis_origin_mm"][1]-ref.center_xy[1]) <= ref.tolerance)]
    if len(matches) != 1:
        raise CadLoopError("REF_MISSING" if not matches else "REF_AMBIGUOUS",
                           "Cylinder reference must match exactly one analytic inner face",
                           match_count=len(matches), part=ref.part)
    return matches[0]


def plane_ref(shape, ref):
    axis = "xyz".index(ref.axis)
    matches = []
    for raw_face in explore(shape, TopAbs_FACE):
        face = TopoDS.Face_s(raw_face)
        s = BRepAdaptor_Surface(face, True)
        if s.GetType() != GeomAbs_Plane:
            continue
        normal = xyz(s.Plane().Axis().Direction())
        if abs(abs(normal[axis])-1) > 1e-8:
            continue
        if face.Orientation() == TopAbs_REVERSED:
            normal = [-x for x in normal]
        coordinate = xyz(s.Plane().Location())[axis]
        matches.append((coordinate, face, normal))
    if not matches:
        raise CadLoopError("REF_MISSING", "No axis-aligned planar reference face", part=ref.part)
    extreme = (min if ref.side == "min" else max)(m[0] for m in matches)
    selected = [m for m in matches if abs(m[0]-extreme) <= ref.tolerance]
    if len(selected) != 1:
        raise CadLoopError("REF_AMBIGUOUS", "Extreme plane is split into multiple faces",
                           part=ref.part, match_count=len(selected))
    coord, face, normal = selected[0]
    return face, {"coordinate_mm": coord, "axis_index": axis, "normal": normal,
                  "area_mm2": area(face)}


def projected_contact(a_face, a_info, b_face, b_info) -> dict:
    if a_info["axis_index"] != b_info["axis_index"]:
        raise CadLoopError("FEATURE_UNSUPPORTED", "Contact planes must share an axis")
    d = distance(a_face, b_face)
    axis = a_info["axis_index"]
    delta = [0., 0., 0.]
    delta[axis] = a_info["coordinate_mm"] - b_info["coordinate_mm"]
    tr = gp_Trsf()
    tr.SetTranslation(gp_Vec(*delta))
    translated = BRepBuilderAPI_Transform(b_face, tr, True).Shape()
    common = boolean_shape(a_face, translated)
    return {**d, "projected_contact_area_mm2": area(common),
            "opposing_normals": dot(a_info["normal"], b_info["normal"]) < -1+1e-8,
            "plane_a": a_info, "plane_b": b_info,
            "method": "planar_projection_common_area_and_BREP_distance"}
