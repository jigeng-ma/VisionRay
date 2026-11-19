from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from xml.etree import ElementTree

import pytest

from cases.g5 import test_pairing as smoke
from cases.g5.test_pairing_full import PERMISSIONS, PairingChecks
from studio.config import resolve
from studio.errors import TestBlocked, WaitTimeout
from studio.runner import registry, runnable_modules


ROOT = Path(__file__).resolve().parents[1]
TARGET = 'DPVR G5-0791'


def page_with_mock():
    android = Mock(context={'config': resolve(ROOT, 'G5', 'G5'), 'phone': 'mock-phone', 'glasses_name': TARGET})
    android.popups.pairing_accepted = 0
    android.popups.pairing_active = False

    def wait(predicate, label, *_args, **_kwargs):
        value = predicate()
        if not value:
            raise WaitTimeout(label)
        return value

    android.wait.side_effect = wait
    return PairingChecks(android, Mock())


def xml(package, text):
    root = ElementTree.Element('hierarchy')
    ElementTree.SubElement(root, 'node', package=package, text=text)
    return ElementTree.tostring(root, encoding='unicode')


@pytest.mark.parametrize('first_prompt', ['Bluetooth is off', 'Location is off'])
def test_detection_order_restores_phone_even_after_failure(first_prompt):
    page = page_with_mock()
    a = page.a
    state = {'bluetooth': True, 'location': False}
    grants = dict.fromkeys(PERMISSIONS, True)
    initial_grants = grants.copy()
    page.prepare_logged_in_home = Mock()
    page.switch_enabled = state.__getitem__
    page.permissions = lambda: grants.copy()
    page.set_permissions = grants.update
    page.set_switch = state.__setitem__
    controller = 'com.android.permissioncontroller'
    add = Mock()
    models = Mock()
    a.driver.page_source = '<hierarchy/>'
    a.driver.press_keycode.side_effect = lambda _: setattr(a.driver, 'page_source', '<hierarchy/>')

    def find(key):
        if key == 'pair.add':
            return add
        if key == 'pair.models_title' and 'Select Your Glasses' in a.driver.page_source:
            return models
        return None

    def click_add():
        if not state['bluetooth']:
            markup = xml(page.package, first_prompt)
        elif not state['location']:
            markup = xml(page.package, 'Location is off')
        else:
            markup = xml(controller, 'Allow VisionRay to find nearby devices?')
        a.driver.page_source = markup

    def allow():
        if 'nearby devices' in a.driver.page_source:
            a.driver.page_source = xml(controller, 'Allow VisionRay to access location?')
        else:
            a.driver.page_source = xml(page.package, 'Select Your Glasses')
        for name in PERMISSIONS:
            if name.startswith('BLUETOOTH') or 'Select Your Glasses' in a.driver.page_source:
                grants[name] = True
        return True

    a.find.side_effect = find
    add.click.side_effect = click_add
    a.popups.handle.side_effect = allow
    if first_prompt == 'Bluetooth is off':
        page.check_detection_order()
        assert [call.args[0] for call in a.capture.call_args_list] == [
            'bluetooth-switch', 'location-switch', 'bluetooth-permission', 'location-permission',
        ]
    else:
        with pytest.raises(AssertionError, match='后续步骤'):
            page.check_detection_order()
    assert state == {'bluetooth': True, 'location': False}
    assert grants == initial_grants


def test_all_checks_pass_requires_model_list_without_a_prompt():
    page = page_with_mock()
    a = page.a
    page.prepare_logged_in_home = Mock()
    page.switch_enabled = Mock(return_value=True)
    page.permissions = Mock(return_value=dict.fromkeys(PERMISSIONS, True))
    add = Mock()
    add.click.side_effect = lambda: setattr(a.driver, 'page_source', xml(page.package, 'Select Your Glasses'))
    a.find.side_effect = lambda key: add if key == 'pair.add' else 'Select Your Glasses' in a.driver.page_source
    page.check_all_ready()
    a.capture.assert_called_once_with('all-checks-passed')


@pytest.mark.parametrize('marker,cards,starts', [(True, [], True), (False, [TARGET], True), (False, [], False)])
def test_next_requires_scan_or_a_real_card(marker, cards, starts):
    page = page_with_mock()
    page.a.find.side_effect = lambda _: marker
    page.device_cards = Mock(return_value=[Mock(text=name) for name in cards])
    if starts:
        page.start_scan()
    else:
        with pytest.raises(WaitTimeout):
            page.start_scan()
    page.a.click.assert_called_once_with('pair.next')


