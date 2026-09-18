import json
import math
from pathlib import Path
import pytest
from pydantic import ValidationError
from cadloop.contracts import Requirements, Proposal
from cadloop.errors import CadLoopError
from cadloop.util import within, read_json

@pytest.mark.parametrize('value',[True,'6',float('nan'),float('inf'),-1,100])
def test_numeric_parameter_rejects_bad_values(value,requirements,good_parameters):
    good_parameters['plate_thickness_mm']=value
    with pytest.raises(ValueError): requirements.validate_parameters(good_parameters)

@pytest.mark.parametrize('value',[0,1,'true','false',None])
def test_boolean_is_not_coerced(value,requirements,good_parameters):
    good_parameters['include_spacer']=value
    with pytest.raises(ValueError): requirements.validate_parameters(good_parameters)


def test_unknown_parameter_rejected(requirements,good_parameters):
    good_parameters['weaken_checks']=True
    with pytest.raises(ValueError): requirements.validate_parameters(good_parameters)


def test_units_not_silently_converted(requirements):
    data=requirements.model_dump(); data['units']='inch'
    with pytest.raises(ValidationError): Requirements.model_validate(data)


def test_unknown_check_cannot_be_silently_skipped(requirements):
    data=requirements.model_dump(); data['checks'][0]['kind']='pretend_pass'
    with pytest.raises(ValidationError): Requirements.model_validate(data)


def test_duplicate_check_ids_rejected(requirements):
    data=requirements.model_dump(); data['checks'].append(data['checks'][0])
    with pytest.raises(ValidationError): Requirements.model_validate(data)

@pytest.mark.parametrize('name',['../outside','/etc/passwd','a/../../x'])
def test_path_traversal_rejected(tmp_path,name):
    with pytest.raises(CadLoopError): within(tmp_path,name,must_exist=False)


def test_symlink_rejected(tmp_path):
    outside=tmp_path/'outside';outside.write_text('x')
    root=tmp_path/'root';root.mkdir();(root/'link').symlink_to(outside)
    with pytest.raises(CadLoopError): within(root,'link')


def test_nan_json_rejected(tmp_path):
    p=tmp_path/'x.json';p.write_text('{"v": NaN}')
    with pytest.raises(ValueError): read_json(p)


def test_proposal_does_not_coerce_string_numbers(project):
    with pytest.raises(ValidationError):
        Proposal(base_revision=project.revision(),parameters={'gap_mm':'12'},reason='test')
