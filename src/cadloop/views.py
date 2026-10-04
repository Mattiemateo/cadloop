"""Offline, revision-bound views derived from the actual BREP geometry."""
from __future__ import annotations
import base64
import html
import json
import math
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRep import BRep_Tool
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_REVERSED
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GeomAbs import GeomAbs_Line
from OCP.gp import gp_Pln, gp_Pnt, gp_Dir
from . import kernel as k
from .worker import load_geometry
from .errors import CadLoopError
from .util import write_json


def triangles(shape):
    mesher = BRepMesh_IncrementalMesh(shape, 0.2, False, 0.25, False)
    if not mesher.IsDone():
        raise CadLoopError("VIEW_UNAVAILABLE", "Meshing failed")
    result = []
    for raw in k.explore(shape, TopAbs_FACE):
        face = TopoDS.Face_s(raw)
        location = TopLoc_Location()
        mesh = BRep_Tool.Triangulation_s(face, location)
        if mesh is None:
            continue
        transform = location.Transformation()
        nodes = {i: k.xyz(mesh.Node(i).Transformed(transform)) for i in range(1, mesh.NbNodes()+1)}
        for i in range(1, mesh.NbTriangles()+1):
            ids = mesh.Triangle(i).Get()
            if face.Orientation() == TopAbs_REVERSED:
                ids = tuple(reversed(ids))
            result.append([nodes[j] for j in ids])
        if len(result) > 150_000:
            raise CadLoopError("VIEW_TOO_LARGE", "Mesh exceeds the v0 preview budget")
    return result


def section_lines(shape):
    plane = gp_Pln(gp_Pnt(0, 0, 0), gp_Dir(0, 1, 0))
    op = BRepAlgoAPI_Section(shape, plane, False)
    op.Build()
    if not op.IsDone():
        raise CadLoopError("VIEW_UNAVAILABLE", "Section operation failed")
    lines = []
    for raw in k.explore(op.Shape(), TopAbs_EDGE):
        edge = TopoDS.Edge_s(raw)
        curve = BRepAdaptor_Curve(edge)
        n = 2 if curve.GetType() == GeomAbs_Line else 97
        lo, hi = curve.FirstParameter(), curve.LastParameter()
        if not math.isfinite(lo) or not math.isfinite(hi):
            raise CadLoopError("VIEW_UNAVAILABLE", "Unbounded section edge")
        points = np.array([k.xyz(curve.Value(float(t))) for t in np.linspace(lo, hi, n)])
        lines.append(points[:, [0, 2]])
    return lines


def render_depth_buffer(parts):
    """Opaque, depth-buffered preview: transparent painter sorting can hide holes.

    VTK is supplied by the pinned cadquery-ocp dependency. Rendering requires a
    working offscreen graphics backend; failures are not measurements.
    """
    import vtk
    from vtk.util.numpy_support import vtk_to_numpy
    from matplotlib.colors import to_rgb
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(1, 1, 1)
    handles = []
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    for idx, (name, shape) in enumerate(parts.items()):
        points, cells = vtk.vtkPoints(), vtk.vtkCellArray()
        for face in triangles(shape):
            triangle = vtk.vtkTriangle()
            for i, point in enumerate(face):
                triangle.GetPointIds().SetId(i, points.InsertNextPoint(point))
            cells.InsertNextCell(triangle)
        poly = vtk.vtkPolyData()
        poly.SetPoints(points); poly.SetPolys(cells)
        mapper = vtk.vtkPolyDataMapper(); mapper.SetInputData(poly)
        actor = vtk.vtkActor(); actor.SetMapper(mapper)
        color = colors[idx % len(colors)]
        actor.GetProperty().SetColor(*to_rgb(color))
        actor.GetProperty().SetInterpolationToFlat()
        actor.GetProperty().SetAmbient(0.35)
        actor.GetProperty().SetDiffuse(0.65)
        renderer.AddActor(actor)
        handles.append(Patch(facecolor=color, label=name.replace("_", " ")))
    bounds = k.bounds(k.compound(parts.values()))
    center = [(a+b)/2 for a, b in zip(bounds["min"], bounds["max"])]
    span = max(max(bounds["size"]), 1)
    camera = renderer.GetActiveCamera()
    camera.SetFocalPoint(*center)
    camera.SetPosition(center[0]+1.5*span, center[1]-2.25*span, center[2]+1.1*span)
    camera.SetViewUp(0, 0, 1)
    camera.ParallelProjectionOn()
    renderer.ResetCamera()
    window = vtk.vtkRenderWindow()
    window.AddRenderer(renderer); window.SetSize(1200, 760)
    window.SetOffScreenRendering(1); window.SetMultiSamples(4)
    try:
        window.Render()
        image = vtk.vtkWindowToImageFilter()
        image.SetInput(window); image.ReadFrontBufferOff(); image.Update()
        output = image.GetOutput()
        width, height, _ = output.GetDimensions()
        if width == 0 or height == 0 or output.GetPointData().GetScalars() is None:
            raise CadLoopError("VIEW_UNAVAILABLE", "Offscreen renderer returned no pixels")
        array = vtk_to_numpy(output.GetPointData().GetScalars())
        raster = np.flipud(array.reshape(height, width, -1)).copy()
    finally:
        window.Finalize()
    return raster, handles


