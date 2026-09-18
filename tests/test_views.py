import numpy as np
from cadloop.views import render_depth_buffer, section_lines, triangles


def test_depth_buffer_preview_and_exact_section(model, good_parameters):
    parts = model.build(good_parameters).parts
    image, handles = render_depth_buffer(parts)
    assert image.shape == (760, 1200, 3)
    assert image.dtype == np.uint8
    assert np.any(image < 100) and np.any(image > 240)
    assert len(handles) == 3
    lines = section_lines(parts["spacer"])
    assert len(lines) >= 8
    points = np.concatenate(lines)
    assert np.allclose(points[:, 1].min(), 6)
    assert np.allclose(points[:, 1].max(), 18)
    mesh = np.array(triangles(parts["upper_plate"]))
    assert np.isfinite(mesh).all() and mesh.shape[1:] == (3, 3)
