import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from studio.ios import capabilities, doctor, smoke


class IOSTests(unittest.TestCase):
    def test_capabilities_require_real_target_and_preserve_app(self):
        for config in ({}, {'udid': 'phone'}, {'udid': ' ', 'bundleId': 'app'}):
            with self.assertRaises(ValueError):
                capabilities(config)
        caps = capabilities({'udid': 'phone', 'bundleId': 'app', 'xcodeOrgId': 'team'})
        self.assertEqual(caps['appium:automationName'], 'XCUITest')
        self.assertTrue(caps['appium:noReset'])
        self.assertFalse(caps['appium:autoLaunch'])
        self.assertEqual(caps['appium:xcodeOrgId'], 'team')
        self.assertNotIn('appium:appPackage', caps)

    def test_doctor_rejects_non_mac(self):
        with patch('studio.ios.sys.platform', 'win32'), self.assertRaisesRegex(RuntimeError, 'macOS'):
            doctor()

    def test_smoke_closes_session_on_capture_failure(self):
        driver = MagicMock()
        driver.page_source = '<App/>'
        driver.save_screenshot.return_value = False
        appium = MagicMock()
        appium.webdriver.Remote.return_value = driver
        with tempfile.TemporaryDirectory() as temp, patch.dict('sys.modules', {
            'appium': appium, 'appium.options': MagicMock(), 'appium.options.ios': MagicMock()
        }):
            folder = Path(temp) / 'run'
            with self.assertRaisesRegex(RuntimeError, '截图'):
                smoke({'udid': 'phone', 'bundleId': 'app'}, folder)
            driver.quit.assert_called_once()
            self.assertTrue((folder / 'error.txt').is_file())
