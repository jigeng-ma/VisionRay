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
        page = SettingsPage(android); page.ai_from_history()
        for title in ('Wake up / Exit', 'Voice Control for Glasses', 'Ask Questions', 'Visual Search / Translation'):
            page.tutorial(title)
        page.toggle_labeled(('Voice Wake-up', 'Voice Wakeup', 'Voice Wake'))
        page.choose_voice('Man'); page.choose_voice('Woman')
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


def _prepare_watermarked_photo(android):
    page = SettingsPage(android); page.capture(); page.toggle_round_trip('photo_watermark_switch'); page.on('photo_watermark_switch')
    gallery = GalleryPage(android); before = gallery.pending_count_or_zero('home')
    BleMediaCommands(android).take_photo()
    android.wait(lambda: gallery.pending_count_or_zero('home') >= before + 1, '拍照后新增待导入媒资', 60)
    gallery.import_from('home'); gallery.preview_latest('image')
    return gallery


def test_photo_watermark_download(android):
    def action():
        gallery = _prepare_watermarked_photo(android)
        gallery.assert_downloaded_image_watermark(gallery.download_and_assert_phone_added('image'))
    run(android, action)


def test_photo_watermark_share(android):
    def action():
        gallery = _prepare_watermarked_photo(android)
        gallery.share(); gallery.assert_share_sheet_watermark()
        android.driver.press_keycode(4)
        android.ensure_foreground()
    run(android, action)


def test_video_watermark(android):
    def action():
        page = SettingsPage(android); page.capture(); page.toggle_round_trip('video_watermark_switch'); page.on('video_watermark_switch')
        gallery = GalleryPage(android); before = gallery.pending_count_or_zero('home')
        BleMediaCommands(android).record_video()
        android.wait(lambda: gallery.pending_count_or_zero('home') >= before + 1, '录像后新增待导入媒资', 90)
        gallery.import_from('home'); gallery.preview_latest('video'); gallery.assert_visionray_watermark(video=True)
        gallery.action('play_btn', '播放视频'); __import__('time').sleep(2)
        gallery.action('play_btn', '暂停后抽查视频帧'); gallery.assert_visionray_watermark(video=True)
    run(android, action)


def test_auto_save_album(android):
    def action():
        page = SettingsPage(android); page.capture(); page.toggle_round_trip('auto_save_album_switch'); page.on('auto_save_album_switch')
        # 该用例验证自动保存本身，先关闭水印，避免把水印用例的结果混入判断。
        page.on('photo_watermark_switch'); page.one('photo_watermark_switch').click()
        page.on('video_watermark_switch'); page.one('video_watermark_switch').click()
        gallery = GalleryPage(android); images = gallery.phone_album_count('image'); videos = gallery.phone_album_count('video')
        command = BleMediaCommands(android); before = gallery.pending_count_or_zero('home')
        command.take_photo()
        android.wait(lambda: gallery.pending_count_or_zero('home') >= before + 1, '拍照后新增待导入媒资', 90)
        gallery.import_from('home')
        android.wait(lambda: gallery.phone_album_count('image') >= images + 1, '导入图片后手机相册自动保存图片', 90)
        before = gallery.pending_count_or_zero('home'); command.record_video()
        android.wait(lambda: gallery.pending_count_or_zero('home') >= before + 1, '录像后新增待导入媒资', 120)
        gallery.import_from('home')
        android.wait(lambda: gallery.phone_album_count('video') >= videos + 1, '导入视频后手机相册自动保存视频', 120)
    run(android, action)


def test_capture_video_duration(android):
    def action():
        page = SettingsPage(android); page.capture(); page.set_duration('video_duration', '12Min')
        gallery = GalleryPage(android); before = gallery.pending_count_or_zero('home')
        BleMediaCommands(android).record_video(duration=720)
        # 眼镜写入和导入队列较慢；每 5 分钟轮询一次，最多 20 分钟。
        for _ in range(4):
            if gallery.pending_count_or_zero('home') >= before + 1:
                break
            __import__('time').sleep(300)
        else:
            raise AssertionError('录像结束后 20 分钟内未出现新增媒资。')
        gallery.import_from('home', timeout=1200)
        gallery.assert_latest_video_duration(720, 5)
    run(android, action)


def test_system_recording_duration(android):
    def action():
        page = SettingsPage(android); page.system(); page.set_duration('recording_duration', '60Min')
        # 录制一段默认 15 秒音频，确认该眼镜设置可被实际 APP 指令使用并产生待导入媒资。
        gallery = GalleryPage(android); before = gallery.pending_count_or_zero('home')
        BleMediaCommands(android).record_audio()
        android.wait(lambda: gallery.pending_count_or_zero('home') >= before + 1,
                     '录音后 APP 显示新增待导入媒资', 60)


def test_system_restart(android):
    def action():
        page = SettingsPage(android); page.system(); page.confirm('force_restart', 'Restarted')
    run(android, action)


def test_system_factory_reset(android):
    def action():
        gallery = GalleryPage(android); before = gallery.pending_count_or_zero('home')
        BleMediaCommands(android).take_photo()
        android.wait(lambda: gallery.pending_count_or_zero('home') == before + 1,
                     '恢复出厂前拍照后 APP 媒资数量新增', 60)
        page = SettingsPage(android); page.system(); page.factory_reset()
        gallery.open_home()
        assert not gallery.import_card(), '恢复出厂并回到 APP 首页后仍显示恢复前的媒资卡片。'
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