def render_report(run: Path, report: dict, *, output_root: Path | None = None,
                  geometry_dir: Path | None = None):
    parts = load_geometry(geometry_dir or run / "geometry")
    output_root = output_root or run
    view_dir = output_root / "views"
    view_dir.mkdir(parents=True, exist_ok=True)
    title = report["status"].replace("_", " ")
    revision = report["revision"][:12]
    raster, handles = render_depth_buffer(parts)
    fig, ax = plt.subplots(figsize=(9, 6.6), layout="constrained")
    ax.imshow(raster)
    ax.axis("off")
    ax.set_title(f"CADLoop | {title}\nRevision {revision} | nominal geometry only", pad=12)
    ax.legend(handles=handles, loc="upper left", fontsize=9)
    fig.supxlabel("Orthographic BREP-mesh preview | model units: mm | not a dimensioned drawing", fontsize=9)
    fig.savefig(view_dir / "overview.png", dpi=145)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4.5), layout="constrained")
    for name, shape in parts.items():
        color = ax._get_lines.get_next_color()
        for i, points in enumerate(section_lines(shape)):
            ax.plot(points[:, 0], points[:, 1], color=color, linewidth=1.5,
                    label=name.replace("_", " ") if i == 0 else None)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("X / mm"); ax.set_ylabel("Z / mm")
    ax.margins(x=.08, y=.35)
    ax.grid(True, alpha=.2)
    ax.legend(loc="upper right", fontsize=9)
    ax.set_title(f"Actual BREP section: Y = 0 mm\nRevision {revision} | {title}")
    gap = next((c["evidence"].get("distance_mm") for c in report["checks"] if c["id"] == "plate_gap"), None)
    if gap is not None:
        fig.supxlabel(f"Measured minimum plate distance: {gap:.3f} mm | geometry is not fabrication approval", fontsize=9)
    fig.savefig(view_dir / "section_xz.png", dpi=145)
    plt.close(fig)
    write_json(view_dir / "manifest.json", {"revision": report["revision"], "units": "mm",
               "views": {"overview": {"file": "overview.png", "method": "BREP_mesh_VTK_depth_buffer"},
                         "section_xz": {"file": "section_xz.png", "method": "BREP_plane_intersection",
                                        "plane": {"origin_mm": [0,0,0], "normal": [0,1,0]}}}})
    images = {}
    for name in ("overview", "section_xz"):
        images[name] = "data:image/png;base64," + base64.b64encode((view_dir / f"{name}.png").read_bytes()).decode()
    esc = html.escape
    rows = []
    for c in report["checks"]:
        details = esc(json.dumps(c["evidence"], indent=2))
        rows.append(f'<tr><td><code>{esc(c["id"])}</code></td><td class="{c["status"]}">{esc(c["status"].upper())}</td>'
                    f'<td>{esc(c["message"])}<details><summary>Measured evidence</summary><pre>{details}</pre></details></td></tr>')
    blockers = "".join(f"<li>{esc(x)}</li>" for x in report["engineering_blockers"])
    summary = report["summary"]
    content = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>CADLoop checkpoint {revision}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 24px;background:#f5f7f9;color:#172331;line-height:1.5}}
h1{{font-size:36px;letter-spacing:-1px;margin-bottom:8px}}.eyebrow{{font-size:12px;letter-spacing:2px;text-transform:uppercase}}
.card{{background:white;border:1px solid #dce1e6;border-radius:12px;padding:22px;margin:20px 0}}.status{{font-size:20px;font-weight:650}}
.pass{{color:#176842}}.fail{{color:#a2222c}}.indeterminate{{color:#805200}}
img{{max-width:100%;display:block;margin:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #e0e5ea;vertical-align:top}}
pre{{overflow:auto;max-height:360px;font-size:12px}}code{{overflow-wrap:anywhere}}summary{{cursor:pointer;font-size:12px;margin-top:6px}}.meta{{font-size:13px;color:#526474}}
</style></head><body><div class="eyebrow">CADLoop / Independent geometry evidence</div>
<h1>{esc(title)}</h1><div class="meta">Revision <code>{report['revision']}</code> | units: mm | schema 1</div>
<div class="card"><div class="status">{summary['pass']} passing / {summary['fail']} failing / {summary['indeterminate']} indeterminate</div>
<p>Acceptance scope: nominal geometry only. Engineering approval: <strong>not granted</strong>.</p><ul>{blockers}</ul></div>
<div class="card"><img alt="Isometric rendering of the actual CAD solids" src="{images['overview']}"></div>
<div class="card"><img alt="Cross section from exact BREP plane intersection" src="{images['section_xz']}"></div>
<div class="card"><h2>Checks and raw measurements</h2><table><thead><tr><th>Check</th><th>Result</th><th>Evidence</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p class="meta">Generated from revision-matched solid geometry. Pictures aid review; measurements determine the check results. This page is self-contained and makes no external network requests.</p>
</body></html>'''
    (output_root / "report.html").write_text(content)
