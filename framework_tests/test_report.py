import tempfile
import unittest
import json
from pathlib import Path

from studio.report import write_report, _brief


class ReportTests(unittest.TestCase):
    def test_assertion_message_is_shown_before_pytest_diff(self):
        detail = ("E   AssertionError: C-L_016 断言失败：注册页邮箱应为 test@example.com，实际为 <空>。\n"
                  "E   assert '' == 'test@example.com'\nE     - test@example.com")
        self.assertIn('C-L_016 断言失败', _brief(detail))

    def test_summary_and_module_counts_match_case_rows(self):
        records = [
            {'sheet': '模块 A', 'id': 'A_001', 'status': 'PASS', 'detail': ''},
            {'sheet': '模块 A', 'id': 'A_002', 'status': 'FAIL', 'detail': 'E   找不到 <按钮>'},
            {'sheet': '模块 B', 'id': 'B_001', 'status': 'SKIPPED', 'detail': 'Skipped: 前置不足'},
            {'sheet': '模块 B', 'id': 'B_002', 'status': 'NOT_IMPLEMENTED', 'detail': ''},
        ]
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'evidence' / 'VisionRay_0001').mkdir(parents=True)
            write_report(folder, 'run_1', {'config': {'model': 'G6'}, 'glasses_name': 'DPVR G6',
                                            'app_version': '1.2.42'}, records,
                         {('模块 A', 'A_001'): {'automation_id': 'VisionRay_0001'}})
            page = (folder / 'report.html').read_text(encoding='utf-8')
            self.assertIn('实际执行</span><strong>2</strong>', page)
            self.assertIn('用例总数</span><strong>4</strong>', page)
            self.assertEqual(page.count('data-module='), 4)
            self.assertIn('找不到 &lt;按钮&gt;', page)
            self.assertIn('模块汇总', page)
            self.assertIn('data-group="PENDING"', page)
            self.assertNotIn('状态分布', page)
            self.assertIn('href="evidence/VisionRay_0001/"', page)
            self.assertIn('target="_blank" onclick="return !window.open(this.href,', page)
            self.assertIn('popup=yes,width=1200,height=800', page)

    def test_unselected_modules_are_absent_from_report(self):
        records = [
            {'sheet': '已选择', 'id': 'A_001', 'status': 'PASS', 'detail': ''},
            {'sheet': '未选择', 'id': 'B_001', 'status': 'NOT_RUN', 'detail': '未选择模块'},
        ]
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'manifest.json').write_text(json.dumps({'selected': ['已选择']}), encoding='utf-8')
            write_report(folder, 'run_1', {}, records, {})
            page = (folder / 'report.html').read_text(encoding='utf-8')
            self.assertIn('用例总数</span><strong>1</strong>', page)
            self.assertEqual(page.count('data-module='), 1)
            self.assertNotIn('未选择', page)
            self.assertNotIn('B_001', page)


if __name__ == '__main__':
    unittest.main()
