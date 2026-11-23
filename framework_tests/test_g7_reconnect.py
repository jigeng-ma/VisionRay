import pytest

from cases.g_series.test_g7_smoke_reconnect import qc_reconnection


TARGET = 'E5:74:FC:34:CC:2A'


@pytest.mark.parametrize('address,pid,since,tail,expected', [
    (TARGET, '14911', 100, '', (101.129, 2, 0)),
    ('00:00:FC:34:CC:2A', '14911', 100, '', None),
    (TARGET, '99999', 100, '', None),
    (TARGET, '14911', 101.128, '', None),
    (TARGET, '14911', 100, '102.000 14911 19643 D DPVRHelper: connectionState = DISCONNECTED', None),
])
def test_qc_reconnect_requires_success_and_full_target_address(address, pid, since, tail, expected):
    log = '\n'.join((
        '101.125 14911 14911 D QCConnection: operation=RECONNECT id=12 completion=SUCCESS',
        '101.129 14911 19643 D DPVRHelper: connectionState = CONNECTED failure = null',
        f'101.183 14911 14911 D QCSDKBleStatusReceiver: onCharacteristicChange: address={address}, uuid=test',
        tail,
    ))
    assert qc_reconnection(log, pid, TARGET, since) == expected
