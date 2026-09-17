import pytest
from studio.errors import TestBlocked
from studio.guide import GuidePage
from studio.home_device import HomeDevicePage
from studio.pairing import PairingPage


def guarded(android, action):
    try:
        action()
    except TestBlocked as exc:
        android.capture('blocked')
        pytest.skip(str(exc))


def test_begin(android):
    guarded(android, GuidePage(android).begin)


def test_done(android):
    guarded(android, GuidePage(android).done_to_home)


def test_skip_after_rebind(android):
    def run():
        HomeDevicePage(android).unbind()
        pairing = PairingPage(android)
        pairing.options['skip_tutorial'] = True
        pairing.run()
        if not pairing.on_target_home():
            raise AssertionError('重新绑定并跳过引导后未进入目标眼镜首页。')
    guarded(android, run)
