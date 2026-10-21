import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cases.g_series import test_auth
from studio.errors import TestBlocked
from studio.runner import ordered_plan


class RegistrationCodeReuseTests(unittest.TestCase):
    def test_resend_feedback_is_covered_by_case_0040_without_0041(self):
        entries = json.loads((Path(__file__).parents[1] / 'cases/g_series/registry.json').read_text(encoding='utf-8'))
        self.assertTrue(any(item.get('automation_id') == 'VisionRay_0040' for item in entries))
        self.assertFalse(any(item.get('automation_id') == 'VisionRay_0041' for item in entries))
        self.assertNotIn(40, test_auth.IMPLEMENTED)

    def test_order_keeps_shared_code_cases_contiguous_then_normal_case(self):
        entries = json.loads((Path(__file__).parents[1] / 'cases/g_series/registry.json').read_text(encoding='utf-8'))
        entries = {(item['sheet'], item['id']): item for item in entries}
        ids = [24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 38, 42, 43, 44, 45, 49]
        cases = [{'sheet': 'G00_登录注册', 'id': f'C-L_{n:03d}', 'row': n + 1} for n in ids]
        actual = [case['id'] for case in ordered_plan(cases, ['G00_登录注册'], entries)]
        self.assertEqual(actual[:14], [f'C-L_{n:03d}' for n in (24, 28, 34, 38, 29, 30, 32, 33, 31, 42, 43, 44, 45, 49)])
        self.assertEqual(entries[('G00_登录注册', 'C-L_049')]['automation_id'], 'VisionRay_0047')
        self.assertEqual(
            {entries[('G00_登录注册', f'C-L_{n:03d}')]['automation_id']: n for n in (31, 32, 33)},
            {'VisionRay_0118': 32, 'VisionRay_0119': 33, 'VisionRay_0039': 31},
        )

    def test_followup_cases_do_not_open_a_new_code_page(self):
        page = Mock()
        with patch.object(test_auth, 'check_code'):
            for number in (28, 34, 38, 29, 30, 32, 33):
                test_auth.run_case(page, number, '123456')
        page.code_page.assert_not_called()

    def test_password_page_checks_follow_0039_without_new_email(self):
        page = Mock()
        page.has.return_value = True
        password_button = Mock()
        password_button.is_enabled.side_effect = [False, True]
        page.el.side_effect = lambda key: password_button if key == 'tv_pwd_ok' else Mock(
            text={'tv_input_email_sub_title': 'Minimum 6 characters',
                  'tv_privacy': 'User Agreement Privacy Policy'}.get(key, ''))
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'GLASSES_RUN_CONTEXT': str(Path(folder) / 'context.json')}):
                with self.assertRaisesRegex(TestBlocked, 'VisionRay_0039'):
                    test_auth.continue_password_page(page, 42)
                test_auth.password_page_file().write_text(json.dumps({'account': test_auth.EMAIL, 'last_case': 31}))
                test_auth.continue_password_page(page, 42)
                test_auth.run_case(page, 42)
                test_auth.password_page_file().write_text(json.dumps({'account': test_auth.EMAIL, 'last_case': 42}))
                test_auth.continue_password_page(page, 43)
                test_auth.run_case(page, 43)
                test_auth.password_page_file().write_text(json.dumps({'account': test_auth.EMAIL, 'last_case': 43}))
                test_auth.continue_password_page(page, 44)
                test_auth.run_case(page, 44)
                test_auth.password_page_file().write_text(json.dumps({'account': test_auth.EMAIL, 'last_case': 44}))
                test_auth.continue_password_page(page, 45)
                test_auth.run_case(page, 45)
                test_auth.password_page_file().write_text(json.dumps({'account': test_auth.EMAIL, 'last_case': 45}))
                test_auth.continue_password_page(page, 49)
                test_auth.run_case(page, 49)
        page.code_page.assert_not_called()
        page.verify.assert_not_called()
        page.resend_code.assert_not_called()
        page.complete_registration.assert_called_once_with()

    def test_resend_reads_and_shares_fresh_code(self):
        page = Mock()
        page.el.return_value.text = test_auth.EMAIL
        page.has.return_value = True
        page.resend_code.return_value = '654321'
        self.assertEqual(test_auth.run_case(page, 34, '123456'), '654321')
        page.resend_code.assert_called_once_with()
        with tempfile.TemporaryDirectory() as folder:
            context = str(Path(folder) / 'context.json')
            with patch.dict(os.environ, {'GLASSES_RUN_CONTEXT': context}):
                test_auth.save_shared_code('123456', 24)
                test_auth.save_shared_code('123456', 28)
                test_auth.save_shared_code('654321', 34, old_code='123456')
                self.assertEqual(json.loads(test_auth.shared_code_file().read_text())['old_code'], '123456')
                self.assertEqual(test_auth.load_shared_code(page, 38), '654321')
                self.assertEqual(test_auth.load_pre_resend_code(), '123456')
                test_auth.save_shared_code('654321', 38)
                self.assertEqual(test_auth.load_shared_code(page, 29), '654321')

    def test_0123_uses_password_page_left_by_0046_without_another_code(self):
        entries = json.loads((Path(__file__).parents[1] / 'cases/g_series/registry.json').read_text(encoding='utf-8'))
        mapped = {item.get('automation_id'): item for item in entries}
        self.assertEqual(mapped['VisionRay_0046']['execution_order'] + 1,
                         mapped['VisionRay_0123']['execution_order'])
        page = Mock()
        page.has.return_value = True
        page.code_page.return_value = '123456'
        page.value.side_effect = ['a' * 30, 'a' * 30, '']
        page.el.return_value.is_enabled.return_value = True
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'GLASSES_RUN_CONTEXT': str(Path(folder) / 'context.json')}):
                test_auth.run_case(page, 46)
                page.fill.assert_any_call('et_pwd', '')
                test_auth.password_page_file().write_text(json.dumps({'account': test_auth.EMAIL, 'last_case': 46}))
                test_auth.continue_password_page(page, 47)
                test_auth.run_case(page, 47)
        page.code_page.assert_called_once_with('register')
        page.complete_registration.assert_called_once_with('Qa1!z9')
        page.login.assert_called_once_with('Qa1!z9')
        page.reset.assert_not_called()

    def test_reset_password_cases_share_one_email_and_finish_on_076(self):
        entries = json.loads((Path(__file__).parents[1] / 'cases/g_series/registry.json').read_text(encoding='utf-8'))
        mapped = {item['id']: item for item in entries if item.get('sheet') == 'G00_登录注册'}
        self.assertEqual(mapped['C-L_075']['automation_id'], 'VisionRay_0144')
        cases = [{'sheet': 'G00_登录注册', 'id': f'C-L_{n:03d}', 'row': n + 1}
                 for n in (72, 73, 74, 75, 76)]
        plan = ordered_plan(cases, ['G00_登录注册'], {('G00_登录注册', key): value for key, value in mapped.items()})
        self.assertEqual([mapped[case['id']]['automation_id'] for case in plan],
                         ['VisionRay_0060', 'VisionRay_0061', 'VisionRay_0062', 'VisionRay_0144', 'VisionRay_0063'])
        page = Mock()
        page.has.return_value = True
        page.value.side_effect = ['a' * 30, 'a' * 30]
        button = Mock()
        button.is_enabled.side_effect = [False, True]
        page.el.side_effect = lambda key: Mock(text='Minimum 6 characters') if key == 'tv_input_email_sub_title' else button
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'GLASSES_RUN_CONTEXT': str(Path(folder) / 'context.json')}):
                with self.assertRaisesRegex(TestBlocked, 'VisionRay_0060'):
                    test_auth.continue_reset_password_page(page, 73)
                for number in (72, 73, 74, 75, 76):
                    if number != 72:
                        test_auth.continue_reset_password_page(page, number)
                    test_auth.run_case(page, number)
                    if number != 76:
                        test_auth.reset_password_page_file().write_text(json.dumps({
                            'account': test_auth.EMAIL, 'last_case': number}))
                with self.assertRaisesRegex(TestBlocked, '同一邮箱|紧接'):
                    test_auth.continue_reset_password_page(page, 75)
        page.password_page.assert_called_once_with('reset')
        page.code_page.assert_not_called()
        page.reset.assert_not_called()
        page.complete_password_reset.assert_called_once_with(test_auth.TEMP_PASSWORD)
        page.login.assert_called_once_with(test_auth.TEMP_PASSWORD)
        page.fill.assert_any_call('et_pwd', 'a' * 30)
        page.fill.assert_any_call('et_pwd', '')
        page.d.press_keycode.assert_any_call(30)

    def test_0065_rejects_0064_old_password_without_resetting_again(self):
        page = Mock()
        page.password = 'new-password'
        page.value.return_value = test_auth.EMAIL
        page.login_result.return_value = 'wrong_password'
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'GLASSES_RUN_CONTEXT': str(Path(folder) / 'context.json')}):
                with self.assertRaisesRegex(TestBlocked, 'VisionRay_0064'):
                    test_auth.load_previous_password(page)
                test_auth.previous_password_file().write_text(json.dumps({
                    'account': test_auth.EMAIL, 'last_case': 78,
                    'old_password': 'old-password', 'new_password': 'new-password'}))
                old_password = test_auth.load_previous_password(page)
                test_auth.run_case(page, 79, old_password)
        page.login_result.assert_called_once_with('old-password')
        page.login.assert_called_once_with('new-password')
        page.reset.assert_not_called()
        page.password_page.assert_not_called()

    def test_0064_saves_old_password_for_followup(self):
        page = Mock()
        page.password = 'old-password'
        page.value.return_value = test_auth.EMAIL
        page.complete_password_reset.side_effect = lambda _: setattr(page, 'password', 'new-password')
        marker = Mock()
        with patch.object(test_auth, 'alternate_password', return_value='new-password'), patch.object(
            test_auth, 'previous_password_file', return_value=marker
        ):
            old_password = test_auth.run_case(page, 78)
        self.assertEqual(old_password, 'old-password')
        saved = json.loads(marker.write_text.call_args.args[0])
        self.assertEqual((saved['old_password'], saved['new_password']), ('old-password', 'new-password'))
        page.password_page.assert_called_once_with('reset')
        page.complete_password_reset.assert_called_once_with('new-password')
        page.login.assert_called_once_with('new-password')
        page.reset.assert_not_called()

    def test_0073_cancels_0072_verification_page_without_resending(self):
        page = Mock()
        page.has.return_value = True
        page.el.side_effect = lambda key: Mock(text=test_auth.EMAIL if key in ('tv_summary', 'tv_email') else '')
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'GLASSES_RUN_CONTEXT': str(Path(folder) / 'context.json')}):
                with self.assertRaisesRegex(TestBlocked, 'VisionRay_0072'):
                    test_auth.continue_delete_verification_page(page)
                test_auth.delete_verification_page_file().write_text(json.dumps({
                    'account': test_auth.EMAIL, 'last_case': 90}))
                test_auth.continue_delete_verification_page(page)
                test_auth.run_case(page, 91)
        page.click.assert_called_once_with('tv_cancel')
        page.start_delete_code.assert_not_called()
        page.mail.checkpoint.assert_not_called()
        page.mail.wait_for_code.assert_not_called()

    def test_0072_leaves_verification_page_for_0073(self):
        page = Mock()
        page.el.side_effect = lambda key: Mock(text='59s' if key == 'tv_retry' else test_auth.EMAIL,
                                                is_enabled=Mock(return_value=False))
        page.mail.wait_for_code.return_value = {'code': '123456'}
        test_auth.run_case(page, 90)
        page.start_delete_code.assert_called_once_with()
        page.click.assert_not_called()

    def test_0074_to_0076_share_account_state_without_repeated_deletion(self):
        entries = json.loads((Path(__file__).parents[1] / 'cases/g_series/registry.json').read_text(encoding='utf-8'))
        mapped = {item['id']: item for item in entries if item.get('sheet') == 'G00_登录注册'}
        cases = [{'sheet': 'G00_登录注册', 'id': f'C-L_{n:03d}', 'row': n}
                 for n in (93, 94, 95)]
        plan = ordered_plan(cases, ['G00_登录注册'], {('G00_登录注册', key): value for key, value in mapped.items()})
        self.assertEqual([mapped[case['id']]['automation_id'] for case in plan],
                         ['VisionRay_0074', 'VisionRay_0075', 'VisionRay_0076'])
        self.assertEqual({mapped[case['id']]['auth_account'] for case in plan}, {'test_zsb2@163.com'})
        page = Mock()
        page.password = 'current-password'
        page.el.side_effect = lambda key: Mock(text=(
            'Not logged in' if key == 'hint' else test_auth.EMAIL if key == 'tv_email' else ''))
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'GLASSES_RUN_CONTEXT': str(Path(folder) / 'context.json')}):
                with self.assertRaisesRegex(TestBlocked, 'VisionRay_0074'):
                    test_auth.continue_deleted_account_flow(page, 94)
                test_auth.run_case(page, 93)
                page.delete.assert_called_once_with()
                test_auth.deleted_account_flow_file().write_text(json.dumps({
                    'account': test_auth.EMAIL, 'last_case': 93}))
                test_auth.continue_deleted_account_flow(page, 94)
                test_auth.run_case(page, 94)
                page.delete.assert_called_once_with()
                page.register.assert_called_once_with()
                test_auth.deleted_account_flow_file().write_text(json.dumps({
                    'account': test_auth.EMAIL, 'last_case': 94}))
                page.el.side_effect = lambda key: Mock(text=test_auth.EMAIL)
                test_auth.continue_deleted_account_flow(page, 95)
                test_auth.run_case(page, 95)
        page.restart.assert_called_once_with()
        page.registered.assert_not_called()

    def test_old_code_after_resend_is_rejected_without_another_email(self):
        page = Mock()
        page.el.return_value.text = 'Incorrect verification code'
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'GLASSES_RUN_CONTEXT': str(Path(folder) / 'context.json')}):
                test_auth.save_shared_code('654321', 34, old_code='123456')
                test_auth.check_code(page, 38, '654321', 'register')
        page.enter_code.assert_called_once_with('123456')
        page.resend_code.assert_not_called()
        page.verify.assert_not_called()

    def test_shared_code_tracks_original_send_time_and_sequence(self):
        with tempfile.TemporaryDirectory() as folder:
            context = str(Path(folder) / 'context.json')
            page = Mock()
            page.has.return_value = True
            page.el.return_value.text = test_auth.EMAIL
            with patch.dict(os.environ, {'GLASSES_RUN_CONTEXT': context}):
                test_auth.save_shared_code('123456', 24)
                sent_at = json.loads(test_auth.shared_code_file().read_text())['sent_at']
                self.assertEqual(test_auth.load_shared_code(page, 28), '123456')
                test_auth.save_shared_code('123456', 28)
                self.assertEqual(json.loads(test_auth.shared_code_file().read_text())['sent_at'], sent_at)
                with self.assertRaisesRegex(TestBlocked, '紧接'):
                    test_auth.load_shared_code(page, 30)
                test_auth.clear_shared_code()
                self.assertFalse(test_auth.shared_code_file().exists())

    def test_missing_page_blocks_without_resending(self):
        with tempfile.TemporaryDirectory() as folder:
            page = Mock()
            page.has.return_value = False
            with patch.dict(os.environ, {'GLASSES_RUN_CONTEXT': str(Path(folder) / 'context.json')}):
                test_auth.save_shared_code('123456', 24)
                with self.assertRaisesRegex(TestBlocked, '页面已丢失'):
                    test_auth.load_shared_code(page, 28)
                page.request_code.assert_not_called()

    def test_boundary_case_reaches_password_page_without_extra_code(self):
        page = Mock()
        with patch('cases.g_series.test_auth.time.sleep'):
            test_auth.check_code(page, 37, '123456', 'register')
        page.verify.assert_called_once_with('123456', 'register')
        page.complete_registration.assert_not_called()
        page.delete.assert_not_called()

    def test_used_code_case_reuses_code_without_requesting_email(self):
        page = Mock()
        page.a = Mock(unsafe=True)
        page.has.side_effect = lambda key: key == 'tvDesc'
        page.el.side_effect = lambda key: Mock(text=test_auth.EMAIL if key in ('tv_summary', 'hint')
                                               else 'Incorrect verification code')
        test_auth.run_case(page, 39, '123456')
        page.start_delete_code.assert_called_once_with()
        page.enter_code.assert_called_once_with('123456')
        page.code_page.assert_not_called()
        page.resend_code.assert_not_called()
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'GLASSES_RUN_CONTEXT': str(Path(folder) / 'context.json')}):
                test_auth.save_used_code('123456', test_auth.time.time())
                self.assertEqual(test_auth.load_used_code(), '123456')

    def test_used_code_case_fails_if_delete_accepts_old_code(self):
        page = Mock()
        page.a = Mock(unsafe=True)
        page.has.side_effect = lambda key: key == 'tabIcon'
        page.el.return_value.text = test_auth.EMAIL
        with self.assertRaisesRegex(AssertionError, '账号已注销'):
            test_auth.run_case(page, 39, '123456')
        page.start_delete_code.assert_called_once_with()
        page.code_page.assert_not_called()
        page.resend_code.assert_not_called()

    def test_change_email_uses_two_distinct_mailboxes_without_registration_cleanup(self):
        page = Mock()
        new_email = test_auth.AUTH['account']
        old_email = next(iter(test_auth.AUTH['alternate_accounts']))
        page.new_code.return_value = '123456'
        page.el.return_value.text = new_email
        with patch.object(test_auth, 'EMAIL', old_email):
            test_auth.run_case(page, 41)
        self.assertEqual(page.mail.account, new_email)
        page.fill.assert_called_once_with('et_email', new_email)
        page.click.assert_any_call('tv_update_email_address')
        page.click.assert_any_call('back_iv')
        page.complete_registration.assert_not_called()
        page.delete.assert_not_called()


if __name__ == '__main__':
    unittest.main()
