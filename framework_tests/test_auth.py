"""账号误操作防护和清理失败可见性。"""
import unittest
from unittest.mock import Mock, patch
from studio.auth import AuthPage, EMAIL, PASSWORD
from studio.errors import TestBlocked, WaitTimeout


class AuthSafetyTests(unittest.TestCase):
    def page(self):
        with patch('studio.auth.VerificationMailbox'):
            return AuthPage(Mock(context={'config': {'package': 'test'}}))

    def test_foreign_account_is_never_logged_out(self):
        page = self.page()
        page.home = Mock()
        page.el = Mock(return_value=Mock(text='someone@example.com'))
        page.click = Mock()
        with self.assertRaises(TestBlocked):
            page.entry()
        page.click.assert_not_called()

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

    def test_temporary_code_limit_retries_then_requires_code_page(self):
        page = self.page()
        page.a.context['phone'] = 'test-phone'
        page.a.wait = Mock(side_effect=[WaitTimeout('no code page'), True])
        page.request_failure = Mock(return_value='请求次数过于频繁')
        page.has = Mock(side_effect=lambda key: key == 'et_code1')
        trigger = Mock()
        with patch('studio.auth.Adb') as adb, patch('studio.auth.time.sleep') as sleep:
            adb.return_value.shell.return_value = '123'
            page.request_code(trigger)
        self.assertEqual(trigger.call_count, 2)
        sleep.assert_called_once_with(65)

    def test_resend_retries_only_temporary_limits(self):
        page = self.page()
        page.new_code = Mock(side_effect=[TestBlocked('请求次数过于频繁'), '123456'])
        with patch('studio.auth.time.sleep') as sleep:
            self.assertEqual(page.resend_code(), '123456')
        self.assertEqual(page.new_code.call_count, 2)
        sleep.assert_called_once_with(65)
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


if __name__ == '__main__':
    unittest.main()
