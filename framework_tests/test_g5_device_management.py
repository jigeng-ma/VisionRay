from unittest.mock import Mock

import pytest

from cases.g5 import test_device_management as cases


@pytest.mark.parametrize('target_present', [True, False])
def test_cleanup_removes_auxiliary_and_restores_only_target(monkeypatch, target_present):
    android = Mock(context={'glasses_name': 'DPVR G5-0791', 'config': {'package': 'test'}})
    page = cases.DeviceManagement(android)
    auxiliary = Mock()
    monkeypatch.setattr(cases, 'HomeDevicePage', Mock(return_value=auxiliary))
    monkeypatch.setattr(cases, 'discovery_panel', Mock(return_value=None))
    page.home = Mock()
    page.switch = Mock()
    page._bound_names = Mock(return_value=['Flow Nova-1234'])
    target_card, other_card = Mock(), Mock()
    before = {'Flow Nova-1234': other_card}
    if target_present:
        before[page.name] = target_card
    page.cards = Mock(side_effect=[before, {page.name: target_card}])
    android.find.return_value = True
    page.keep_only_target()
    assert auxiliary.name == 'Flow Nova-1234'
    auxiliary.unbind.assert_called_once_with(require_empty=False, allow_discovery=True)
    assert page.switch.call_args_list[-1].args == (target_card, page.name)
    page.home.assert_any_call()


def test_cleanup_reports_remaining_auxiliary(monkeypatch):
    android = Mock(context={'glasses_name': 'DPVR G5-0791', 'config': {'package': 'test'}})
    page = cases.DeviceManagement(android)
    monkeypatch.setattr(cases, 'HomeDevicePage', Mock())
    monkeypatch.setattr(cases, 'discovery_panel', Mock(return_value=None))
    page.home = Mock()
    page.switch = Mock()
    page._bound_names = Mock(return_value=['DPVR G7-CC2A'])
    page.cards = Mock(return_value={page.name: Mock(), 'DPVR G7-CC2A': Mock()})
    android.find.return_value = True
    with pytest.raises(AssertionError, match='用例收尾后应仅保留'):
        page.keep_only_target()


@pytest.mark.parametrize('name,model,identifier', [
    ('DPVR G5-0791', 'Flow Echo Pilot', 'MAC: C2:02:00:00:07:91'),
    ('DPVR G7_CC2A', 'Flow Pro Pilot', 'MAC: E5:74:FC:34:CC:2A'),
    ('DPVR G3_ABCD', 'DPVR G3', 'MAC: E5:74:FC:34:AB:CD'),
    ('Flow Nova-1234', 'Flow Nova', 'SN: 0123456789'),
])
def test_card_details_cover_mixed_models(name, model, identifier):
    android = Mock(context={'glasses_name': 'DPVR G5-0791', 'config': {
        'package': 'test', 'name_pattern': r'DPVR\s+G5[-_]\S+'}})
    page = cases.DeviceManagement(android)
    elements = {'tvTag': Mock(text=model), 'tvSn': Mock(text=identifier),
                'ivDevice': Mock(), 'ivSettings': Mock()}
    page.one = Mock(side_effect=lambda resource, _: elements[resource])
    card = Mock()
    assert page.card_details(name, card) == (model, identifier.split(': ', 1)[1])
    assert [call.args[0] for call in page.one.call_args_list] == ['tvTag', 'tvSn', 'ivDevice', 'ivSettings']


def test_settings_validates_target_card_against_settings():
    page = Mock(spec=cases.DeviceManagement)
    page.name = 'DPVR G5-0791'
    page.a = Mock()
    card = Mock()
    page.start.return_value = {page.name: card}
    page.card_details.return_value = 'Flow Echo Pilot', 'C2:02:00:00:07:91'
    page.setting_value.side_effect = [page.name, 'Flow Echo Pilot', 'c2:02:00:00:07:91']
    cases.test_g5_device_settings((page, Mock()))
    page.one.assert_called_once_with('ivSettings', card)
    page.one.return_value.click.assert_called_once_with()
    page.assert_system_info.assert_called_once_with()


def test_switch_uses_nova_then_restores_g5():
    page = Mock()
    page.name = 'DPVR G5-0791'
    page.a.context = {'glasses_name': page.name}
    target, other = Mock(), Mock()
    page.start.return_value = {page.name: target, 'Flow Nova-1234': other}
    page.cards.return_value = {page.name: target}
    cases.test_g5_switch_bound_device((page, Mock()))
    assert [call.args for call in page.switch.call_args_list] == [
        (other, 'Flow Nova-1234'), (target, page.name)]


@pytest.mark.parametrize('remaining,passed', [(['Flow Nova-1234'], True),
                                             (['Flow Nova-1234', 'DPVR G5-0791'], False)])
def test_multi_unbind_requires_only_target_to_disappear(remaining, passed):
    page = Mock(spec=cases.DeviceManagement)
    page.a = Mock()
    page.name = 'DPVR G5-0791'
    page.start.return_value = ['DPVR G5-0791', 'Flow Nova-1234']
    page._bound_names.return_value = ['Flow Nova-1234']
    page.cards.return_value = remaining
    if passed:
        cases.test_g5_unbind_one_of_multiple_devices((page, Mock()))
    else:
        with pytest.raises(AssertionError, match='设备列表'):
            cases.test_g5_unbind_one_of_multiple_devices((page, Mock()))
    page.unbind.assert_called_once_with(require_empty=False)
