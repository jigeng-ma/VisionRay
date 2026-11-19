"""空间内选中照片与视频，并验证批量下载。"""
import hashlib
import posixpath
import re
import shlex
from collections import Counter
from pathlib import PurePosixPath

from cases.g5.test_capture import file_versions
from cases.g_series.test_gallery import run
from studio.ble_commands import BleMediaCommands
from studio.devices import Adb
from studio.errors import WaitTimeout
from studio.gallery import GalleryPage


COMBINATIONS = ((1, 1), (1, 2), (2, 1), (2, 2))
ALBUM_URIS = {kind: f'content://media/external/{collection}/media'
              for kind, collection in (('image', 'images'), ('video', 'video'))}


def prepare_media(page, images, videos):
    if page.pending_count_or_zero('home'):
        page.import_from('home')
    adb = Adb()
    phone = page.a.context['phone']
    before = file_versions(adb, phone, page.package)
    command = BleMediaCommands(page.a)
    command.take_photo(images)
    page.a.assert_wait(lambda: page.pending_count_or_zero('home'), images, '新测试照片待导入', 90)
    command.record_video(count=videos)
    page.a.assert_wait(lambda: page.pending_count_or_zero('home'), images + videos, '新混合媒资待导入', 120)
    page.import_from('home')

    def imported():
        changed = {path for path, stamp in file_versions(adb, phone, page.package).items()
                   if before.get(path) != stamp}
        sources = {kind: sorted({path for path in page.imported_files(kind).values() if path and
                   'files/media/' + posixpath.normpath(path).rsplit('/files/media/', 1)[-1] in changed})
                   for kind in ALBUM_URIS}
        return sources if (len(sources['image']), len(sources['video'])) == (images, videos) else None

    return page.a.wait(imported, 'APP 中本组照片和视频文件已写入', 30)


def select_recent(page, images, videos):
    page.open()
    indexed = {'image': [], 'video': []}
    for index, tile in enumerate(page.all('cl_root')):
        if not tile.find_elements('id', page.package + ':id/iv_photo'):
            continue
        kind = 'video' if tile.find_elements('id', page.package + ':id/iv_video_icon') else 'image'
        indexed[kind].append(index)
    assert len(indexed['image']) >= images and len(indexed['video']) >= videos, '空间可见缩略图不足。'
    selected = sorted(indexed['image'][:images] + indexed['video'][:videos])
    for position, index in enumerate(selected, 1):
        tile = page.all('cl_root')[index].find_element('id', page.package + ':id/iv_photo')
        if position == 1:
            page.d.execute_script('mobile: longClickGesture', {'elementId': tile.id, 'duration': 650})
        else:
            tile.click()
        page.a.assert_wait(lambda: page.one('tv_count').text, f'{position} selected', '混合媒资选中数量', 8)


def download_selected(page):
    button = page.one('ll_download', '批量 Download')
    assert button.is_enabled() and button.text.strip() == 'Download', '批量下载按钮初始状态异常。'
    page.download()
    page.a.wait(lambda: bool(page.all('gallery_title')) and not page.all('tv_count'), '下载后退出多选', 12)


def verify_downloaded(page, sources, before):
    adb = Adb()
    phone = page.a.context['phone']
    failures = []
    for kind, paths in sources.items():
        def album_rows():
            visible = page.phone_album_rows(kind)
            added = visible - before[kind]
            linked = set()
            for path, uri in page._media_query('select path, uri from file_metadata where file_type = ?', (kind,)):
                prefix = ALBUM_URIS[kind] + '/'
                if path in paths and uri and uri.startswith(prefix) and uri[len(prefix):].isdigit():
                    linked.add(int(uri[len(prefix):]))
            return (added | (linked & visible)) if len(added | (linked & visible)) >= len(paths) else None

        ids = page.a.wait(album_rows, f'手机相册可读取本组选中的 {len(paths)} 个 {kind}', 45)
        expected = Counter()
        for path in paths:
            output = adb.shell(phone, 'run-as', page.package, 'sha256sum', shlex.quote(path))
            digest = output.split()[0]
            assert re.fullmatch(r'[a-f0-9]{64}', digest), f'无法读取 APP 源文件指纹：{path}。'
            expected[digest] += 1
        actual = Counter()
        for media_id in ids:
            part = adb.run('-s', phone, 'exec-out', 'content', 'read', '--uri',
                           f'{ALBUM_URIS[kind]}/{media_id}', binary=True, timeout=90)
            assert part, f'手机相册文件为空：{media_id}。'
            actual[hashlib.sha256(part).hexdigest()] += 1
        matched = not expected - actual
        if not matched:
            failures.append(f'{kind} 相册文件与 APP 源文件不一致（ID {sorted(ids)}）')
        page.a.log('mixed-download-files', {'kind': kind, 'album_ids': sorted(ids),
                   'source_files': [PurePosixPath(path).name for path in paths], 'sha256_match': matched})
    if failures:
        raise AssertionError('；'.join(failures))


def test_g5_mixed_download(android, record_property):
    def action():
        original = android.driver.get_settings()
        failures = []
        try:
            android.driver.update_settings({'enableMultiWindows': True, 'waitForIdleTimeout': 0})
            for images, videos in COMBINATIONS:
                label = f'{images} 张照片 + {videos} 段视频'
                try:
                    sources = prepare_media(page, images, videos)
                    page.require_unsaved_files([path for paths in sources.values() for path in paths])
                    before = {kind: page.phone_album_rows(kind) for kind in ALBUM_URIS}
                    select_recent(page, images, videos)
                    download_selected(page)
                    verify_downloaded(page, sources, before)
                    android.capture(f'mixed-downloaded-{images}-{videos}')
                except (AssertionError, WaitTimeout) as exc:
                    failures.append(f'{label}：{exc}')
                    android.capture(f'mixed-download-failed-{images}-{videos}')
        finally:
            android.driver.update_settings({name: original[name] for name in
                                            ('enableMultiWindows', 'waitForIdleTimeout') if name in original})
        if failures:
            record_property('studio_detail', '\n'.join(failures))
            raise AssertionError('混合下载校验失败。')
        record_property('studio_detail', '四组照片与视频均在手机相册找到，SHA-256 与 APP 源文件一致。')

    page = GalleryPage(android)
    run(page, action)
