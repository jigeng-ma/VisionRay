import unittest
from pathlib import Path

from studio.g7 import G7Page
from studio.runner import registry, case_applies


ROOT = Path(__file__).resolve().parents[1]


class G7RegistrationTests(unittest.TestCase):
    def test_nine_g7_cases_have_unique_automation_ids_and_apply_only_to_g7(self):
        expected = {'PAIR_004', 'PAIR_005', 'H-DM_086', 'H-DM_097', 'AI_079',
                    'Cam_007', 'Cam_008', 'Cam_009', 'Cam_010'}
        entries = registry(ROOT, 'G7')
        cases = [item for item in entries.values() if item['id'] in expected]
        self.assertEqual({item['id'] for item in cases}, expected)
        self.assertEqual(len({item['automation_id'] for item in cases}), 9)
        self.assertTrue(all(case_applies(item, {'product': 'G7', 'model': 'G7'})
                            for item in cases))
        self.assertFalse(any(case_applies(item, {'product': 'G系列', 'model': 'G1'})
                             for item in cases))

    def test_recording_duration_labels_are_parsed(self):
        self.assertEqual(G7Page.seconds('30 sec'), 30)
        self.assertEqual(G7Page.seconds('1Min'), 60)
        self.assertEqual(G7Page.seconds('12分钟'), 720)


if __name__ == '__main__':
    unittest.main()
