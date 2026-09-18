from pathlib import Path
import importlib.util
import pytest
from cadloop.project import Project
from cadloop.contracts import Requirements
from cadloop.util import read_json

TEMPLATE = Path(__file__).parents[1] / 'src/cadloop/templates/plate_stack'

@pytest.fixture
def requirements():
    return Requirements.model_validate(read_json(TEMPLATE / 'requirements.json'))

@pytest.fixture
def model():
    spec = importlib.util.spec_from_file_location('trusted_fixture', TEMPLATE / 'design/model_cadquery.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

@pytest.fixture
def good_parameters():
    p = read_json(TEMPLATE / 'design/parameters.json')
    p.update(include_spacer=True, gap_mm=12.)
    return p

@pytest.fixture
def project(tmp_path):
    return Project.initialize(tmp_path / 'project')
