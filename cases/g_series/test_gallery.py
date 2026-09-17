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


def test_import_card_on_gallery(gallery):
    def action():
        gallery.open()
        gallery.require_import_card()
    run(gallery, action)


def test_photo_creates_import_card(gallery):
    def action():
        BleMediaCommands(gallery.a).take_photo()
        gallery.open()
        gallery.a.wait(gallery.import_card, '拍照后待导入媒资卡片', 30)
    run(gallery, action)


def test_import_media(gallery):
    def action():
        gallery.open()
        _, button = gallery.require_import_card()
        button.click()
        gallery.a.wait(lambda: not gallery.import_card(), '导入完成', 120)
        gallery.media()
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
