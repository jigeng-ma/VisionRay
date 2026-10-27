import unittest
from unittest.mock import MagicMock, patch

from studio.runner import unbind_before_reinstall


class ReinstallPreparationTests(unittest.TestCase):
    def setUp(self):
        self.context = {'phone': 'phone', 'glasses_name': 'DPVR G6_2831',
                        'config': {'package': 'test.app'}}
        self.adb = MagicMock()
        self.adb.shell.return_value = 'package:/data/app/test.app/base.apk'
        self.events = []

    def prepare(self, states, source=''):
        android = MagicMock()
        android.find.side_effect = lambda key: states.get(key, False)
        android.driver.page_source = source
        return android

    @patch('studio.home_device.HomeDevicePage')
    @patch('studio.android.Android')
    @patch('studio.service.start')
    def test_bound_device_is_unbound_before_reinstall(self, start, android_cls, page_cls):
        android = self.prepare({'pair.home_title': True})
        android_cls.return_value.connect.return_value = android
        unbind_before_reinstall('.', self.context, self.adb, lambda *event: self.events.append(event))
        page_cls.return_value.unbind.assert_called_once_with()
        android.close.assert_called_once_with()

    @patch('studio.home_device.HomeDevicePage')
    @patch('studio.android.Android')
    @patch('studio.service.start')
    def test_unbound_device_does_not_repair(self, start, android_cls, page_cls):
        android = self.prepare({'pair.add': True})
        android_cls.return_value.connect.return_value = android
        unbind_before_reinstall('.', self.context, self.adb, lambda *event: self.events.append(event))
        page_cls.return_value.unbind.assert_not_called()
        android.close.assert_called_once_with()

    @patch('studio.android.Android')
    @patch('studio.service.start')
    def test_unknown_state_continues_reinstall(self, start, android_cls):
        android = self.prepare({})
        android_cls.return_value.connect.return_value = android
        with patch('studio.runner.time.sleep'):
            unbind_before_reinstall('.', self.context, self.adb, lambda *event: self.events.append(event))
        self.assertIn(('service', '卸载前无法确认眼镜绑定状态，继续卸载安装。'), self.events)
        android.close.assert_called_once_with()

    @patch('studio.android.Android')
    @patch('studio.service.start')
    def test_not_installed_needs_no_appium_session(self, start, android_cls):
        self.adb.shell.return_value = ''
        unbind_before_reinstall('.', self.context, self.adb, lambda *event: self.events.append(event))
        start.assert_not_called()
        android_cls.assert_not_called()

    @patch('studio.android.Android')
    @patch('studio.service.start', side_effect=RuntimeError('Appium unavailable'))
    def test_inspection_unavailable_continues_reinstall(self, start, android_cls):
        unbind_before_reinstall('.', self.context, self.adb, lambda *event: self.events.append(event))
        self.assertIn('继续卸载安装', self.events[-1][1])
        android_cls.assert_not_called()
