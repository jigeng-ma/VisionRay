from unittest.mock import Mock, patch
import pytest

from studio.errors import TestBlocked, WaitTimeout
from studio.gallery import GalleryPage
from cases.g_series.test_gallery import prepare_three_pending_media


def test_missing_count_after_photo_reports_actual_counts():
    page = Mock()
    page.pending_count_or_zero.side_effect = lambda surface: 3
    page.a.wait.side_effect = WaitTimeout('等待超时')
    with patch('cases.g_series.test_gallery.BleMediaCommands'):
        with pytest.raises(AssertionError, match='拍照后待导入媒资数量未按预期增加：期望 4，首页实际 3、空间页实际 3'):
            prepare_three_pending_media(page)


def test_cam003_reports_missing_watermark_after_processing_window():
    from cases.g_series.test_settings import test_video_watermark
    android, gallery = Mock(unsafe=True), Mock(spec=GalleryPage)
    gallery.pending_count_or_zero.return_value = 0
    gallery.gallery_media_count.return_value = {'video': 1}
    gallery.assert_visionray_watermark.side_effect = AssertionError('OCR 未识别')
    with patch('cases.g_series.test_settings.SettingsPage'), \
         patch('cases.g_series.test_settings.GalleryPage', return_value=gallery), \
         patch('cases.g_series.test_settings.BleMediaCommands'), \
         patch('cases.g_series.test_settings.time.monotonic', side_effect=[0, 181]), \
         patch('cases.g_series.test_settings.time.sleep'):
        with pytest.raises(AssertionError, match='视频已导入，但详情封面在 180 秒内仍未识别到 VisionRay 水印'):
            test_video_watermark(android)


def test_missing_import_notice_after_preparation_is_failure():
    page = object.__new__(GalleryPage)
    page.pending_count_or_zero = Mock(return_value=0)
    with pytest.raises(AssertionError, match='期望 3，实际 0'):
        page.assert_pending_counts(3)


def page_with_card(*texts):
    page = object.__new__(GalleryPage)
    card = Mock(text='')
    card.find_elements.return_value = [Mock(text=text) for text in texts]
    page.require_import_card = Mock(return_value=(card, Mock()))
    return page


def test_import_count_reads_card_number():
    assert page_with_card('3 files ready to import').import_count() == 3


def test_import_count_blocks_when_card_has_no_unique_number():
    with pytest.raises(TestBlocked, match='无法从待导入卡片唯一解析'):
        page_with_card('Import 2 of 3 files').import_count()


def test_unscrolled_media_count_refuses_partial_list():
    page = object.__new__(GalleryPage)
    page.one = Mock(return_value=Mock(get_attribute=Mock(return_value='true')))
    with pytest.raises(TestBlocked, match='可滚动'):
        page._unscrolled_count('list', 'item', '媒资列表')


def test_gallery_count_uses_media_database():
    page = object.__new__(GalleryPage)
    page.open = Mock()
    page._media_counts_from_database = Mock(return_value={'image': 3, 'video': 1, 'audio': 2})
    assert page.gallery_media_count() == {'image': 3, 'video': 1, 'total': 4}
