import unittest
from unittest.mock import Mock, patch

from studio.firmware_ota import FirmwareUpdatePage, firmware_version, leave_failed_update, ensure_system_bluetooth_pairing
from studio.firmware_ota import clear_target


class FirmwareRecoveryTests(unittest.TestCase):
    def test_leaves_failed_update_through_confirmed_quit(self):
        android = Mock(context={'config': {'package': 'test.app'}})
        back, quit_button = Mock(), Mock()
        state = {'dialog': False}
        back.click.side_effect = lambda: state.__setitem__('dialog', True)

        def elements(by, value):
            if value.endswith(':id/uof_btn_text'):
                return [Mock(text='Update Failed', is_displayed=Mock(return_value=True))]
            if value.endswith(':id/top_bar_back'):
                back.is_displayed.return_value = True
                return [back]
            if value.endswith(':id/tv_title') and state['dialog']:
                return [Mock(text='Quit the update', is_displayed=Mock(return_value=True))]
            if value.endswith(':id/tv_cancel') and state['dialog']:
                quit_button.text = 'Quit'
                quit_button.is_displayed.return_value = True
                return [quit_button]
            return []

        android.driver.find_elements.side_effect = elements
        android.wait.side_effect = lambda predicate, *_: predicate()
        self.assertTrue(leave_failed_update(android))
        back.click.assert_called_once_with()
        quit_button.click.assert_called_once_with()


def test_firmware_entry_clicks_whole_row_and_confirms_page_transition():
    android = Mock(context={'config': {'package': 'test.app'}})
    android.driver.page_source = '<hierarchy/>'
    android.driver.get_window_size.return_value = {'width': 1080, 'height': 2340}
    row = Mock()
    row.is_displayed.return_value = True
    row.is_enabled.return_value = True
    screen = {'update': False}
    row.click.side_effect = lambda: screen.__setitem__('update', True)

    def elements(by, value):
        if value.endswith(':id/version'):
            return [row]
        if value.endswith(':id/uof_version'):
            return [Mock()] if screen['update'] else []
        if by == 'xpath' and 'Firmware is up to date' not in value:
            labels = ['Firmware Update'] if screen['update'] else ['Basic Information', 'Firmware Update']
            return [Mock(text=label, is_displayed=Mock(return_value=True)) for label in labels]
        return []

    android.driver.find_elements.side_effect = elements
    android.wait.side_effect = lambda predicate, *_: predicate()
    with patch('studio.firmware_ota.HomeDevicePage'):
        FirmwareUpdatePage(android).open()
    row.click.assert_called_once_with()
    android.capture.assert_called_once_with('firmware-update-page')


def test_wifi_version_reads_wifi_row_instead_of_bluetooth_row():
    android = Mock(context={'config': {'package': 'test.app'}})
    value = Mock(text='1.00.29')
    value.is_displayed.return_value = True
    android.driver.find_elements.side_effect = lambda by, locator: [value] if 'wifi_sw_version' in locator else []
    with patch('studio.firmware_ota.HomeDevicePage'):
        assert firmware_version(android, 'wifi') == '1.00.29'
    android.log.assert_called_once_with('firmware-version', {'firmware': 'wifi', 'version': '1.00.29'})


def test_g5_reads_separate_bt_and_isp_versions_and_uses_app_model():
    from studio.firmware_ota import _firmware_model

    android = Mock(context={'config': {'package': 'test.app', 'model': 'G5'}})
    rows = {'Bluetooth Version': '2.0.2', 'ISP Version': '1.3.6', 'Model': 'Flow Echo Crystal'}
    android.driver.find_elements.side_effect = lambda _, locator: [
        Mock(text=value) for label, value in rows.items() if f"@text='{label}'" in locator]
    with patch('studio.firmware_ota.HomeDevicePage'):
        assert firmware_version(android, 'bluetooth') == '2.0.2'
        assert firmware_version(android, 'isp') == '1.3.6'
        assert _firmware_model(android) == 'Flow Echo Crystal'


