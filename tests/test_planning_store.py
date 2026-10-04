from concurrent.futures import ThreadPoolExecutor
import copy
import pytest
from cadloop.errors import CadLoopError
from cadloop.planning.store import PlanningProject
from cadloop.util import read_json, tree_hashes, project_lock
from planning_helpers import proposal, reviewable


def test_init_needs_no_cad_and_proposals_are_immutable(tmp_path):
    workspace = PlanningProject.initialize(tmp_path / 'plan', brief='Make a removable mount')
    assert not (workspace.root / 'design').exists()
    assert workspace.state()['status'] == 'DRAFT'
    original = tree_hashes(workspace.folder / 'revisions')
    state = workspace.propose(proposal(workspace))
    assert state['status'] == 'NEEDS_INPUT'
    assert len(list((workspace.folder / 'revisions').glob('*.json'))) == 2
    for name, sha in original.items():
        assert tree_hashes(workspace.folder / 'revisions')[name] == sha
    assert workspace.questions()['questions'][0]['id'] == 'orientation_question'


@pytest.mark.parametrize('size', [4001, 16000])
def test_declared_brief_budget_matches_source_record_budget(tmp_path, size):
    text='x'*size
    workspace=PlanningProject.initialize(tmp_path/'plan',brief=text)
    assert workspace.context()['sources'][0]['description']==text


def test_brief_budget_rejects_before_creating_workspace(tmp_path):
    root=tmp_path/'plan'
    with pytest.raises(CadLoopError) as exc: PlanningProject.initialize(root,brief='x'*16001)
    assert exc.value.code=='PLANNING_BRIEF_INVALID'
    assert not root.exists()


def test_source_approval_answer_does_not_require_artificial_parameter_update(tmp_path):
    workspace=PlanningProject.initialize(tmp_path/'plan',brief='Make a mount')
    reviewable(workspace)
    context=workspace.context()
    packet={'base_revision':context['revision'],'reason':'Present a source interpretation','contract':context['contract']}
    contract=packet['contract']
    contract['sources'].append({'id':'inferred_requirement','kind':'MODEL_INFERRED','description':'Proposed mounting intent'})
    contract['requirements'][0].update(impact='CRITICAL',source_refs=['inferred_requirement'])
    contract['decision_candidates'].append({'id':'requirement_approval','question':'Accept this interpretation?',
        'confidence':.5,'impact':'CRITICAL','change_cost':'HIGH','affects':['removable','orientation'],
        'options':[{'id':'accept','label':'Accept','description':'Approve the stated interpretation',
                    'recommended':True,'updates':[], 'approved_source_refs':['inferred_requirement']},
                   {'id':'reconsider','label':'Reconsider','description':'Keep the claim unapproved and revise it',
                    'recommended':False,'updates':[{'path':'/parameters/orientation/confidence','value':.5}]}]})
    state=workspace.propose(packet)
    assert state['status']=='NEEDS_INPUT'
    state=workspace.answer(base=state['revision'],answers=[('requirement_approval','accept')])
    assert state['status']=='REVIEWABLE'
    assert workspace.audit()['blocking']==[]
    assert workspace.context()['accepted_decisions'][-1]['updates']==[]


def test_stale_and_invalid_proposals_do_not_mutate(tmp_path):
    workspace = PlanningProject.initialize(tmp_path / 'plan', brief='Make a mount')
    packet = proposal(workspace)
    workspace.propose(packet)
    before = tree_hashes(workspace.folder)
    with pytest.raises(CadLoopError, match='exact current'):
        workspace.propose(packet)
    invalid = proposal(workspace)
    invalid['contract']['parameters'][0]['value'] = 'invalid'
    with pytest.raises(ValueError):
        workspace.propose(invalid)
    assert tree_hashes(workspace.folder) == before


def test_oversized_revision_is_rejected_before_committing_unreadable_state(tmp_path):
    workspace=PlanningProject.initialize(tmp_path/'plan',brief='Make a mount')
    packet=proposal(workspace)
    packet['contract']['intent']='x'*4_000_000
    before=tree_hashes(workspace.folder)
    with pytest.raises(CadLoopError) as exc: workspace.propose(packet)
    assert exc.value.code=='PLANNING_REVISION_TOO_LARGE'
    assert tree_hashes(workspace.folder)==before
    assert workspace.state()['status']=='DRAFT'


def test_user_answers_bind_log_and_cannot_be_silently_undone(tmp_path):
    workspace = PlanningProject.initialize(tmp_path / 'plan', brief='Make a mount')
    state = reviewable(workspace)
    assert state['status'] == 'REVIEWABLE'
    assert state['questions'] == []
    context = workspace.context()
    assert context['contract']['parameters'][0]['value'] == 'outward'
    log = workspace.folder / 'decisions.jsonl'
    old = log.read_bytes()
    record = read_json(workspace.folder / 'revisions/000002.json')
    assert record['events'][0]['new_revision'] == state['revision']
    assert record['events'][0]['resulting_contract_hash'] == state['contract_hash']
    packet = proposal(workspace)
    packet['contract']['parameters'][0]['value'] = 'inward'
    with pytest.raises(CadLoopError) as exc:
        workspace.propose(packet)
    assert exc.value.code == 'PLANNING_PROTECTED_STATE'
    assert log.read_bytes() == old


