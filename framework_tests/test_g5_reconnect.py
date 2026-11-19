from unittest.mock import Mock

import pytest

from cases.g5.test_reconnect import bind_additional_glasses, other_bound_name
from studio.errors import TestBlocked, WaitTimeout


@pytest.fixture(autouse=True)
def no_real_pairing_cooldown(monkeypatch):
    monkeypatch.setattr('cases.g5.test_reconnect.time.sleep', Mock())


@pytest.mark.parametrize('detected,configured,selected', [
    (['DPVR G5-0791', 'DPVR G7_CC2A', 'DPVR G5-0304'], [], 'DPVR G5-0304'),
    (['DPVR G5-0304', 'DPVR G5-0999'], ['DPVR G5-0999'], 'DPVR G5-0999'),
    (['DPVR G5-0999', 'DPVR G5-0304'], [], 'DPVR G5-0304'),
    (['DPVR G5-0304', 'DPVR G5-0304'], [], None),
    (['DPVR G5-0791', 'DPVR G7_CC2A'], [], 'DPVR G7_CC2A'),
    (['DPVR G3_ABCD'], [], 'DPVR G3_ABCD'),
    (['Flow Nova-1234'], [], 'Flow Nova-1234'),
    (['DPVR G5-0791', 'Unrelated device'], [], None),
])
def test_add_second_g5_selects_unique_eligible_device(monkeypatch, detected, configured, selected):
    options = {'model_label': 'Flow Echo Pilot', 'device_name_id': 'test:id/tv_device_name',
               'skip_tutorial': False, 'require_pairing_prompt': True}
    context = {'glasses_name': 'DPVR G5-0791', 'config': {'package': 'test',
               'name_pattern': r'DPVR\s+G5[-_]\S+'}, 'glasses_inventory': [
                   {'product': 'G5', 'glasses_name': name} for name in configured]}
    android = Mock(context=context)
    android.driver.current_activity = 'MyDevicesActivity'
    add = Mock()
    scan_rows = [Mock(text=name) for name in detected]
    android.driver.find_elements.side_effect = lambda _, resource: (
        [add] if resource.endswith('/btnAddDevice') else scan_rows if resource == options['device_name_id'] else [])

    def wait(predicate, label, timeout):
        result = predicate()
        if not result:
            raise WaitTimeout(label)
        return result

    android.wait.side_effect = wait
    pairing = Mock(options=options.copy())
    pairing._model_names.return_value = {'Flow Echo Pilot', 'Flow Echo Crystal', 'Flow Pro Pilot',
                                         'DPVR G1', 'DPVR G3', 'DPVR G6', 'Flow Nova'}
    monkeypatch.setattr('cases.g5.test_reconnect.PairingPage', Mock(return_value=pairing))

    def bind():
        assert context['glasses_name'] == selected
        assert pairing.options['skip_tutorial'] is True
        assert pairing.options['require_pairing_prompt'] is False

    pairing.bind.side_effect = bind
    if selected:
        assert bind_additional_glasses(android, ['DPVR G5-0791']) == selected
        pairing.bind.assert_called_once_with()
    else:
        with pytest.raises(TestBlocked, match='同名眼镜|未搜索到第二台'):
            bind_additional_glasses(android, ['DPVR G5-0791'])
        pairing.bind.assert_not_called()
    add.click.assert_called_once_with()
    assert context['glasses_name'] == 'DPVR G5-0791'
    assert pairing.options == options


def test_bound_nova_matches_configured_secondary():
    context = {'glasses_name': 'DPVR G5-0791',
               'glasses_inventory': [{'glasses_name': 'Flow Nova-1234'}]}
    assert other_bound_name(context, ['DPVR G5-0791', 'DPVR G7_CC2A', 'Flow Nova-1234'],
                            preferred='DPVR G7_CC2A') == 'Flow Nova-1234'
