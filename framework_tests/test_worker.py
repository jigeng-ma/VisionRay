import unittest

from studio.worker import failure_detail


class WorkerFailureDetailTests(unittest.TestCase):
    def test_assertion_message_is_visible_without_traceback(self):
        report = {'when': 'call', 'detail': (
            'cases\\g_series\\test_auth.py:536: in run_case\n'
            "E   AssertionError: C-L_078 断言失败：期望邮箱 test@example.com，实际为 <空>。\n"
            "E   assert '' == 'test@example.com'\n")}
        self.assertEqual(failure_detail(report),
                         'C-L_078 断言失败：期望邮箱 test@example.com，实际为 <空>。')

    def test_setup_error_retains_traceback(self):
        report = {'when': 'setup', 'detail': 'setup.py:10\nE   AssertionError: 配置错误'}
        self.assertEqual(failure_detail(report), report['detail'])


if __name__ == '__main__':
    unittest.main()
