import pytest
from studio.errors import TestBlocked
from studio.ble_commands import BleMediaCommands
from studio.gallery import GalleryPage
from studio.home_device import HomeDevicePage
from studio.settings import SettingsPage


def run(android, action):
    try:
        action()
    except TestBlocked as exc:
        android.capture('settings-blocked')
        pytest.skip(str(exc))


def test_ai_tutorial_round_trip(android):
    def action():
        page = SettingsPage(android); page.ai()
        for title in ('Wake up / Exit', 'Voice Control for Glasses', 'Ask Questions', 'Visual Search / Translation'):
            page.tutorial(title)
    run(android, action)


def ai_tutorial(android, title):
    run(android, lambda: (SettingsPage(android).ai(), SettingsPage(android).tutorial(title)))


def test_ai_wake_exit_english(android): ai_tutorial(android, 'Wake up / Exit')
def test_ai_voice_control_english(android): ai_tutorial(android, 'Voice Control for Glasses')
def test_ai_questions_english(android): ai_tutorial(android, 'Ask Questions')
def test_ai_visual_search_english(android): ai_tutorial(android, 'Visual Search / Translation')


def test_ai_voice_type(android):
    def action():
        page = SettingsPage(android); page.ai(); page.choose_voice('Man'); page.choose_voice('Woman')
    run(android, action)


def test_capture_watermarks_and_auto_save_controls(android):
    def action():
        page = SettingsPage(android); page.capture()
        for resource in ('photo_watermark_switch', 'video_watermark_switch', 'auto_save_album_switch'):
            page.on(resource)
    run(android, action)


def test_capture_video_duration(android):
    def action():
        page = SettingsPage(android); page.capture(); page.set_duration('video_duration', '12Min')
        gallery = GalleryPage(android); before = gallery.pending_count_or_zero('home')
        BleMediaCommands(android).record_video(duration=720)
        android.wait(lambda: gallery.pending_count_on('home') == before + 1, '12 分钟录像生成待导入媒资', 45)
    run(android, action)


def test_system_recording_duration(android):
    run(android, lambda: (SettingsPage(android).system(), SettingsPage(android).set_duration('recording_duration', '60Min')))


def test_system_restart(android):
    def action():
        page = SettingsPage(android); page.system(); page.confirm('force_restart', 'Restarted')
    run(android, action)


def test_system_factory_reset(android):
    def action():
        page = SettingsPage(android); page.system(); page.factory_reset()
    run(android, action)


def test_system_single_unbind(android):
    run(android, lambda: HomeDevicePage(android).unbind())


def test_system_multi_unbind(android):
    def action():
        page = HomeDevicePage(android); page.home()
        devices = [e for e in android.driver.find_elements('id', page.package + ':id/tv_device_name') if e.is_displayed()]
        if len(devices) < 2:
            raise TestBlocked('多设备解绑需要至少绑定两台眼镜。')
        page.unbind()
    run(android, action)
