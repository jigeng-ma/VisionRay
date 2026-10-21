import time
import pytest
from studio.errors import TestBlocked, WaitTimeout
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
    android.assert_wait(lambda: gallery.pending_count_or_zero('home'), before + 1,
                        '拍照后首页待导入媒资数量', 300, lambda actual, expected: actual >= expected)
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
        gallery = GalleryPage(android)
        before, videos = gallery.pending_count_or_zero('home'), gallery.gallery_media_count()['video']
        duration = 60
        BleMediaCommands(android).record_video(duration=duration)
        try:
            android.assert_wait(lambda: gallery.pending_count_or_zero('home'), before + 1,
                                '录像后首页待导入媒资数量', duration + 180,
                                lambda actual, expected: actual >= expected)
            gallery.import_from('home', timeout=max(300, duration + 180))
            android.assert_wait(lambda: gallery.gallery_media_count()['video'], videos + 1,
                                'APP 媒资库视频数量', duration + 180,
                                lambda actual, expected: actual >= expected)
        except WaitTimeout:
            raise AssertionError(f'录像 {duration} 秒后未在预留时间内完成导入；'
                                 f'导入前视频 {videos} 个，当前 {gallery.gallery_media_count()["video"]} 个。') from None
        gallery.preview_latest('video')
        for stage in ('详情封面', '播放后暂停帧'):
            if stage == '播放后暂停帧':
                gallery.action('play_btn', '播放视频'); time.sleep(2)
                gallery.action('play_btn', '暂停后抽查视频帧')
            deadline = time.monotonic() + duration + 120
            while True:
                try:
                    gallery.assert_visionray_watermark(video=True)
                    break
                except AssertionError as error:
                    if time.monotonic() >= deadline:
                        raise AssertionError(f'视频已导入，但{stage}在 {duration + 120} 秒内'
                                             f'仍未识别到 VisionRay 水印：{error}') from None
                    time.sleep(10)
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
        android.assert_wait(lambda: gallery.pending_count_or_zero('home'), before + 1,
                            '拍照后首页待导入媒资数量', 300, lambda actual, expected: actual >= expected)
        gallery.import_from('home')
        android.assert_wait(lambda: gallery.phone_album_count('image'), images + 1,
                            '导入后手机相册图片数量', 300, lambda actual, expected: actual >= expected)
        before = gallery.pending_count_or_zero('home'); command.record_video()
        android.assert_wait(lambda: gallery.pending_count_or_zero('home'), before + 1,
                            '录像后首页待导入媒资数量', 300, lambda actual, expected: actual >= expected)
        gallery.import_from('home')
        android.assert_wait(lambda: gallery.phone_album_count('video'), videos + 1,
                            '导入后手机相册视频数量', 300, lambda actual, expected: actual >= expected)
    run(android, action)


def test_capture_video_duration(android):
    def action():
        page = SettingsPage(android); page.capture(); page.set_duration('video_duration', '12Min')
        gallery = GalleryPage(android); before = gallery.pending_count_or_zero('home')
        BleMediaCommands(android).record_video(duration=720)
        # 长录像同步和导入各按录像时长加 3 分钟等待；每 5 分钟检查一次。
        for _ in range(4):
            if gallery.pending_count_or_zero('home') >= before + 1:
                break
            if _ < 3:
                __import__('time').sleep(300)
        else:
            raise AssertionError('录像结束后 15 分钟内未出现新增媒资。')
        gallery.import_from('home', timeout=720 + 180)
        gallery.assert_latest_video_duration(720, 5)
    run(android, action)


def test_system_recording_duration(android):
    def action():
        page = SettingsPage(android); page.system(); page.set_duration('recording_duration', '60Min')
        # 录制一段默认 15 秒音频，确认该眼镜设置可被实际 APP 指令使用并产生待导入媒资。
        gallery = GalleryPage(android); before = gallery.pending_count_or_zero('home')
        BleMediaCommands(android).record_audio()
        android.assert_wait(lambda: gallery.pending_count_or_zero('home'), before + 1,
                            '录音后首页待导入媒资数量', 60, lambda actual, expected: actual >= expected)
    run(android, action)


def test_system_restart(android):
    def action():
        page = SettingsPage(android); page.system(); page.confirm('force_restart', None)
        HomeDevicePage(android).connected()
    run(android, action)


def test_system_factory_reset(android):
    def action():
        gallery = GalleryPage(android); before = gallery.pending_count_or_zero('home')
        BleMediaCommands(android).take_photo()
        android.assert_wait(lambda: gallery.pending_count_or_zero('home'), before + 1,
                            '恢复出厂前首页待导入媒资数量', 60)
        page = SettingsPage(android); page.system(); page.factory_reset()
        gallery.open_home()
        assert not gallery.import_card(), '恢复出厂并回到 APP 首页后仍显示恢复前的媒资卡片。'
    run(android, action)


def test_system_single_unbind(android):
    run(android, lambda: HomeDevicePage(android).unbind())


def test_system_multi_unbind(android):
    def action():
        page = HomeDevicePage(android)
        android.ensure_foreground()
        if android.find('pair.add'):
            raise TestBlocked('多设备解绑前置不满足：当前为 Add Device 空设备页，已绑定 0 台，至少需要 2 台。')
        page.home()
        devices = [e for e in android.driver.find_elements('id', page.package + ':id/tv_device_name') if e.is_displayed()]
        if len(devices) < 2:
            raise TestBlocked(f'多设备解绑前置不满足：当前识别到 {len(devices)} 台已绑定眼镜，至少需要 2 台。')
        page.unbind()
    run(android, action)
