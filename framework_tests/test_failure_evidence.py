from unittest.mock import Mock

from studio.devices import Adb


def test_failed_case_evidence_saves_phone_screen_and_logcat(tmp_path):
    adb = object.__new__(Adb)
    adb.run = Mock(side_effect=[b'png-bytes', '10-14 19:00:00 app error'])
    adb.evidence('phone-serial', tmp_path)
    assert (tmp_path / 'phone.png').read_bytes() == b'png-bytes'
    assert 'app error' in (tmp_path / 'phone-logcat.txt').read_text(encoding='utf-8')
    assert adb.run.call_args_list[1].args == (
        '-s', 'phone-serial', 'logcat', '-d', '-v', 'threadtime', '-t', '12000')
