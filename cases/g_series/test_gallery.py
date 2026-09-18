"""G04 媒资导入、G05 空间。缺少原表指定媒资时明确阻塞。"""
import pytest
from studio.errors import TestBlocked
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
    for expected, action in enumerate((media.take_photo, media.record_video, media.record_audio), baseline + 1):
        action()
        page.a.wait(lambda: page.pending_count_on('home') == expected, '首页待导入媒资数量更新', 30)
        page.assert_pending_counts(expected)
    return baseline + 3


def restart_app(page, adb):
    package = page.package
    phone = page.a.context['phone']
    adb.shell(phone, 'am', 'force-stop', package)
    adb.shell(phone, 'monkey', '-p', package, '-c', 'android.intent.category.LAUNCHER', '1')
    page.a.wait(lambda: page.a.driver.current_package == package, 'APP 重启后前台启动', 25)


def test_import_card_on_home_and_gallery(gallery, adb):
    def action():
        expected = prepare_three_pending_media(gallery)
        restart_app(gallery, adb)
        gallery.assert_pending_counts(expected)
    run(gallery, action)


def test_each_media_updates_import_count(gallery):
    def action():
        prepare_three_pending_media(gallery)
    run(gallery, action)


def assert_import_increment(page, surface):
    before = page.imported_totals()
    imported = page.import_from(surface)
    after = page.imported_totals()
    assert after['total'] == before['total'] + imported, (
        f'导入总数增量不符：导入前 {before["total"]}，卡片待导入 {imported}，导入后 {after["total"]}。')
    assert after['gallery'] + after['recorder'] == after['total']


def test_import_from_home(gallery):
    def action():
        assert_import_increment(gallery, 'home')
    run(gallery, action)


def test_import_from_gallery(gallery):
    def action():
        assert_import_increment(gallery, 'gallery')
    run(gallery, action)


def test_download_media(gallery):
    def action():
        gallery.open(); gallery.preview_first(); gallery.download()
    run(gallery, action)


def test_video_playback(gallery):
    def action():
        gallery.open(); gallery.preview_first(); gallery.play_pause()
    run(gallery, action)


@pytest.mark.parametrize('also_phone', [False, True])
def test_delete_media(gallery, also_phone):
    def action():
        gallery.open(); gallery.preview_first(); gallery.confirm_delete(also_phone)
    run(gallery, action)
