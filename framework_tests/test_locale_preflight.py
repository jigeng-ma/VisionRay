import unittest
from unittest.mock import Mock, patch

from studio.locale import ensure_system_english


class LocalePreflightTests(unittest.TestCase):
    @patch('studio.locale.time.sleep')
    def test_android_16_switches_and_verifies_before_install(self, sleep):
        adb = Mock()
        locales = iter(('zh-CN', 'zh-CN', 'en-US'))
        adb.shell.side_effect = lambda serial, *args: (
            '36' if args == ('getprop', 'ro.build.version.sdk') else
            next(locales) if args == ('cmd', 'locale', 'get-device-locale') else '')
        events = []
        ensure_system_english(adb, 'pixel', lambda *event: events.append(event))
        adb.shell.assert_any_call('pixel', 'cmd', 'locale', 'set-device-locale', 'en-US')
        self.assertIn('en-US', events[-1][1])

    def test_android_16_failure_stops_run(self):
        adb = Mock()
        adb.shell.side_effect = lambda serial, *args: (
            '36' if args == ('getprop', 'ro.build.version.sdk') else 'zh-CN')
        with patch('studio.locale.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, '停止执行用例'):
                ensure_system_english(adb, 'pixel', lambda *_: None)

    def test_older_android_keeps_existing_language_flow(self):
        adb = Mock()
        adb.shell.return_value = '34'
        ensure_system_english(adb, 'samsung', lambda *_: None)
        adb.shell.assert_called_once_with('samsung', 'getprop', 'ro.build.version.sdk')
