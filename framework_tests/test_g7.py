import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

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

    def test_failed_variant_copies_only_recorded_video_to_case_evidence(self):
        page = object.__new__(G7Page)
        page.a = Mock(context={'phone': 'phone-1'})
        page.package = 'app.package'
        page._recorded_video_path = '/data/user/0/app.package/files/clip.mp4'
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict('os.environ', {'GLASSES_EVIDENCE_DIR': directory}), \
             patch('studio.g7.Adb') as adb, \
             patch('studio.g7.subprocess.run') as run:
            adb.return_value.executable = 'adb'
            def copy_video(command, *, stdout, **kwargs):
                stdout.write(b'video bytes')
                return Mock(returncode=0, stderr=b'')
            run.side_effect = copy_video
            self.assertIsNone(page.save_failed_video())
            self.assertEqual((Path(directory) / 'clip.mp4').read_bytes(), b'video bytes')
            run.assert_called_once()

    def test_failed_variant_without_new_video_reports_reason(self):
        page = object.__new__(G7Page)
        page.a = Mock()
        page._video_before = {1: 'old.mp4'}
        page.video_rows = Mock(return_value={1: 'old.mp4'})
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict('os.environ', {'GLASSES_EVIDENCE_DIR': directory}):
            self.assertIn('新增 0 个', page.save_failed_video())
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
