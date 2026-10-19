import unittest

from studio.ui import brief_detail


class FeedbackTests(unittest.TestCase):
    def test_brief_detail_keeps_one_readable_line(self):
        self.assertEqual(brief_detail('Appium\n未就绪'), 'Appium 未就绪')

    def test_brief_detail_truncates_without_losing_the_cause_prefix(self):
        result = brief_detail('Appium 未就绪：' + 'x' * 300, 24)
        self.assertEqual(result, 'Appium 未就绪：' + 'x' * 12 + '…')


if __name__ == '__main__':
    unittest.main()
