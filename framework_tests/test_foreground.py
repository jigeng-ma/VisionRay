import unittest
from unittest.mock import Mock, patch
from studio.android import Android
from studio.errors import WaitTimeout

class ForegroundTests(unittest.TestCase):
    def test_business_wait_reports_last_actual_value(self):
        a = Android({'config': {'package': 'test.app'}})
        a.wait = Mock(side_effect=WaitTimeout('等待超时'))
        with self.assertRaisesRegex(AssertionError, '期望 4，实际 3'):
            a.assert_wait(lambda: 3, 4, '媒资数量', 60)
        self.assertEqual(a.assert_wait(lambda: 4, 4, '媒资数量', 60), 4)

    def adapter(self, current):
        a=Android({'config':{'package':'test.app'}});a.driver=Mock();a.driver.current_package=current
        a.popups=Mock();a.popups.handle.return_value=False
        return a

    def test_starts_target_from_launcher(self):
        a=self.adapter('launcher')
        a.driver.activate_app.side_effect=lambda package:setattr(a.driver,'current_package',package)
        a.ensure_foreground()
        a.driver.activate_app.assert_called_once_with('test.app')

    def test_preserves_app_already_in_foreground(self):
        a=self.adapter('test.app');a.ensure_foreground()
        a.driver.activate_app.assert_not_called()

    @patch('studio.devices.Adb')
    def test_restart_uses_launcher_and_actual_focus(self, adb_type):
        a=Android({'phone':'serial', 'config':{'package':'test.app'}})
        a.driver=Mock(); a.driver.current_package='test.app'
        a.popups=Mock(); a.popups.handle.return_value=False
        adb=adb_type.return_value
        adb.shell.side_effect=[
            None,
            'mCurrentFocus=Window{0 u0 com.android.launcher/.Launcher}',
            None,
            'mCurrentFocus=Window{0 u0 test.app/.HomeActivity}',
        ]
        a.restart()
        self.assertEqual(adb.shell.call_args_list[0].args[1:], ('am', 'force-stop', 'test.app'))
        self.assertIn(('serial', 'monkey', '-p', 'test.app', '-c', 'android.intent.category.LAUNCHER', '1'),
                      [call.args for call in adb.shell.call_args_list])
