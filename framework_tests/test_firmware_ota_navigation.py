import unittest
from unittest.mock import Mock, patch

from studio.firmware_ota import FirmwareUpdatePage, firmware_version, leave_failed_update


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
