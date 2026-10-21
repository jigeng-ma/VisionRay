"""G04 媒资导入、G05 空间。缺少原表指定媒资时明确阻塞。"""
import pytest
from studio.errors import TestBlocked, WaitTimeout
from studio.gallery import GalleryPage
from studio.ble_commands import BleMediaCommands


@pytest.fixture
def gallery(android):
    return GalleryPage(android)


def run(page, action):
    try:
        action()
        page.a.capture('gallery-passed')
    except TestBlocked as exc:
        page.a.capture('gallery-blocked')
        pytest.skip(str(exc))


def prepare_three_pending_media(page):
    """每种媒体各产生一条，并在每一步校验首页与空间页卡片的累加数量。"""
    media = BleMediaCommands(page.a)
    baseline = page.pending_count_or_zero('home')
    for expected, (kind, action) in enumerate((('拍照', media.take_photo), ('录像', media.record_video),
                                               ('录音', media.record_audio)), baseline + 1):
        action()
        # 新拍摄文件同步到首页通知前，首页不存在通知是正常中间状态，不能把它
        # 当成前置阻塞；出现后才做严格的跨页面数量断言。
        try:
            page.a.wait(lambda: page.pending_count_or_zero('home') == expected, '首页待导入媒资数量更新', 60)
        except WaitTimeout:
            home = page.pending_count_or_zero('home')
            gallery = page.pending_count_or_zero('gallery')
            raise AssertionError(f'{kind}后待导入媒资数量未按预期增加：期望 {expected}，'
                                 f'首页实际 {home}、空间页实际 {gallery}。') from None
        page.assert_pending_counts(expected)
    return baseline + 3


def restart_app(page):
    page.a.restart()


def test_import_card_on_home_and_gallery(gallery):
    def action():
        expected = prepare_three_pending_media(gallery)
        restart_app(gallery)
        gallery.assert_pending_counts(expected)
    run(gallery, action)


def test_each_media_updates_import_count(gallery):
    def action():
        prepare_three_pending_media(gallery)
    run(gallery, action)


def assert_import_increment(page, surface):
    # 模块单独执行时没有上一条用例留下待导入媒资，先生成可导入的三类测试数据。
    if page.pending_count_or_zero(surface) == 0:
        prepare_three_pending_media(page)
    before = page.imported_totals()
    imported = page.import_from(surface)
    after = page.imported_totals()
    assert after['total'] == before['total'] + imported, (
        f'导入总数增量不符：导入前 {before["total"]}，卡片待导入 {imported}，导入后 {after["total"]}。')
    assert after['image'] + after['video'] + after['recorder'] == after['total']


def test_import_from_home(gallery):
    def action():
        assert_import_increment(gallery, 'home')
    run(gallery, action)


def test_import_from_gallery(gallery):
    def action():
        assert_import_increment(gallery, 'gallery')
    run(gallery, action)


def prepare_new_imported_media(gallery, kind, duration=15):
    """下载验证只使用本用例新建媒资，避免历史文件已存在于手机相册。"""
    before = gallery.pending_count_or_zero('home')
    command = BleMediaCommands(gallery.a)
    if kind == 'image':
        command.take_photo()
    else:
        command.record_video(duration=duration)
    gallery.a.assert_wait(lambda: gallery.pending_count_or_zero('home'), before + 1,
                          f'BLE {"录像" if kind == "video" else "拍照"}后首页待导入媒资数量',
                          120 if kind == 'video' else 60, lambda actual, expected: actual >= expected)
    gallery.import_from('home')
    gallery.preview_latest(kind)


def test_download_image(gallery):
    def action():
        prepare_new_imported_media(gallery, 'image'); gallery.download_and_assert_phone_added('image')
    run(gallery, action)


def test_download_video(gallery):
    def action():
        prepare_new_imported_media(gallery, 'video'); gallery.download_and_assert_phone_added('video')
    run(gallery, action)


def test_video_playback(gallery):
    def action():
        prepare_new_imported_media(gallery, 'video', duration=60); gallery.play_pause()
    run(gallery, action)


def test_delete_image_from_app(gallery):
    def action():
        prepare_new_imported_media(gallery, 'image'); gallery.delete_current_and_assert_absent(False)
    run(gallery, action)


def test_delete_image_from_app_and_phone(gallery):
    def action():
        prepare_new_imported_media(gallery, 'image'); gallery.delete_current_and_assert_absent(True)
    run(gallery, action)


def test_delete_video_from_app_and_phone(gallery):
    def action():
        prepare_new_imported_media(gallery, 'video'); gallery.delete_current_and_assert_absent(True)
    run(gallery, action)


def test_delete_image_and_video_from_app_and_phone(gallery):
    def action():
        for kind in ('image', 'video'):
            prepare_new_imported_media(gallery, kind); gallery.delete_current_and_assert_absent(True)
    run(gallery, action)
