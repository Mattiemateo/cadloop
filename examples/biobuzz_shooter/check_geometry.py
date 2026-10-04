"""Independent, read-only checks of a CADLoop shooter geometry export.

This reads BREP artifacts only. It does not import or execute the design source.
All measurements are millimetres in the export's X-forward, Y-shaft, Z-up frame.
"""

import argparse
import json
import math
from pathlib import Path

import cadquery as cq
from OCP.BRep import BRep_Builder
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.TopoDS import TopoDS_Shape


REQUIRED = {
    "base_plywood", "left_plywood", "right_plywood", "hood", "feed_chute",
    "flywheel_core", "silicone_tire", "left_608_reference",
    "right_608_reference", "motor_reference", "motor_mount", "chain_guard",
    "camera_mount", "limelight_reference",
}
BALL_RADIUS = 73.66 / 2


def _read_parts(directory):
    scene = json.loads((directory / "scene.json").read_text())
    if scene.get("units") != "mm" or scene.get("schema_version") != 1:
        raise ValueError("Expected a CADLoop millimetre scene export")
    listed = scene.get("parts")
    if not isinstance(listed, dict) or not REQUIRED <= listed.keys():
        raise ValueError(f"Missing required parts: {sorted(REQUIRED - set(listed or {}))}")
    files = {p.name for p in (directory / "parts").glob("*.brep")}
    if files != {f"{name}.brep" for name in listed}:
        raise ValueError("BREP files do not match scene.json part inventory")
    parts = {}
    for name, relative in listed.items():
        if relative != f"parts/{name}.brep":
            raise ValueError(f"Unexpected part path for {name}")
        path = directory / relative
        if path.is_symlink() or path.stat().st_size > 50_000_000:
            raise ValueError(f"Unsafe BREP artifact: {name}")
        raw = TopoDS_Shape()
        if not BRepTools.Read_s(raw, str(path), BRep_Builder()) or raw.IsNull():
            raise ValueError(f"Unreadable BREP: {name}")
        part = cq.Shape.cast(raw)
        solids = part.Solids()
        if not BRepCheck_Analyzer(raw, True).IsValid() or len(solids) != 1 or len(part.Faces()) != len(solids[0].Faces()):
            raise ValueError(f"Invalid or non-single-solid BREP: {name}")
        parts[name] = solids[0]
    return parts


def _box(shape):
    b = shape.BoundingBox()
    values = [b.xmin, b.ymin, b.zmin, b.xmax, b.ymax, b.zmax]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Non-finite BREP bounds")
    return values


def _gap(a, b):
    return math.sqrt(sum(max(a[i] - b[i + 3], b[i] - a[i + 3], 0) ** 2 for i in range(3)))


def _near(a, b):
    def intersection(fuzzy=0):
        operation = BRepAlgoAPI_Common(a.wrapped, b.wrapped)
        if fuzzy:
            operation.SetFuzzyValue(fuzzy)
            operation.Build()
        if not operation.IsDone() or operation.Shape().IsNull():
            return None
        common = cq.Shape.cast(operation.Shape())
        if not common.isValid():
            return None
        return common.Volume()

    volume = intersection()
    impossible = lambda value: value is None or not math.isfinite(value) or value < -1e-8 or value > min(a.Volume(), b.Volume()) + 1e-3
    regularized = impossible(volume)
    if regularized:
        # OCC can return the whole sphere for a geometrically exact tangent.
        # An intersection larger than either input is impossible; retry the
        # same solids with a recorded 0.0001 mm boolean tolerance.
        volume = intersection(0.0001)
        if impossible(volume):
            raise ValueError("BREP intersection remained inconsistent after retry")
    distance = BRepExtrema_DistShapeShape(a.wrapped, b.wrapped)
    if not distance.IsDone() or distance.NbSolution() < 1:
        raise ValueError("BREP distance query failed")
    clearance = float(distance.Value())
    if not math.isfinite(clearance) or clearance < 0:
        raise ValueError("BREP distance was not finite and nonnegative")
    return volume, clearance, regularized


def _cylinders(shape):
    for face in shape.Faces():
        surface = BRepAdaptor_Surface(face.wrapped, True)
        if surface.GetType() == GeomAbs_Cylinder:
            cylinder = surface.Cylinder()
            yield cylinder.Radius(), cylinder.Axis().Direction(), cylinder.Axis().Location()


def _ball_centers(angle):
    rho = 118.12 - BALL_RADIUS
    end = angle - 90
    count = math.ceil((end + 180) / 5)
    for i in range(count + 1):
        theta = math.radians(-180 + (end + 180) * i / count)
        yield "hood_arc", rho * math.cos(theta), 0, 140 + rho * math.sin(theta)
    for z in range(250, 139, -5):
        yield "vertical_feed", -rho, 0, z
    release_x = rho * math.cos(math.radians(end))
    release_z = 140 + rho * math.sin(math.radians(end))
    dx, dz = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    for distance in range(10, 101, 10):
        yield "straight_exit", release_x + distance * dx, 0, release_z + distance * dz
    for speed in (5, 7, 9):
        for step in range(1, 11):
            t = step * 0.005
            if speed * t <= 0.2:
                yield f"ballistic_{speed}m_s", release_x + 1000 * speed * t * dx, 0, (
                    release_z + 1000 * (speed * t * dz - 0.5 * 9.80665 * t * t))


