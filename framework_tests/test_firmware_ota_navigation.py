import unittest
from unittest.mock import Mock, patch

from studio.firmware_ota import FirmwareUpdatePage, firmware_version, leave_failed_update
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
        if by == 'xpath':
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
    assert detail == ('APP提示OTA失败，但检查版本已从1.00.29降到1.00.28版本，'
                      '判定降级成功，忽略异常提示')


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


def test_forced_ota_clears_backend_and_restarts_after_popup_failure():
    from cases.g_series.test_firmware_ota import _startup_update
    android = Mock()
    with patch('cases.g_series.test_firmware_ota.choose_target', return_value=('2.00.05', {'task_id': 155, 'version': '2.00.04'}, 'downgrade')), \
         patch('cases.g_series.test_firmware_ota.prepare_target'), \
         patch('cases.g_series.test_firmware_ota.clear_target') as clear, \
         patch('cases.g_series.test_firmware_ota.FirmwareUpdatePage') as page:
        page.return_value.startup_popup.side_effect = AssertionError('popup missing')
        with unittest.TestCase().assertRaisesRegex(AssertionError, 'popup missing'):
            _startup_update(android, 'bluetooth', mandatory=True)
    clear.assert_called_once_with(155)
    android.restart.assert_called_once_with()


def test_forced_ota_clears_backend_even_when_setup_fails():
    from cases.g_series.test_firmware_ota import _startup_update
    android = Mock(context={'config': {'package': 'test.app'}})
    with patch('cases.g_series.test_firmware_ota.choose_target', return_value=('2.00.05', {'task_id': 155}, 'downgrade')), \
         patch('cases.g_series.test_firmware_ota.prepare_target', side_effect=RuntimeError('setup failed')), \
         patch('cases.g_series.test_firmware_ota.clear_target') as clear, \
         patch('cases.g_series.test_firmware_ota.FirmwareUpdatePage'):
        with unittest.TestCase().assertRaisesRegex(RuntimeError, 'setup failed'):
            _startup_update(android, 'bluetooth', mandatory=True)
    clear.assert_called_once_with(155)
    android.restart.assert_called_once_with()
