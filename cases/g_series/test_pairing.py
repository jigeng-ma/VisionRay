"""对应 NovaAPP-G系列冒烟测试用例.xlsx / G01_配对。"""
import pytest
from studio.pairing import PairingPage
from studio.errors import TestBlocked


def run_pairing(android, request):
    try:
        PairingPage(android).run()
    except TestBlocked as exc:
        android.capture('blocked')
        request.node.user_properties.append(('studio_status', 'BLOCKED'))
        pytest.skip(str(exc))


def test_bind(android, request):
    run_pairing(android, request)
