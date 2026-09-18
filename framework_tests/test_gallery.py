from unittest.mock import Mock
import pytest

from studio.errors import TestBlocked
from studio.gallery import GalleryPage


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
