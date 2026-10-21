import unittest
from unittest.mock import Mock, patch

from studio.auth import AuthPage
from studio.errors import TestBlocked


class AuthRateLimitTests(unittest.TestCase):
    def test_waits_five_minutes_then_retries_once(self):
        page = AuthPage.__new__(AuthPage)
        page.a = Mock()
        page._new_code_once = Mock(side_effect=[TestBlocked('请求次数过于频繁,请稍后再试'), '123456'])
        with patch('studio.auth.time.sleep') as sleep:
            self.assertEqual(page.new_code(Mock()), '123456')
        sleep.assert_called_once_with(300)
        self.assertEqual(page._new_code_once.call_count, 2)

    def test_second_rate_limit_is_reported_without_more_waiting(self):
        page = AuthPage.__new__(AuthPage)
        page.a = Mock()
        page._new_code_once = Mock(side_effect=TestBlocked('请求次数过于频繁,请稍后再试'))
        with patch('studio.auth.time.sleep') as sleep:
            with self.assertRaises(TestBlocked):
                page.new_code(Mock())
        sleep.assert_called_once_with(300)
        self.assertEqual(page._new_code_once.call_count, 2)


if __name__ == '__main__':
    unittest.main()