def test_g5_isp_uses_configured_directions_for_descending_upgrade_version():
    from studio.firmware_ota import choose_target

    android = Mock()
    upgrade = {'version': '1.3.6', 'task_id': 174}
    downgrade = {'version': '3.3.7', 'task_id': 173}
    with patch('studio.firmware_ota._firmware_model', return_value='Flow Echo Crystal'), \
         patch('studio.firmware_ota._ota_task_ids'), \
         patch('studio.firmware_ota._target', side_effect=[upgrade, downgrade, upgrade, downgrade]), \
         patch('studio.firmware_ota.firmware_version', side_effect=['1.3.6', '3.3.7']):
        assert choose_target(android, 'isp') == ('1.3.6', downgrade, 'downgrade')
        assert choose_target(android, 'isp') == ('3.3.7', upgrade, 'upgrade')


def test_g5_pilot_and_crystal_share_all_four_ota_tasks():
    from studio.firmware_ota import _ota_task_ids, _target

    assert _ota_task_ids('Flow Echo Pilot') == _ota_task_ids('Flow Echo Crystal') == (175, 176, 174, 173)
    for kind in ('bluetooth', 'isp'):
        for direction in ('upgrade', 'downgrade'):
            pilot = _target('Flow Echo Pilot', kind, direction)
            crystal = _target('Flow Echo Crystal', kind, direction)
            assert pilot['model'] == 'Flow Echo Pilot'
            assert pilot['task_id'] == crystal['task_id']
            assert pilot['version'] == crystal['version']


def test_disconnected_update_fails_immediately_with_clear_reason():
    android = Mock(context={'config': {'package': 'test.app'}})
    android.driver.page_source = ('<hierarchy><node package="test.app" '
                                  'text="Bluetooth not connected" displayed="true"/></hierarchy>')
    with unittest.TestCase().assertRaisesRegex(AssertionError, 'Bluetooth not connected'):
        FirmwareUpdatePage(android).wait_for_completion('2.00.04', '2.00.05', 'downgrade', timeout=1)
    android.capture.assert_called_once_with('firmware-bluetooth-disconnected')


def test_failed_popup_with_completed_wifi_downgrade_returns_pass_detail():
    android = Mock(context={'config': {'package': 'test.app'}})
    android.driver.find_elements.return_value = [Mock(text='Firmware update failed. Please try again later.',
                                                      is_displayed=Mock(return_value=True))]
    with patch.object(FirmwareUpdatePage, '_any_text', side_effect=[False, True]), \
         patch('studio.firmware_ota.firmware_version', return_value='1.00.28'):
        detail = FirmwareUpdatePage(android).wait_for_completion(
            '1.00.28', '1.00.29', 'downgrade', firmware='wifi')
    assert '判定 Passed' in detail and '后台任务配置' in detail
    assert '1.00.29 → 1.00.28' in detail


def test_g5_isp_failed_downgrade_uses_configured_target_not_version_order():
    android = Mock(context={'config': {'package': 'test.app', 'model': 'G5'}})
    android.driver.find_elements.return_value = []
    with patch.object(FirmwareUpdatePage, '_any_text', side_effect=[False, True]), \
         patch('studio.firmware_ota.firmware_version', return_value='3.3.7'):
        detail = FirmwareUpdatePage(android).wait_for_completion(
            '3.3.7', '1.3.6', 'downgrade', firmware='isp')
    assert '判定 Passed' in detail and '1.3.6 → 3.3.7' in detail


def test_failed_upgrade_is_not_passed_by_matching_actual_version():
    android = Mock(context={'config': {'package': 'test.app', 'model': 'G5'}})
    android.driver.find_elements.return_value = []
    with patch.object(FirmwareUpdatePage, '_any_text', side_effect=[False, True]), \
         patch('studio.firmware_ota.firmware_version', return_value='2.0.2') as read:
        with unittest.TestCase().assertRaisesRegex(AssertionError, '升级失败'):
            FirmwareUpdatePage(android).wait_for_completion('2.0.2', '2.0.1', 'upgrade')
    read.assert_not_called()


def test_failed_downgrade_with_wrong_actual_version_stays_failed():
    android = Mock(context={'config': {'package': 'test.app', 'model': 'G5'}})
    android.driver.find_elements.return_value = []
    with patch.object(FirmwareUpdatePage, '_any_text', side_effect=[False, True]), \
         patch('studio.firmware_ota.firmware_version', return_value='2.0.2'):
        with unittest.TestCase().assertRaisesRegex(AssertionError, '版本未达到目标'):
            FirmwareUpdatePage(android).wait_for_completion('2.0.1', '2.0.2', 'downgrade')


