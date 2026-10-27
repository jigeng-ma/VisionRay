import unittest
from pathlib import Path

from studio.config import catalog, resolve_device
from studio.runner import registry, case_applies, ordered_plan
from studio.ui import product_key, product_label


ROOT = Path(__file__).resolve().parents[1]


class MultiModelTests(unittest.TestCase):
    def test_workbench_has_four_model_groups(self):
        products = catalog(ROOT)['products']
        self.assertEqual([product_label(key) for key in products],
                         ['Nova', 'G1/G3/G6', 'G7', 'G5'])
        self.assertEqual(product_key('G1/G3/G6'), 'G系列')
        self.assertEqual(product_key('G系列'), 'G系列')  # 旧工作台保存值

    def test_g7_and_g5_names_do_not_route_to_g_series(self):
        for model in ('G7', 'G5'):
            config = resolve_device(ROOT, model, model, f'DPVR {model}_1234')
            self.assertEqual((config['product'], config['model']), (model, model))
            self.assertEqual(config['configured'], model == 'G7')

    def test_g7_rejects_another_model_name(self):
        with self.assertRaisesRegex(ValueError, 'G7 蓝牙名称'):
            resolve_device(ROOT, 'G7', 'G7', 'DPVR G1_7BAF')

    def test_g7_temporarily_reuses_shared_g_series_cases(self):
        for product in ('Nova', 'G5'):
            entries = registry(ROOT, product)
            self.assertNotIn(('G01_配对', 'PAIR_001'), entries)
        self.assertIn(('G01_配对', 'PAIR_001'), registry(ROOT, 'G系列'))
        shared = registry(ROOT, 'G7')[('G05_空间', 'Space_006')]
        self.assertTrue(case_applies(shared, {'product': 'G7', 'model': 'G7'}))
        self.assertFalse(case_applies(registry(ROOT, 'G7')[('G01_配对', 'PAIR_001')],
                                      {'product': 'G7', 'model': 'G7'}))

    def test_model_tags_filter_cases_without_changing_automation_id(self):
        item = registry(ROOT, 'G系列')[('G01_配对', 'PAIR_001')]
        self.assertEqual(item['automation_id'], 'VisionRay_0001')
        self.assertTrue(case_applies(item, {'product': 'G系列', 'model': 'G1'}))
        self.assertFalse(case_applies(item, {'product': 'G系列', 'model': 'G3'}))

    def test_consolidated_model_sheets_resolve_existing_cases(self):
        g7 = registry(ROOT, 'G7')
        self.assertEqual(g7[('G7', 'F-OTA_002')]['node'],
                         g7[('G09_固件更新', 'F-OTA_002')]['node'])
        self.assertTrue(case_applies(g7[('G7', 'F-OTA_002')],
                                     {'product': 'G7', 'model': 'G7'}))
        self.assertEqual(g7[('G7', 'PAIR_004')]['automation_id'], 'VisionRay_0145')
        self.assertIn(('APP_注册登录', 'C-L_005'), g7)
        g1 = registry(ROOT, 'G系列')
        self.assertIn(('G1_G3_G6', 'F-OTA_002'), g1)
        self.assertNotIn(('G1_G3_G6', 'PAIR_004'), g1)

    def test_consolidated_sheet_follows_excel_rows_not_legacy_module_priorities(self):
        entries = registry(ROOT, 'G7')
        cases = [{'sheet': 'G7', 'id': case_id, 'row': row} for row, case_id in
                 [(2, 'PAIR_004'), (4, 'UG_001'), (5, 'UG_002'),
                  (6, 'UG_003'), (58, 'Cam_007'), (70, 'F-OTA_001')]]
        self.assertEqual([case['id'] for case in ordered_plan(cases, ['G7'], entries)],
                         [case['id'] for case in cases])
