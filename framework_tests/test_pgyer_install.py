import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from studio.pgyer import install


class FreshInstallTests(unittest.TestCase):
    @patch('studio.pgyer.subprocess.run')
    def test_existing_app_is_uninstalled_before_installing_lower_version(self, run):
        run.side_effect = [Mock(returncode=0, stdout='package:/base.apk', stderr=''),
                           Mock(returncode=0, stdout='Success', stderr=''),
                           Mock(returncode=0, stdout='Success', stderr='')]
        install('phone', Path('older.apk'), 'visionray')
        self.assertEqual([args.args[0] for args in run.call_args_list], [
            ['adb', '-s', 'phone', 'shell', 'pm', 'path', 'visionray'],
            ['adb', '-s', 'phone', 'uninstall', 'visionray'],
            ['adb', '-s', 'phone', 'install', 'older.apk']])

    @patch('studio.pgyer.subprocess.run')
    def test_failed_uninstall_never_attempts_install(self, run):
        run.side_effect = [Mock(returncode=0, stdout='package:/base.apk', stderr=''),
                           Mock(returncode=1, stdout='Failure', stderr='')]
        with self.assertRaisesRegex(RuntimeError, '卸载当前 APP 失败'):
            install('phone', Path('older.apk'), 'visionray')
        self.assertEqual(run.call_count, 2)

    @patch('studio.pgyer.subprocess.run')
    def test_empty_device_installs_without_uninstall(self, run):
        run.side_effect = [Mock(returncode=1, stdout='', stderr=''),
                           Mock(returncode=0, stdout='Success', stderr='')]
        install('phone', Path('current.apk'), 'visionray')
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[-1].args[0],
                         ['adb', '-s', 'phone', 'install', 'current.apk'])
