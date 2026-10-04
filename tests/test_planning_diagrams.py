from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from pydantic import ValidationError

from cadloop.errors import CadLoopError
from cadloop.planning.contracts import DesignContract, DiagramPrimitive
from cadloop.planning.diagrams import render_svgs
from cadloop.util import read_json

FIXTURE = Path(__file__).parents[1] / "benchmarks/planning/fixtures/motor_mount/gold_contract.json"


def contract():
    return DesignContract.model_validate(read_json(FIXTURE))


def test_three_svg_views_are_byte_identical_and_reference_canonical_values():
    first = render_svgs(contract())
    second = render_svgs(contract())
    assert list(first) == ["front", "side", "top"]
    assert first == second
    assert "motor_size_mm = 42 mm" in first["front"]
    assert "shaft_clearance_mm = 24 mm" in first["front"]
    assert "motor_orientation = shaft_outward" in first["side"]
    assert "Normalized concept layout" in first["front"]
    for svg in first.values():
        root = ET.fromstring(svg)
        assert root.tag == "{http://www.w3.org/2000/svg}svg"


def test_changed_canonical_parameter_changes_its_label_without_independent_diagram_value():
    data = contract().model_dump()
    next(p for p in data["parameters"] if p["id"] == "motor_size_mm")["value"] = 43.0
    svg = render_svgs(DesignContract.model_validate(data))["front"]
    assert "motor_size_mm = 43 mm" in svg
    assert "motor_size_mm = 42 mm" not in svg


def test_html_javascript_and_entities_are_displayed_as_escaped_text():
    data = contract().model_dump()
    malicious = '<script>alert("x")</script><image href="https://evil.test/x"/> &lt;img&gt;'
    data["diagram_spec"]["views"]["front"].append(
        {"id": "untrusted_annotation", "type": "label", "text": malicious, "x": 20.0, "y": 30.0})
    svg = render_svgs(DesignContract.model_validate(data))["front"]
    root = ET.fromstring(svg)
    tags = {node.tag.rsplit("}", 1)[-1] for node in root.iter()}
    assert "script" not in tags and "image" not in tags and "foreignObject" not in tags
    assert malicious in [node.text for node in root.iter()]
    assert "&lt;script&gt;" in svg and "&amp;lt;img&amp;gt;" in svg
    assert all("href" not in node.attrib for node in root.iter())


@pytest.mark.parametrize("character", ["\x00", "\x1b", "\ud800", "\ufffe"])
def test_forbidden_xml_characters_are_rejected(character):
    data = contract().model_dump()
    data["diagram_spec"]["views"]["front"].append(
        {"id": "invalid_xml", "type": "label", "text": "caption" + character})
    with pytest.raises(CadLoopError) as exc:
        render_svgs(DesignContract.model_validate(data))
    assert exc.value.code == "PLANNING_DIAGRAM_TEXT"


@pytest.mark.parametrize("field", ["svg", "html", "href", "style", "onclick", "src"])
def test_no_arbitrary_svg_or_remote_resource_fields(field):
    with pytest.raises(ValidationError):
        DiagramPrimitive.model_validate({"id": "unsafe", "type": "label", "text": "caption", field: "https://evil.test"})


def test_all_supported_primitives_have_closed_svg_output():
    data = contract().model_dump()
    data["diagram_spec"]["views"]["front"].extend([
        {"id": "arrow_primitive", "type": "arrow", "x": 10.0, "y": 30.0, "x2": 30.0, "y2": 10.0},
        {"id": "line_primitive", "type": "line", "x": 40.0, "y": 40.0, "x2": 80.0, "y2": 80.0},
        {"id": "arc_primitive", "type": "motion_arc", "x": 120.0, "y": 120.0, "radius": 25.0,
         "start_angle_deg": 0.0, "end_angle_deg": 360.0},
        {"id": "referenced_requirement", "type": "label", "x": 50.0, "y": 900.0, "requirement_ref": "removable"},
    ])
    svg = render_svgs(DesignContract.model_validate(data))["front"]
    root = ET.fromstring(svg)
    assert all(node.tag.rsplit("}", 1)[-1] in {
        "svg", "title", "defs", "marker", "path", "rect", "circle", "line", "g", "text"
    } for node in root.iter())
    assert "removable: Keep the motor removable" in svg
    assert 'marker-end="url(#arrow)"' in svg


def test_render_revision_is_explicit_and_absent_views_are_not_invented():
    data = contract().model_dump()
    data["revision"] = "new_revision"
    data["diagram_spec"]["views"] = {}
    result = render_svgs(DesignContract.model_validate(data))
    assert len(result) == 3
    assert all("planning revision new_revision" in svg for svg in result.values())
    assert all("No concept primitives supplied" in svg for svg in result.values())


@pytest.mark.parametrize("angles", [(-1e308, 1e308), (-360.0, 360.0), (0.0, 10000.0)])
def test_motion_arc_rejects_nonfinite_difference_or_multiple_turns(angles):
    with pytest.raises(ValidationError):
        DiagramPrimitive.model_validate({"id": "invalid_arc", "type": "motion_arc", "radius": 10.0,
                                         "start_angle_deg": angles[0], "end_angle_deg": angles[1]})
