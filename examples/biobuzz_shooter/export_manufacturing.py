"""Make cut and print files from CADLoop's verified BREP exports only.

Run in the validated Docker CAD profile. All dimensions are millimetres. STL
orientation and a clean CAD check do not establish print strength or fit.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import struct
import tempfile

import cadquery as cq
import ezdxf
from OCP.BRep import BRep_Builder
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS_Shape


PRINTS = {
    "left_carrier": (2, "PETG or tougher rigid filament; print bore fit coupon", (("X", -90),)),
    "left_retainer": (2, "Nut pockets up; check M3 access", (("X", -90),)),
    "left_sleeve": (2, "Flange down; verify 5 mm hex and 608 inner-ring fit", (("X", -90), ("X", 180))),
    "left_rear_foot": (4, "Square-nut pocket up; front/right locations use the same part", ()),
    "hood": (1, "On one side face; support or brim as required", (("X", 90),)),
    "flywheel_core": (1, "Cast-in core; support the raised hub/flanges by 2 mm; balance before running", (("X", 90),)),
    "feed_chute": (1, "Upright; support roof if slicer requires it", ()),
    "motor_mount": (1, "M3 nut pockets up; verify gearbox screw access", (("X", 90),)),
    "chain_guard": (1, "Front face down; rotate 60 degrees on bed", (("X", -90), ("Z", -60))),
    "camera_mount": (1, "Upright; support inclined backplate", ()),
    "turret_adapter": (1, "Upright; turret-side 76 mm pattern is provisional", ()),
    "mold_lower": (1, "Mating side up; seal print before casting", ()),
    "mold_upper": (1, "Flat outside face down; cavity up; recessed pour funnel opens on bed-facing exterior", (("X", 180),)),
}
PLY = ("left_plywood", "right_plywood", "base_plywood")
MOLD = {"mold_lower", "mold_upper"}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verified_export(directory):
    directory = directory.resolve(strict=True)
    manifest = json.loads((directory / "export_manifest.json").read_text())
    if not manifest.get("geometry_accepted") or not manifest.get("task_accepted"):
        raise ValueError(f"CADLoop did not accept geometry: {directory}")
    for relative, expected in manifest["files"].items():
        path = directory / relative
        if path.resolve() != path or not path.is_file() or path.is_symlink():
            raise ValueError(f"Unsafe or absent export artifact: {relative}")
        if digest(path) != expected:
            raise ValueError(f"Export hash mismatch: {relative}")
    geometry = directory / "geometry"
    scene = json.loads((geometry / "scene.json").read_text())
    if scene.get("schema_version") != 1 or scene.get("units") != "mm":
        raise ValueError("Expected a millimetre CADLoop scene")
    return directory, manifest, scene


def part(geometry, scene, name):
    relative = scene["parts"].get(name)
    if relative != f"parts/{name}.brep":
        raise ValueError(f"Missing registered BREP: {name}")
    path = geometry / relative
    if path.is_symlink() or path.stat().st_size > 50_000_000:
        raise ValueError(f"Unsafe BREP: {name}")
    raw = TopoDS_Shape()
    if not BRepTools.Read_s(raw, str(path), BRep_Builder()) or raw.IsNull():
        raise ValueError(f"Unreadable BREP: {name}")
    shape = cq.Shape.cast(raw)
    solids = shape.Solids()
    if not BRepCheck_Analyzer(raw, True).IsValid() or len(solids) != 1:
        raise ValueError(f"Invalid or multi-solid BREP: {name}")
    return solids[0], digest(path)


def orient(shape, turns):
    for axis, angle in turns:
        vector = (1, 0, 0) if axis == "X" else (0, 0, 1)
        shape = shape.rotate((0, 0, 0), vector, angle)
    b = shape.BoundingBox()
    return shape.translate((-b.xmin, -b.ymin, -b.zmin))


def mesh_check(path, brep_volume):
    """Check a binary STL's closed edge graph, orientation and volume."""
    data = path.read_bytes()
    if len(data) < 84:
        raise ValueError(f"Short STL: {path}")
    triangles = struct.unpack_from("<I", data, 80)[0]
    if triangles < 4 or triangles > 5_000_000 or len(data) != 84 + 50 * triangles:
        raise ValueError(f"Malformed binary STL: {path}")
    edges = Counter()
    volume = 0.0
    for record in struct.iter_unpack("<12fH", data[84:]):
        a, b, c = (record[3:6], record[6:9], record[9:12])
        vertices = [tuple(round(v, 4) for v in point) for point in (a, b, c)]
        for i in range(3):
            edges[tuple(sorted((vertices[i], vertices[(i + 1) % 3])))] += 1
        volume += (a[0] * (b[1] * c[2] - b[2] * c[1])
                   + a[1] * (b[2] * c[0] - b[0] * c[2])
                   + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6
    bad = sum(count != 2 for count in edges.values())
    if bad or not math.isfinite(volume) or volume <= 0 or abs(volume - brep_volume) / brep_volume >= 0.01:
        raise ValueError(f"STL mesh invalid: {path.name}, bad edges={bad}, volume={volume:.3f} mm³")
    return {"triangles": triangles, "nonmanifold_edges": 0,
            "mesh_volume_mm3": round(volume, 3), "brep_volume_mm3": round(brep_volume, 3)}


def top_face(shape):
    z = shape.BoundingBox().zmax
    faces = [f for f in shape.Faces() if f.geomType() == "PLANE"
             and f.normalAt().z > 0.99 and abs(f.BoundingBox().zmax - z) < 1e-4]
    if not faces:
        raise ValueError("No planar top cut face")
    face = max(faces, key=lambda f: f.Area())
    if any(not wire.IsClosed() for wire in face.Wires()):
        raise ValueError("Open wire on cut face")
    return face


def cut_face(shape, offset):
    shape = orient(shape, (("X", 90),)) if shape.BoundingBox().zlen > 3.1 else orient(shape, ())
    face = top_face(shape)
    b = face.BoundingBox()
    if b.xlen > offset[2] + 0.01 or b.ylen > offset[3] + 0.01:
        raise ValueError("Plywood cut exceeds assigned sheet cell")
    return face.translate((offset[0], offset[1], -b.zmin)), (b.xlen, b.ylen, len(face.Wires()))


def dxf(faces, path):
    cq.exporters.exportDXF(faces, str(path), approx="arc", doc_units=4)
    doc = ezdxf.readfile(path)
    if doc.header["$INSUNITS"] != 4 or not list(doc.modelspace()):
        raise ValueError(f"Invalid millimetre DXF: {path}")


def svg_from_dxf(source, destination, width, height):
    """Mirror CAD Y into SVG Y while retaining millimetre coordinates."""
    paths = []
    for entity in ezdxf.readfile(source).modelspace():
        if entity.dxftype() == "LINE":
            a, b = entity.dxf.start, entity.dxf.end
            command = f"M {a.x:.6f} {height-a.y:.6f} L {b.x:.6f} {height-b.y:.6f}"
        elif entity.dxftype() == "ARC":
            c, r = entity.dxf.center, entity.dxf.radius
            start, end = entity.dxf.start_angle, entity.dxf.end_angle
            sweep = (end - start) % 360
            if not 0 < sweep < 360:
                raise ValueError("Degenerate DXF arc")
            a, b = math.radians(start), math.radians(end)
            x1, y1 = c.x + r * math.cos(a), height - c.y - r * math.sin(a)
            x2, y2 = c.x + r * math.cos(b), height - c.y - r * math.sin(b)
            command = (f"M {x1:.6f} {y1:.6f} A {r:.6f} {r:.6f} 0 "
                       f"{int(sweep > 180)} 0 {x2:.6f} {y2:.6f}")
        else:
            raise ValueError(f"Unexpected DXF entity for SVG: {entity.dxftype()}")
        paths.append(f'<path d="{command}"/>')
    destination.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.3f}mm" '
        f'height="{height:.3f}mm" viewBox="0 0 {width:.3f} {height:.3f}" '
        'fill="none" stroke="black" stroke-width="0.1">\n'
        + "\n".join(paths) + "\n</svg>\n")


