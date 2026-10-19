import unittest
from io import BytesIO
from unittest.mock import Mock, patch

from cases.g_series.test_foundation import _assert_first_launch, _older_build, _set_locale, test_lower_version_cover_install as cover_install_case
from studio.errors import WaitTimeout


class _Row:
    rect = {'x': 10, 'y': 100, 'width': 20, 'height': 20}

    def __init__(self, android, direct=True):
        self.android = android
        self.direct = direct

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True

    def click(self):
        if self.direct:
            self.android.locale = 'zh-CN'


class _Driver:
    def __init__(self, android, direct=True):
        self.android = android
        self.direct = direct
        self.current_package = 'com.android.settings'
        self.scripts = []
        self.keycodes = []

    def find_elements(self, by, value):
        if "中文 (简体)" in value:
            return [_Row(self.android, self.direct)]
        if value == 'com.android.settings:id/dragHandle':
            return [_Row(self.android)]
        return []

    def get_window_size(self):
        return {'width': 1080, 'height': 2400}

    def execute_script(self, name, args):
        self.scripts.append((name, args))
        if name == 'mobile: dragGesture':
            self.android.locale = 'zh-CN'

    def press_keycode(self, value):
        self.keycodes.append(value)


class _Android:
    def __init__(self, direct=True):
        self.locale = 'en-US'
        self.driver = _Driver(self, direct)

    def wait(self, predicate, label, timeout):
        result = predicate()
        if not result:
            raise WaitTimeout(label)
        return result


class FoundationTests(unittest.TestCase):
    def test_lower_version_is_fresh_installed_before_upgrade(self):
        context = {'phone': 'phone', 'config': {'package': 'visionray'},
                   'glasses_name': 'G1', 'app_version': '1.2.41-debug'}
        android, adb = Mock(), Mock()
        adb.run.return_value = 'Success'
        adb.shell.return_value = 'versionName=1.2.40-debug'
        android.find.return_value = True
        android.wait.side_effect = lambda predicate, *_: predicate()
        with patch('cases.g_series.test_foundation._older_build', return_value=('build', '1.2.40-debug')), patch(
            'cases.g_series.test_foundation.download', return_value='old.apk'
        ), patch('cases.g_series.test_foundation._install_current') as install_current, patch(
            'cases.g_series.test_foundation.HomeDevicePage'
        ) as home_page, patch('cases.g_series.test_foundation.AuthPage') as auth_page:
            def check_upgrade(*_):
                self.assertEqual(adb.run.call_args_list, [
                    unittest.mock.call('-s', 'phone', 'uninstall', 'visionray'),
                    unittest.mock.call('-s', 'phone', 'install', 'old.apk')])
                self.assertEqual(android.restart.call_count, 1)
                auth_page.return_value.home.assert_called_once_with()
                home_page.return_value.home.assert_called_once_with()
            install_current.side_effect = check_upgrade
            cover_install_case(android, adb, context)
        install_current.assert_called_once_with(adb, context)
        self.assertEqual(android.restart.call_count, 2)
        android.find.assert_called_once_with('pair.home_title')

    def test_failed_low_version_setup_restores_current_app(self):
        context = {'phone': 'phone', 'config': {'package': 'visionray'},
                   'glasses_name': 'G1', 'app_version': '1.2.41-debug'}
        android, adb = Mock(), Mock()
        adb.run.side_effect = ['Success', RuntimeError('old install failed')]
        with patch('cases.g_series.test_foundation._older_build', return_value=('build', '1.2.40-debug')), patch(
            'cases.g_series.test_foundation.download', return_value='old.apk'
        ), patch('cases.g_series.test_foundation._install_current') as install_current:
            with self.assertRaisesRegex(RuntimeError, 'old install failed'):
                cover_install_case(android, adb, context)
        install_current.assert_called_once_with(adb, context)

    def test_samsung_settings_home_opens_general_management_language(self):
        android = _Android()
        class SamsungDriver(_Driver):
            stage = 'home'
            swipes = 0

            def find_elements(self, by, value):
                if 'General management' in value and self.stage == 'home' and self.swipes:
                    item = Mock()
                    item.is_displayed.return_value = item.is_enabled.return_value = True
                    item.click.side_effect = lambda: setattr(self, 'stage', 'general')
                    return [item]
                if "@text='Language'" in value and self.stage == 'general':
                    item = Mock()
                    item.is_displayed.return_value = item.is_enabled.return_value = True
                    item.click.side_effect = lambda: setattr(self, 'stage', 'language')
                    return [item]
                if '中文 (简体)' in value and self.stage == 'language':
                    return [_Row(android)]
                return []

            def swipe(self, *_):
                self.swipes += 1

        android.driver = SamsungDriver(android)
        class Adb:
            def shell(self, serial, *args):
                return android.locale if args[:2] == ('getprop', 'persist.sys.locale') else ''
        _set_locale(android, Adb(), 'phone', 'zh-CN')
        self.assertEqual(android.driver.stage, 'language')
        self.assertGreater(android.driver.swipes, 0)
        self.assertEqual(android.locale, 'zh-CN')

    def test_already_selected_language_needs_no_settings_navigation(self):
        android = _Android()
        test = self
        class Adb:
            def shell(self, serial, *args):
                test.assertEqual(args[:2], ('getprop', 'persist.sys.locale'))
                return 'en-US'
        _set_locale(android, Adb(), 'phone', 'en-US')

    def test_older_debug_build_is_found_on_detail_page(self):
        current = 'a' * 32
        same_version = 'b' * 32
        older = 'c' * 32
        pages = {
            'https://www.pgyer.com/visionray-android-5': f'/app/build/{current}',
            f'https://www.pgyer.com/app/build/{current}':
                f"aVersion = '1.2.41-Occident'; data-url='/{same_version}' data-url='/{older}'",
            f'https://www.pgyer.com/app/build/{same_version}': "aVersion = '1.2.41-Occident-debug'",
            f'https://www.pgyer.com/app/build/{older}': "aVersion = '1.2.40-Occident-debug'",
        }
        with patch('studio.pgyer.fetch', side_effect=lambda url: BytesIO(pages[url].encode())):
            self.assertEqual(_older_build({'app_version': '1.2.41-Occident-debug'}),
                             (older, '1.2.40-Occident-debug'))

    def test_hyperos_language_row_is_clicked_directly(self):
        android = _Android()

        class Adb:
            def shell(self, serial, *args):
                if args[:2] == ('getprop', 'persist.sys.locale'):
                    return android.locale
                return ''

        _set_locale(android, Adb(), 'phone', 'zh-CN')
        self.assertEqual(android.locale, 'zh-CN')

    def test_one_ui_language_falls_back_to_dragging_the_row_first(self):
        android = _Android(direct=False)

        class Adb:
            def shell(self, serial, *args):
                if args[:2] == ('getprop', 'persist.sys.locale'):
                    return android.locale
                return ''

        _set_locale(android, Adb(), 'phone', 'zh-CN')
        self.assertEqual(android.locale, 'zh-CN')
        self.assertIn('mobile: dragGesture', [name for name, _ in android.driver.scripts])
        self.assertEqual(android.driver.keycodes, [4])

    def test_first_launch_accepts_localized_page_by_ids(self):
        class Android:
            context = {'config': {'package': 'app'}}
            driver = type('Driver', (), {'page_source': 'app:id/ll_user_privacy app:id/tv_agree'})()

            def ensure_foreground(self):
                pass

            def capture(self, name):
                self.name = name

        android = Android()
        _assert_first_launch(android)
        self.assertEqual(android.name, 'first-launch-agreement')


if __name__ == '__main__':
    unittest.main()
