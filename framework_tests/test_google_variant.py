import unittest
from unittest.mock import Mock, patch

from studio.auth import install_auth_variant


class GoogleVariantTests(unittest.TestCase):
    def setUp(self):
        self.android = Mock()
        self.context = {'app_version': '1.2.43-Occident-debug', 'phone': 'phone',
                        'config': {'package': 'com.dpvr.android.app.Occident'}}

    @patch('studio.auth.Adb')
    @patch('studio.pgyer.install')
    @patch('studio.pgyer.download')
    @patch('studio.pgyer.resolve_build')
    def test_release_and_debug_are_fresh_installs_with_exact_version(self, resolve, download, install, adb):
        resolve.return_value = 'build'
        download.return_value = 'apk'
        for variant, version in [('release', '1.2.43-Occident'),
                                 ('debug', '1.2.43-Occident-debug')]:
            adb.return_value.shell.return_value = '  versionName=' + version + '\n'
            install_auth_variant(self.android, self.context, variant)
            resolve.assert_called_with(unittest.mock.ANY, version, None, variant)
        self.assertEqual(install.call_count, 2)
        install.assert_called_with('phone', 'apk', 'com.dpvr.android.app.Occident')

    @patch('studio.auth.Adb')
    @patch('studio.pgyer.install')
    @patch('studio.pgyer.download', return_value='apk')
    @patch('studio.pgyer.resolve_build', return_value='build')
    def test_debug_cannot_pass_release_version_check(self, _resolve, _download, _install, adb):
        adb.return_value.shell.return_value = '  versionName=1.2.43-Occident-debug\n'
        with self.assertRaisesRegex(AssertionError, 'release 包安装后版本错误'):
            install_auth_variant(self.android, self.context, 'release')


if __name__ == '__main__':
    unittest.main()
