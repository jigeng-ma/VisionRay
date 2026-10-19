"""账号误操作防护和清理失败可见性。"""
import json
import unittest
from unittest.mock import Mock, patch
from studio.auth import AuthPage, EMAIL, PASSWORD, ROOT, alternate_password, save_password
from studio.errors import TestBlocked, WaitTimeout


class AuthSafetyTests(unittest.TestCase):
    def page(self):
        with patch('studio.auth.VerificationMailbox'):
            page = AuthPage(Mock(context={'config': {'package': 'test'}}))
            page.mail.today_code_count.return_value = 0
            return page

    def test_alternate_account_has_own_mailbox_and_password(self):
        from studio.auth import AUTH
        alternate = next(iter(AUTH['alternate_accounts']))
        with patch('studio.auth.VerificationMailbox') as mailbox:
            page = AuthPage(Mock(context={'config': {'package': 'test'}}), account=alternate)
        self.assertEqual(page.email, alternate)
        self.assertEqual(page.password, AUTH['alternate_accounts'][alternate]['password'])
        mailbox.assert_called_once_with(ROOT, alternate)

    def test_installed_variant_uses_device_package_not_requested_version(self):
        page = self.page()
        page.a.context['phone'] = 'test-phone'
        with patch('studio.auth.Adb') as adb:
            adb.return_value.shell.return_value = 'versionName=1.2.42-debug\npkgFlags=[ DEBUGGABLE ]'
            self.assertEqual(page.installed_variant(), 'debug')
            adb.return_value.shell.return_value = 'versionName=1.2.42\npkgFlags=[ ]'
            self.assertEqual(page.installed_variant(), 'release')
            adb.return_value.shell.assert_called_with('test-phone', 'dumpsys', 'package', 'test')

    def test_foreign_account_is_never_logged_out(self):
        page = self.page()
        page.home = Mock()
        page.el = Mock(return_value=Mock(text='someone@example.com'))
        page.click = Mock()
        with self.assertRaises(TestBlocked):
            page.entry()
        page.click.assert_not_called()

    def test_switching_between_configured_accounts_logs_out_current_account(self):
        page = self.page()
        page.home = Mock()
        from studio.auth import AUTH
        alternate = next(iter(AUTH['alternate_accounts']))
        page.el = Mock(side_effect=lambda key: Mock(
            text=alternate if key == 'hint' else 'Log Out' if key == 'tv_cancel' else ''))
        page.text = Mock()
        page.click = Mock()
        page.entry()
        page.click.assert_any_call('tv_cancel')

    def test_registered_precondition_switches_from_other_test_account(self):
        page = self.page()
        page.home = Mock()
        from studio.auth import AUTH
        alternate = next(iter(AUTH['alternate_accounts']))
        page.el = Mock(side_effect=[Mock(text=alternate), Mock(text=EMAIL), Mock(text=EMAIL)])
        page.login_result = Mock(return_value='logged_in')
        page.registered()
        page.login_result.assert_called_once_with()

    def test_unregistered_account_is_created_for_registered_precondition(self):
        page = self.page()
        page.home = Mock()
        page.el = Mock(side_effect=[Mock(text='Not logged in'), Mock(text=EMAIL)])
        page.login_result = Mock(return_value='unregistered')
        page.register = Mock()
        page.registered()
        page.register.assert_called_once_with()

    def test_already_unregistered_is_not_deleted_again(self):
        page = self.page()
        page.home = Mock()
        page.el = Mock(return_value=Mock(text='Not logged in'))
        page.login_result = Mock(return_value='unregistered')
        page.delete = Mock()
        page.unregistered()
        page.delete.assert_not_called()

    def test_stale_login_display_does_not_delete_absent_account(self):
        page = self.page()
        page.home = Mock()
        page.el = Mock(return_value=Mock(text=EMAIL))
        page.login_result = Mock(return_value='unregistered')
        page.delete = Mock()
        page.unregistered()
        page.login_result.assert_called_once_with()
        page.delete.assert_not_called()

    def test_one_code_boundary_case_prepares_unregistered_account(self):
        page = self.page()
        page.home = Mock()
        page.el = Mock(return_value=Mock(text=EMAIL))
        page.login_result = Mock(return_value='logged_in')
        page.delete = Mock()
        page.prepare(37)
        page.delete.assert_called_once_with()

    def test_change_email_case_deletes_registered_account_in_precondition(self):
        page = self.page()
        page.home = Mock()
        page.el = Mock(return_value=Mock(text=EMAIL))
        page.login_result = Mock(return_value='logged_in')
        page.delete = Mock()
        page.prepare(41)
        page.delete.assert_called_once_with()

    def test_logged_in_but_changed_password_is_repaired(self):
        page = self.page()
        page.home = Mock()
        page.el = Mock(return_value=Mock(text=EMAIL))
        page.login_result = Mock(return_value='wrong_password')
        page.reset = Mock()
        page.login = Mock()
        page.registered(verify_password=True)
        page.reset.assert_called_once_with(PASSWORD)
        page.login.assert_called_once_with()

    def test_ui_only_cleanup_does_not_require_account(self):
        page = self.page()
        page.home = Mock()
        page.registered = Mock()
        page.restore()
        page.registered.assert_not_called()

    def test_prepare_failure_is_blocked_before_business_assertions(self):
        page = self.page()
        page.registered = Mock(side_effect=TimeoutError('mail unavailable'))
        with self.assertRaisesRegex(TestBlocked, '前置条件准备失败'):
            page.prepare(18)

    def test_rate_limit_detection_ignores_old_responses_and_non_json(self):
        page = self.page()
        page.a.context['phone'] = 'test-phone'
        log = '\n'.join([
            '100.1 1 2 D OKHttp : {"success":false,"message":"old"}',
            '101.1 1 2 D OKHttp : header {not-json}',
            '101.2 1 2 D OKHttp : {"success":false,"message":"请求次数过于频繁,请稍后再试"}',
            '101.3 1 2 D Other : {"success":false,"message":"unrelated"}',
        ])
        with patch('studio.auth.Adb') as adb:
            adb.return_value.shell.return_value = '123'
            adb.return_value.run.return_value = log
            self.assertIn('频繁', page.request_failure(101))

    def test_daily_code_limit_blocks_without_retry(self):
        page = self.page()
        page.a.context['phone'] = 'test-phone'
        page.a.wait = Mock(side_effect=WaitTimeout('no code page'))
        page.request_failure = Mock(return_value='Reached daily limit')
        trigger = Mock()
        with patch('studio.auth.Adb') as adb:
            adb.return_value.shell.return_value = '123'
            with self.assertRaisesRegex(TestBlocked, 'daily limit'):
                page.request_code(trigger)
        trigger.assert_called_once_with()

    def test_daily_code_limit_blocks_before_sending(self):
        page = self.page()
        page.mail.today_code_count.return_value = 50
        trigger = Mock()
        with self.assertRaisesRegex(TestBlocked, '50 条上限'):
            page.request_code(trigger)
        trigger.assert_not_called()

    def test_temporary_code_limit_does_not_retry(self):
        page = self.page()
        page.a.context['phone'] = 'test-phone'
        page.a.wait = Mock(side_effect=WaitTimeout('no code page'))
        page.request_failure = Mock(return_value='请求次数过于频繁')
        trigger = Mock()
        with patch('studio.auth.Adb') as adb:
            adb.return_value.shell.return_value = '123'
            with self.assertRaisesRegex(TestBlocked, '频繁'):
                page.request_code(trigger)
        trigger.assert_called_once_with()

    def test_resend_does_not_retry_temporary_limits(self):
        page = self.page()
        page.new_code = Mock(side_effect=TestBlocked('请求次数过于频繁'))
        page.a.wait = Mock()
        with self.assertRaisesRegex(TestBlocked, '频繁'):
            page.resend_code()
        page.new_code.assert_called_once()
        page.new_code = Mock(side_effect=TestBlocked('Reached daily limit'))
        with self.assertRaisesRegex(TestBlocked, 'daily limit'):
            page.resend_code()
        page.new_code.assert_called_once()

    def test_failed_password_recovery_is_not_swallowed(self):
        page = self.page()
        page.password_changed = True
        page.reset = Mock(side_effect=TimeoutError('mail unavailable'))
        with self.assertRaises(TimeoutError):
            page.restore()
        self.assertTrue(page.password_changed)
        page.reset.assert_called_once_with(PASSWORD)

    def test_alternate_password_differs_from_saved_password(self):
        self.assertNotEqual(alternate_password(PASSWORD), PASSWORD)

    def test_reset_persists_password_after_confirmation(self):
        page = self.page()
        page.password_page = Mock()
        page.fill = Mock()
        page.click = Mock()
        page.text = Mock()
        changed = alternate_password(PASSWORD)

        with patch('studio.auth.save_password') as save:
            page.reset(changed)

        self.assertEqual(page.password, changed)
        self.assertTrue(page.password_changed)
        save.assert_called_once_with(changed, EMAIL)

    def test_save_password_writes_auth_config(self):
        path = Mock()
        with patch('studio.auth.AUTH_PATH', path), patch(
            'studio.auth.AUTH', {'account': EMAIL, 'password': PASSWORD}
        ), patch('studio.auth.PASSWORD', PASSWORD):
            save_password('changed-password')
        self.assertEqual(json.loads(path.write_text.call_args.args[0])['password'], 'changed-password')

    def test_alternate_password_update_keeps_primary_password(self):
        path = Mock()
        alternate = 'second@example.com'
        data = {'account': EMAIL, 'password': PASSWORD,
                'alternate_accounts': {alternate: {'password': 'initial'}}}
        with patch('studio.auth.AUTH_PATH', path), patch('studio.auth.AUTH', data), patch(
            'studio.auth.EMAIL', alternate
        ), patch('studio.auth.PASSWORD', 'initial'):
            save_password('changed-password')
        saved = json.loads(path.write_text.call_args.args[0])
        self.assertEqual(saved['password'], PASSWORD)
        self.assertEqual(saved['alternate_accounts'][alternate]['password'], 'changed-password')


if __name__ == '__main__':
    unittest.main()