def audit(directory, angle, deck_height):
    parts = _read_parts(directory)
    checks = {}

    boxes = {name: _box(shape) for name, shape in parts.items()}
    union = [min(b[i] for b in boxes.values()) for i in range(3)] + [
        max(b[i + 3] for b in boxes.values()) for i in range(3)]
    size = [union[i + 3] - union[i] for i in range(3)]
    checks["starting_envelope"] = {
        "pass": all(value <= 457.2 + 1e-6 for value in size) and union[5] + deck_height <= 457.2 + 1e-6,
        "bounds_mm": union, "size_mm": size, "deck_height_mm": deck_height,
        "absolute_top_mm": union[5] + deck_height, "limit_mm": 457.2,
    }
    thicknesses = {name: (boxes[name][5] - boxes[name][2] if name == "base_plywood" else boxes[name][4] - boxes[name][1])
                   for name in ("base_plywood", "left_plywood", "right_plywood")}
    checks["plywood_thickness"] = {
        "pass": all(abs(value - 3) <= 0.01 for value in thicknesses.values()),
        "measured_mm": thicknesses, "target_mm": 3,
    }

    bearings = {}
    for name in ("left_608_reference", "right_608_reference"):
        b = boxes[name]
        radii = sorted({round(radius, 4) for radius, direction, _ in _cylinders(parts[name])
                        if abs(direction.Y()) > 0.999})
        bearings[name] = {"outer_diameter_x_mm": b[3] - b[0], "outer_diameter_z_mm": b[5] - b[2],
                          "width_y_mm": b[4] - b[1], "analytic_radii_mm": radii}
    checks["bearing_608_envelopes"] = {
        "pass": all(abs(v["outer_diameter_x_mm"] - 22) < 0.01 and
                    abs(v["outer_diameter_z_mm"] - 22) < 0.01 and
                    abs(v["width_y_mm"] - 7) < 0.01 and
                    any(abs(r - 4) < 0.01 for r in v["analytic_radii_mm"]) and
                    any(abs(r - 11) < 0.01 for r in v["analytic_radii_mm"])
                    for v in bearings.values()),
        "measured": bearings, "target_id_od_width_mm": [8, 22, 7],
    }

    hood_cylinders = [(r, d, p) for r, d, p in _cylinders(parts["hood"])
                      if abs(r - 118.12) < 0.01 and abs(d.Y()) > 0.999 and
                      abs(p.X()) < 0.01 and abs(p.Z() - 140) < 0.01]
    outlet_faces = []
    for face in parts["hood"].Faces():
        if face.geomType() != "PLANE" or abs(face.Area() - 328) > 0.1:
            continue
        center, normal = face.Center(), face.normalAt()
        if center.x > 0 and center.z < 140 and normal.x > 0 and normal.z > 0:
            outlet_faces.append((face.Area(), center, normal))
    slope = math.degrees(math.atan2(outlet_faces[0][2].z, outlet_faces[0][2].x)) if len(outlet_faces) == 1 else None
    checks["hood_outlet"] = {
        "pass": len(hood_cylinders) == 1 and len(outlet_faces) == 1 and abs(slope - angle) <= 0.1,
        "inner_radius_mm": hood_cylinders[0][0] if len(hood_cylinders) == 1 else None,
        "outlet_face_area_mm2": outlet_faces[0][0] if len(outlet_faces) == 1 else None,
        "measured_tangent_deg": slope, "target_tangent_deg": angle,
    }

    near_clearances = {}
    collisions = {}
    regularized_count = 0
    samples = 0
    for stage, x, y, z in _ball_centers(angle):
        ball = cq.Solid.makeSphere(BALL_RADIUS, cq.Vector(x, y, z), angleDegrees1=-90, angleDegrees2=90)
        ball_box = _box(ball)
        samples += 1
        for name, part in parts.items():
            if name == "silicone_tire" or _gap(ball_box, boxes[name]) > 15:
                continue
            try:
                volume, clearance, regularized = _near(ball, part)
            except ValueError as error:
                raise ValueError(f"{stage} against {name} at {[x, y, z]}: {error}") from error
            regularized_count += regularized
            near_clearances[name] = min(clearance, near_clearances.get(name, math.inf))
            if volume >= 1e-5 and (name not in collisions or volume > collisions[name]["overlap_mm3"]):
                collisions[name] = {"stage": stage, "ball_center_mm": [x, y, z], "overlap_mm3": volume}
    checks["pollen_swept_sphere"] = {
        "pass": not collisions, "ball_diameter_mm": BALL_RADIUS * 2, "sample_count": samples,
        "intentional_tire_compression_mm": BALL_RADIUS * 2 - (118.12 - 50),
        "worst_collisions": collisions,
        "tangent_boolean_retries_0p0001mm": regularized_count,
        "near_clearance_mm": {name: round(distance, 4) for name, distance in
                              sorted(near_clearances.items(), key=lambda item: item[1])[:12]},
        "scope": "Discrete high-end ball samples; tire omitted intentionally; no dynamic or scoring certification",
    }
    return {"status": "PASS" if all(item["pass"] for item in checks.values()) else "FAIL",
            "geometry": str(directory), "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hood-angle", type=float, choices=(65, 70), required=True)
    parser.add_argument("--deck-height", type=float, default=180)
    args = parser.parse_args()
    try:
        if not math.isfinite(args.deck_height) or args.deck_height < 0:
            raise ValueError("Deck height must be a nonnegative finite millimetre value")
        result = audit(args.geometry, args.hood_angle, args.deck_height)
    except Exception as error:
        result = {"status": "ERROR", "geometry": str(args.geometry), "error": str(error)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{result['status']}: {args.output}")
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