def find_variant(shooter_dir, shooter_manifest, explicit):
    if explicit:
        choices = [Path(explicit).resolve(strict=True)]
    else:
        project = shooter_dir.parent.parent
        choices = list((project / ".cadloop" / "runs" / shooter_dir.name).glob(
            "parametric_tests/hood_70_deg-*/geometry"))
    accepted = []
    for geometry in choices:
        root = geometry.parent
        report_path = root / "verification/report.json"
        if not report_path.is_file():
            continue
        report = json.loads(report_path.read_text())
        if report.get("status") != "GEOMETRY_ACCEPTED" or not report.get("geometry_accepted"):
            continue
        if any(digest(root / "input/design" / name) != shooter_manifest["files"]["input/design/" + name]
               for name in ("model.py", "fabricated.py")):
            continue
        scene = json.loads((geometry / "scene.json").read_text())
        if scene.get("units") == "mm":
            accepted.append((geometry, scene, report_path))
    if len(accepted) != 1:
        raise ValueError(f"Expected one verified 70° parametric geometry, found {len(accepted)}")
    return accepted[0]


def run(args):
    shooter_dir, shooter_manifest, shooter_scene = verified_export(Path(args.shooter_export))
    mold_dir, mold_manifest, mold_scene = verified_export(Path(args.mold_export))
    shooter = shooter_dir / "geometry"
    mold = mold_dir / "geometry"
    variant, variant_scene, variant_report = find_variant(shooter_dir, shooter_manifest, args.hood_70_geometry)
    for name in ("left_plywood", "right_plywood"):
        if digest(shooter / shooter_scene["parts"][name]) != digest(variant / variant_scene["parts"][name]):
            raise ValueError(f"70° variant changes shared plywood panel: {name}")
    output = Path(args.output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory must be new or empty")
    (output / "print").mkdir(parents=True, exist_ok=True)
    (output / "cut").mkdir(exist_ok=True)
    entries = {}
    for name, (quantity, note, turns) in PRINTS.items():
        geometry, scene = (mold, mold_scene) if name in MOLD else (shooter, shooter_scene)
        shape, source_hash = part(geometry, scene, name)
        ready = orient(shape, turns)
        path = output / "print" / f"{name}.stl"
        cq.exporters.export(ready, str(path), "STL", tolerance=0.03, angularTolerance=0.08)
        entries[name] = {"file": str(path.relative_to(output)), "sha256": digest(path),
                         "source_brep_sha256": source_hash, "quantity": quantity,
                         "material": "rigid 3D print", "orientation": list(turns),
                         "notes": note, "mesh_check": mesh_check(path, shape.Volume())}
    shape, source_hash = part(variant, variant_scene, "hood")
    path = output / "print/hood_70_deg.stl"
    cq.exporters.export(orient(shape, (("X", 90),)), str(path), "STL",
                        tolerance=0.03, angularTolerance=0.08)
    entries["hood_70_deg"] = {"file": str(path.relative_to(output)), "sha256": digest(path),
                               "source_brep_sha256": source_hash, "quantity": 1,
                               "material": "rigid 3D print", "orientation": [["X", 90]],
                               "notes": "Alternate hood only; use the same slotted plywood panels",
                               "mesh_check": mesh_check(path, shape.Volume())}
    tire, source_hash = part(shooter, shooter_scene, "silicone_tire")
    path = output / "print/silicone_tire_REFERENCE_NOT_FOR_PRINT.stl"
    cq.exporters.export(orient(tire, (("X", 90),)), str(path), "STL",
                        tolerance=0.03, angularTolerance=0.08)
    entries["silicone_tire_reference"] = {"file": str(path.relative_to(output)),
        "sha256": digest(path), "source_brep_sha256": source_hash, "quantity": 1,
        "material": "cast 25A silicone, reference mesh only; do not print",
        "mesh_check": mesh_check(path, tire.Volume())}
    cells = ((10, 10, 270, 255), (290, 10, 270, 255), (10, 285, 284, 96))
    nested = []
    for name, cell in zip(PLY, cells):
        shape, source_hash = part(shooter, shooter_scene, name)
        face, (width, height, wires) = cut_face(shape, (0, 0, cell[2], cell[3]))
        path = output / "cut" / f"{name}.dxf"
        dxf(face, path)
        svg = path.with_suffix(".svg")
        svg_from_dxf(path, svg, width, height)
        entries[name] = {"file": str(path.relative_to(output)), "sha256": digest(path),
                         "svg_file": str(svg.relative_to(output)), "svg_sha256": digest(svg),
                         "source_brep_sha256": source_hash, "quantity": 1,
                         "material": "3 mm plywood", "units": "mm", "kerf": "nominal; calibrate laser",
                         "size_mm": [round(width, 3), round(height, 3)], "closed_wires": wires}
        nested.append(face.translate((cell[0], cell[1], 0)))
    path = output / "cut/600x400_nested.dxf"
    dxf(nested, path)
    svg = path.with_suffix(".svg")
    svg_from_dxf(path, svg, 600, 400)
    result = {"schema_version": 1, "sheet_mm": [600, 400],
              "nested_cut_file": str(path.relative_to(output)), "nested_cut_sha256": digest(path),
              "nested_svg_file": str(svg.relative_to(output)), "nested_svg_sha256": digest(svg),
              "source_exports": {"shooter_revision": shooter_manifest["revision"],
                                 "mold_revision": mold_manifest["revision"],
                                 "shooter_manifest_sha256": digest(shooter_dir / "export_manifest.json"),
                                 "mold_manifest_sha256": digest(mold_dir / "export_manifest.json"),
                                 "variant_report_sha256": digest(variant_report)},
              "parts": entries,
              "process_blockers": ["No kerf compensation, print fit, rotor balance, silicone cure or shot performance certified."]}
    (output / "manufacturing_manifest.json").write_text(json.dumps(result, indent=2) + "\n")


def self_check():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        cube = cq.Workplane("XY").box(10, 10, 10).val()
        stl = root / "cube.stl"
        cq.exporters.export(cube, str(stl), "STL", tolerance=0.03, angularTolerance=0.08)
        assert mesh_check(stl, 1000)["nonmanifold_edges"] == 0
        cut = root / "cube.dxf"
        dxf(top_face(cube), cut)
        assert ezdxf.readfile(cut).header["$INSUNITS"] == 4
        svg_from_dxf(cut, root / "cube.svg", 10, 10)
        assert 'width="10.000mm"' in (root / "cube.svg").read_text()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shooter-export")
    parser.add_argument("--mold-export")
    parser.add_argument("--output")
    parser.add_argument("--hood-70-geometry", help="Accepted 70 degree parametric geometry directory")
    parser.add_argument("--self-check", action="store_true")
    options = parser.parse_args()
    if options.self_check:
        self_check()
    else:
        if not all((options.shooter_export, options.mold_export, options.output)):
            parser.error("--shooter-export, --mold-export and --output are required")
        run(options)
