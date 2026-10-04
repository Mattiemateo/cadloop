import json
import subprocess
import sys
from cadloop.cli import main
from cadloop.planning.store import PlanningProject
from cadloop.util import write_json
from planning_helpers import proposal


def invoke(capsys, *args, code=0):
    assert main(list(map(str, args))) == code
    return json.loads(capsys.readouterr().out)


def test_planning_cli_json_round_trip(tmp_path, capsys):
    root = tmp_path / 'mount'
    state = invoke(capsys, 'design-init', root, '--brief', 'Make a removable mount')
    workspace = PlanningProject(root)
    assert state['status'] == 'DRAFT'
    context = invoke(capsys, 'design-context', root)
    assert context['original_brief']['brief'] == 'Make a removable mount'
    assert 'PlanningProposal' in str(context['proposal_schema'])
    packet = proposal(workspace)
    path = tmp_path / 'proposal.json'; write_json(path, packet)
    state = invoke(capsys, 'design-propose', root, '--base', state['revision'], '--file', path)
    assert state['status'] == 'NEEDS_INPUT'
    assert len(invoke(capsys, 'design-questions', root)['questions']) == 1
    blocked = invoke(capsys, 'design-freeze', root, '--base', state['revision'], code=2)
    assert not blocked['frozen']
    assert invoke(capsys, 'design-audit', root, code=2)['blocking']
    state = invoke(capsys, 'design-answer', root, '--base', state['revision'],
                   '--answer', 'orientation_question=outward')
    assert state['status'] == 'REVIEWABLE'
    assert invoke(capsys, 'design-audit', root)['blocking'] == []
    rendered = invoke(capsys, 'design-render', root, '--base', state['revision'])
    assert set(rendered['manifest']['files']) == {'front.svg','side.svg','top.svg'}
    state = invoke(capsys, 'design-freeze', root, '--base', state['revision'])
    assert state['status'] == 'FROZEN'
    assert invoke(capsys, 'design-handoff', root)['design_contract_hash'] == state['contract_hash']
    assert main(['design-handoff', str(root), '--format', 'markdown']) == 0
    assert capsys.readouterr().out.startswith('# CADLoop modeling handoff')
    reopened = invoke(capsys, 'design-reopen', root, '--base', state['revision'], '--reason','Reconsider geometry')
    assert reopened['status'] == 'DRAFT'


def test_stdin_proposal_and_brief_file(tmp_path):
    root = tmp_path / 'mount'
    brief = tmp_path / 'brief.txt'; brief.write_text('Make a removable mount\n')
    result = subprocess.run([sys.executable,'-m','cadloop.cli','design-init',str(root),
                             '--brief-file',str(brief)],capture_output=True,text=True,check=True)
    state = json.loads(result.stdout)
    packet = proposal(PlanningProject(root))
    result = subprocess.run([sys.executable,'-m','cadloop.cli','design-propose',str(root),
                             '--base',state['revision'],'--file','-'], input=json.dumps(packet),
                             capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)['status'] == 'NEEDS_INPUT'


def test_bad_cli_answers_are_json_and_atomic(tmp_path, capsys):
    workspace = PlanningProject.initialize(tmp_path / 'mount', brief='Make a mount')
    state = workspace.propose(proposal(workspace))
    result = invoke(capsys,'design-answer',workspace.root,'--base',state['revision'],
                    '--answer','orientation_question',code=3)
    assert result['code'] == 'PLANNING_ANSWERS_INVALID'
    assert workspace.state()['revision'] == state['revision']


def test_cli_never_evaluates_unknown_fields_or_nonfinite_input(tmp_path, capsys):
    workspace = PlanningProject.initialize(tmp_path / 'mount', brief='Make a mount')
    packet = proposal(workspace)
    packet['unexpected'] = '__import__("os").system("false")'
    path = tmp_path / 'bad.json';write_json(path,packet)
    result = invoke(capsys,'design-propose',workspace.root,'--base',workspace.state()['revision'],'--file',path,code=3)
    assert result['status'] == 'error'