@pytest.mark.parametrize('duration', [15019, 3900, None])
def test_scan_duration_uses_new_completed_scan_for_app(duration):
    page = page_with_mock()
    page.prepare_model_search = Mock()
    page.a.find.return_value = True
    page.device_cards = Mock(return_value=[Mock(text=TARGET)])
    baseline = (f' {page.package}\n LE scans (started/stopped) : 1 / 1\n'
                ' Last 1 scans :\n 11-17 12:00:01 - 15000ms 5 results (3) CB\n')
    latest = baseline
    if duration is not None:
        latest += f' 11-17 12:02:14 - {duration}ms 5 results (4) CB\n'
    latest += (' Ongoing scans :\n 11-17 12:04:01 - 15000ms 5 results (3) CB\n\n'
               ' other.package\n LE scans (started/stopped) : 1 / 1\n'
               ' 11-17 12:05:01 - 15000ms 5 results (3) CB\n')
    page.shell = Mock(side_effect=[baseline, latest])
    if duration is None:
        with pytest.raises(TestBlocked, match='时长记录'):
            page.check_scan_duration()
    elif duration < 14500:
        with pytest.raises(AssertionError, match='3900 ms'):
            page.check_scan_duration()
    else:
        page.check_scan_duration()
        page.a.log.assert_called_with('ble-scan-duration-ms', duration)


@pytest.mark.parametrize('first,loading', [(TARGET, TARGET), ('DPVR G5-0792', TARGET), (TARGET, 'DPVR G5-0792')])
def test_first_card_checks_selection_and_loading(first, loading):
    page = page_with_mock()
    page.prepare_model_search = Mock()
    page.finish_binding = Mock()
    second = 'DPVR G5-0792' if first == TARGET else TARGET
    cards = [Mock(text=first), Mock(text=second)]
    page.device_cards = Mock(return_value=cards)
    page.a.driver.page_source = xml(page.package, f'Pairing with {loading}')
    if first != TARGET:
        with pytest.raises(TestBlocked, match='排在第一项'):
            page.bind_first_card()
        cards[0].click.assert_not_called()
        page.finish_binding.assert_not_called()
    elif loading != TARGET:
        with pytest.raises(WaitTimeout, match=TARGET):
            page.bind_first_card()
        page.finish_binding.assert_not_called()
    else:
        page.bind_first_card()
        cards[0].click.assert_called_once_with()
        page.finish_binding.assert_called_once_with(0)
    assert page.a.popups.pairing_active is False


def test_full_sheet_reuses_both_smoke_nodes_and_their_model_labels(monkeypatch):
    entries = registry(ROOT, 'G5')
    assert {key[1] for key in entries if key[0] == 'G5_全量'} == {
        'PAIR_011', 'PAIR_018', 'PAIR_028', 'PAIR_031', 'PAIR_050', 'PAIR_058', 'PAIR_059',
    }
    for full_id, smoke_id, label in [('PAIR_058', 'PAIR_001', 'Flow Echo Pilot'),
                                     ('PAIR_059', 'PAIR_002', 'Flow Echo Crystal')]:
        item = entries[('G5_全量', full_id)]
        existing = entries[('G5', smoke_id)]
        assert item['node'] == existing['node']
        assert item['automation_id'] == existing['automation_id']
        page = Mock(options={'model_label': 'unchanged', 'skip_tutorial': True})
        page.run.side_effect = lambda: (
            page.options['model_label'] == label and page.options['skip_tutorial'] is False
        ) or pytest.fail('冒烟脚本没有选择对应的 Flow Echo 型号')
        monkeypatch.setattr(smoke, 'PairingPage', lambda _: page)
        getattr(smoke, item['node'].split('::')[1])(SimpleNamespace(), Mock())
        page.run.assert_called_once_with()
        assert page.options == {'model_label': 'unchanged', 'skip_tutorial': True}


def test_full_sheet_only_schedules_registered_unambiguous_rows():
    sheet = 'G5_全量'
    entries = registry(ROOT, 'G5')
    good = {'sheet': sheet, 'id': 'PAIR_058', 'row': 2, 'automation_id': 'VisionRay_0197'}
    blank = {'sheet': sheet, 'id': 'PAIR_059', 'row': 3, 'automation_id': ''}
    unrelated = {'sheet': sheet, 'id': 'BG-019', 'row': 4, 'automation_id': ''}
    legacy = {'cases': [], 'warnings': ['existing warning'], 'reason': ''}
    source_warnings = ['原表存在缺失和重复编号']
    source = {sheet: {'cases': [good, blank, unrelated, dict(unrelated, row=5)],
                      'warnings': source_warnings, 'reason': ''}, 'G5': legacy}
    filtered = runnable_modules(source, entries)
    assert filtered['G5'] is legacy
    assert filtered[sheet]['cases'] == [good]
    assert filtered[sheet]['warnings'] == []
    assert filtered[sheet]['source_warnings'] == source_warnings
    source[sheet]['cases'].append(dict(good, row=6, automation_id=''))
    rejected = runnable_modules(source, entries)
    assert rejected[sheet]['cases'] == []
    assert '已登记用例编号重复' in rejected[sheet]['warnings'][0]
