"""G5 BT 与 ISP 固件更新。"""

import pytest

from studio.errors import TestBlocked
from studio.firmware_ota import manual_update, startup_update


@pytest.mark.parametrize(
    ('firmware', 'mandatory'),
    [
        pytest.param('bluetooth', None, id='bt-manual'),
        pytest.param('isp', None, id='isp-manual'),
        pytest.param('bluetooth', True, id='bt-forced'),
        pytest.param('isp', False, id='isp-optional'),
    ],
)
def test_g5_ota(android, firmware, mandatory, record_property):
    if reason := android.context.get('skip_firmware_ota'):
        pytest.skip(reason)
    if mandatory is not None:
        android.popups.preserve.add('firmware_update')
    try:
        detail = (manual_update(android, firmware) if mandatory is None
                  else startup_update(android, firmware, mandatory))
        if detail:
            record_property('studio_detail', detail)
    except TestBlocked as exc:
        android.capture('firmware-ota-blocked')
        record_property('studio_status', 'BLOCKED')
        pytest.skip(str(exc))
    finally:
        if mandatory is not None:
            android.popups.preserve.discard('firmware_update')