@pytest.mark.parametrize('answers,code', [
    ([('orientation_question','missing')], 'PLANNING_OPTION_UNKNOWN'),
    ([('missing','outward')], 'PLANNING_QUESTION_INACTIVE'),
    ([('orientation_question','outward'),('orientation_question','inward')], 'PLANNING_ANSWERS_INVALID'),
    ([], 'PLANNING_ANSWERS_INVALID')])
def test_invalid_answer_batches_are_atomic(tmp_path, answers, code):
    workspace = PlanningProject.initialize(tmp_path / 'plan', brief='Make a mount')
    state = workspace.propose(proposal(workspace))
    before = tree_hashes(workspace.folder)
    with pytest.raises(CadLoopError) as exc:
        workspace.answer(base=state['revision'], answers=answers)
    assert exc.value.code == code
    assert tree_hashes(workspace.folder) == before


def test_stale_answer_is_rejected(tmp_path):
    workspace = PlanningProject.initialize(tmp_path / 'plan', brief='Make a mount')
    initial = workspace.state()['revision']
    workspace.propose(proposal(workspace))
    with pytest.raises(CadLoopError) as exc:
        workspace.answer(base=initial, answers=[('orientation_question','outward')])
    assert exc.value.code == 'STALE_REVISION'


@pytest.mark.parametrize('kind', ['USER', 'APPROVED_REFERENCE', 'ATTACHMENT_MEASURED'])
def test_model_cannot_mint_source_authority(tmp_path, kind):
    workspace = PlanningProject.initialize(tmp_path / 'plan', brief='Make a mount')
    packet = proposal(workspace)
    packet['contract']['sources'].append({'id':'invented', 'kind':kind, 'description':'Invented authority'})
    with pytest.raises(CadLoopError) as exc:
        workspace.propose(packet)
    assert exc.value.code == 'PLANNING_SOURCE_AUTHORITY'


def test_failed_commit_restores_log_and_current_revision(tmp_path, monkeypatch):
    workspace = PlanningProject.initialize(tmp_path / 'plan', brief='Make a mount')
    state = workspace.propose(proposal(workspace))
    before = tree_hashes(workspace.folder)
    import cadloop.planning.store as store
    write = store.write_json
    def failure(path, obj):
        if path.name == 'state.json':
            raise OSError('Simulated atomic commit failure')
        return write(path, obj)
    monkeypatch.setattr(store, 'write_json', failure)
    with pytest.raises(OSError):
        workspace.answer(base=state['revision'], answers=[('orientation_question','outward')])
    assert tree_hashes(workspace.folder) == before
    assert workspace.state()['revision'] == state['revision']


def test_shared_controller_lock_rejects_concurrent_mutation(tmp_path):
    workspace = PlanningProject.initialize(tmp_path / 'plan', brief='Make a mount')
    packet = proposal(workspace)
    def contender():
        try:
            workspace.propose(packet)
        except CadLoopError as exc:
            return exc.code
    with project_lock(workspace.control), ThreadPoolExecutor(1) as pool:
        assert pool.submit(contender).result() == 'PROJECT_BUSY'


@pytest.mark.parametrize('name', ['revisions/000000.json', 'decisions.jsonl', 'brief.json'])
def test_history_tampering_is_detected(tmp_path, name):
    workspace = PlanningProject.initialize(tmp_path / 'plan', brief='Make a mount')
    (workspace.folder / name).write_text('{}\n')
    with pytest.raises((CadLoopError, ValueError, KeyError)):
        workspace.state()


def test_symlink_control_path_rejected(tmp_path):
    root = tmp_path / 'plan'; root.mkdir()
    other = tmp_path / 'other'; other.mkdir()
    (root / '.cadloop').symlink_to(other, target_is_directory=True)
    with pytest.raises(CadLoopError) as exc:
        PlanningProject(root)
    assert exc.value.code == 'UNSAFE_PATH'


@pytest.mark.parametrize('conflict', [False, True])
def test_answer_batch_shared_updates_are_deduplicated_or_rejected(tmp_path, conflict):
    workspace=PlanningProject.initialize(tmp_path/'plan',brief='Make a mount')
    packet=proposal(workspace)
    question=copy.deepcopy(packet['contract']['decision_candidates'][0])
    question['id']='access_question'
    packet['contract']['decision_candidates'].append(question)
    state=workspace.propose(packet)
    before=tree_hashes(workspace.folder)
    answers=[('orientation_question','outward'),('access_question','inward' if conflict else 'outward')]
    if conflict:
        with pytest.raises(CadLoopError) as exc: workspace.answer(base=state['revision'],answers=answers)
        assert exc.value.code=='PLANNING_ANSWERS_CONFLICT'
        assert tree_hashes(workspace.folder)==before
    else:
        result=workspace.answer(base=state['revision'],answers=answers)
        assert result['status']=='REVIEWABLE'
        assert len(workspace.context()['contract']['accepted_decisions'])==2
