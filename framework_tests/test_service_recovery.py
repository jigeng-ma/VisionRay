import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from studio.service import restart_stale_sdk


class StaleSdkRecoveryTests(unittest.TestCase):
    @patch('studio.service.start', return_value='ready')
    @patch('studio.service.time.sleep')
    @patch('studio.service.status', return_value=False)
    @patch('studio.service.os.kill')
    @patch('studio.service.subprocess.run', return_value=CompletedProcess([], 0, '1234\n', ''))
    def test_restarts_verified_local_appium(self, run, kill, status, sleep, start):
        with patch('studio.service.os.name', 'nt'):
            self.assertEqual(restart_stale_sdk(Path('C:/VisionRay')), 'ready')
        kill.assert_called_once()
        start.assert_called_once()

    @patch('studio.service.os.kill')
    @patch('studio.service.subprocess.run', return_value=CompletedProcess([], 3, '', ''))
    def test_does_not_stop_unverified_listener(self, run, kill):
        with patch('studio.service.os.name', 'nt'):
            with self.assertRaisesRegex(RuntimeError, '无法确认是 Appium'):
                restart_stale_sdk(Path('C:/VisionRay'))
        kill.assert_not_called()
