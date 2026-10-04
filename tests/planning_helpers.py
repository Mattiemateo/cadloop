"""Small synthetic planning packets; no CAD source is executed by planner tests."""
from cadloop.planning.contracts import DesignContract


def proposal(workspace):
    state = workspace.context()
    contract = state['contract']
    contract.update(intent='A removable synthetic motor mount', components=[
        {'id': 'motor', 'name': 'Motor', 'role': 'supplied hardware'},
        {'id': 'mount', 'name': 'Mount', 'role': 'fabricated mount'}],
        parameters=[{'id': 'orientation', 'name': 'orientation', 'kind': 'enum',
            'mode': 'FIXED', 'unit': 'text', 'value': None,
            'enum_values': ['outward', 'inward'], 'impact': 'CRITICAL'}],
        interfaces=[{'id': 'mounting', 'component_a': 'motor', 'component_b': 'mount',
            'kind': 'mounting_face', 'impact': 'CRITICAL', 'parameter_refs': ['orientation'],
            'required_parameter_refs': ['orientation'], 'resolved': False}],
        requirements=[{'id': 'removable', 'text': 'Mount can be removed',
                       'source_refs': ['src_user_1']}],
        diagram_spec={'views': {view: [{'id': view + '_label', 'type': 'label',
                                      'text': 'Concept mount'}] for view in ['front', 'side', 'top']}},
        decision_candidates=[{'id': 'orientation_question', 'question': 'Motor orientation?',
            'confidence': .5, 'impact': 'CRITICAL', 'change_cost': 'HIGH',
            'affects': ['orientation', 'mounting'], 'options': [
                {'id': option, 'label': option, 'description': 'Shaft faces ' + option,
                 'recommended': option == 'outward', 'updates': [
                    {'path': '/parameters/orientation/value', 'value': option},
                    {'path': '/interfaces/mounting/resolved', 'value': True}]}
                for option in ['outward', 'inward']]}])
    DesignContract.model_validate(contract)
    return {'base_revision': state['revision'], 'reason': 'Interpret the synthetic brief', 'contract': contract}


def reviewable(workspace):
    state = workspace.propose(proposal(workspace))
    return workspace.answer(base=state['revision'], answers=[('orientation_question', 'outward')])


def frozen(workspace):
    state = reviewable(workspace)
    workspace.render()
    return workspace.freeze(base=state['revision'])
