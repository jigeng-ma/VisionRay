import unittest
from unittest.mock import MagicMock, patch

from selenium.common.exceptions import WebDriverException

from studio.android import Android


class AppiumSettingsRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.context = {'phone': 'phone-1', 'config': {
            'appium_url': 'http://127.0.0.1:4723', 'package': 'test.app'}}

    @patch('studio.devices.Adb')
    @patch('appium.webdriver.Remote')
    def test_missing_location_permission_is_granted_and_session_retried(self, remote, adb_cls):
        driver = MagicMock(session_id='session-1')
        remote.side_effect = [WebDriverException('Appium Settings app is not running after 5000ms'), driver]
        result = Android(self.context).connect()
        self.assertIs(result.driver, driver)
        self.assertEqual(remote.call_count, 2)
        self.assertEqual(adb_cls.return_value.shell.call_args_list[0].args,
                         ('phone-1', 'pm', 'grant', 'io.appium.settings',
                          'android.permission.ACCESS_COARSE_LOCATION'))

    @patch('studio.devices.Adb')
    @patch('appium.webdriver.Remote')
    def test_other_session_error_is_not_retried(self, remote, adb_cls):
        remote.side_effect = WebDriverException('device offline')
        with self.assertRaises(WebDriverException):
            Android(self.context).connect()
        remote.assert_called_once()
        adb_cls.assert_not_called()


if __name__ == '__main__':
    unittest.main()