def test_wifi_case_records_pass_detail():
    from cases.g_series.test_firmware_ota import test_wifi_firmware_update
    request = Mock()
    request.node.user_properties = []
    with patch('cases.g_series.test_firmware_ota.run', return_value='降级完成'):
        test_wifi_firmware_update(Mock(), request)
    assert request.node.user_properties == [('studio_detail', '降级完成')]


def test_ota_target_is_unforced_and_offline_after_case():
    with patch('studio.firmware_ota.OtaClient') as client:
        clear_target(155)
    client.return_value.set_force.assert_called_once_with(155, False, apply=True)
    client.return_value.set_state.assert_called_once_with(155, 'offline', apply=True)


def test_ota_cleanup_still_unforces_when_offline_request_fails():
    with patch('studio.firmware_ota.OtaClient') as client:
        client.return_value.set_state.side_effect = RuntimeError('offline rejected')
        with unittest.TestCase().assertRaisesRegex(RuntimeError, '下线失败'):
            clear_target(155)
    client.return_value.set_force.assert_called_once_with(155, False, apply=True)


def test_system_bluetooth_pairs_only_the_exact_selected_glasses():
    android = Mock(context={'config': {'model': 'G7'}, 'phone': 'phone-1',
                            'glasses_name': 'DPVR G7_C837'})
    wrong = Mock(text='DPVR G7_C838')
    wrong.is_displayed.return_value = True
    target = Mock(text='DPVR G7_C837')
    target.is_displayed.return_value = True
    bonded = {'value': False}
    target.click.side_effect = lambda: bonded.__setitem__('value', True)
    def find_elements(_by, locator):
        assert "DPVR G7_C837" in locator
        return [target]

    android.driver.find_elements.side_effect = find_elements
    android.driver.page_source = '<hierarchy><node text="DPVR G7_C837"/></hierarchy>'

    def shell(_phone, *args):
        if args[:2] == ('dumpsys', 'bluetooth_manager'):
            return ('Bonded devices:\n' + ('XX:XX:XX:XX:C8:37\n' if bonded['value'] else '')
                    + 'Scan Mode Changes:')
        return ''

    with patch('studio.devices.Adb') as adb:
        adb.return_value.shell.side_effect = shell
        ensure_system_bluetooth_pairing(android)
    target.click.assert_called_once_with()
    wrong.click.assert_not_called()
    android.ensure_foreground.assert_called_once_with()


def test_forced_ota_clears_backend_and_restarts_after_popup_failure():
    from studio.firmware_ota import startup_update
    android = Mock()
    target = {'task_id': 155, 'version': '2.00.04', 'model': 'DPVR G1'}
    with patch('studio.firmware_ota.choose_target', return_value=('2.00.05', target, 'downgrade')), \
         patch('studio.firmware_ota.ensure_system_bluetooth_pairing'), \
         patch('studio.firmware_ota.prepare_target'), \
         patch('studio.firmware_ota.clear_target') as clear, \
         patch('studio.firmware_ota.FirmwareUpdatePage') as page:
        page.return_value.startup_popup.side_effect = AssertionError('popup missing')
        with unittest.TestCase().assertRaisesRegex(AssertionError, 'popup missing'):
            startup_update(android, 'bluetooth', mandatory=True)
    clear.assert_called_once_with(155)
    android.restart.assert_called_once_with()


def test_forced_ota_clears_backend_even_when_setup_fails():
    from studio.firmware_ota import startup_update
    android = Mock(context={'config': {'package': 'test.app'}})
    target = {'task_id': 155, 'model': 'DPVR G1'}
    with patch('studio.firmware_ota.choose_target', return_value=('2.00.05', target, 'downgrade')), \
         patch('studio.firmware_ota.ensure_system_bluetooth_pairing'), \
         patch('studio.firmware_ota.prepare_target', side_effect=RuntimeError('setup failed')), \
         patch('studio.firmware_ota.clear_target') as clear, \
         patch('studio.firmware_ota.FirmwareUpdatePage'):
        with unittest.TestCase().assertRaisesRegex(RuntimeError, 'setup failed'):
            startup_update(android, 'bluetooth', mandatory=True)
    clear.assert_called_once_with(155)
    android.restart.assert_called_once_with()
