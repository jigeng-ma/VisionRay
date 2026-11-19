import csv
from threading import Event
from xml.etree.ElementTree import Element, SubElement, tostring

import pytest

from studio.battery_monitor import read_home, record_samples


PACKAGE = 'com.dpvr.android.app.Occident'


def page(percent, *, name='Example Glasses', charging=False, disconnected=False, title_name=False):
    root = Element('hierarchy')
    identity = [('devices_title', name), ('home_top_bg', ''), ('devices_menu', '')] if title_name else [
        ('devices_title', 'Smart Glasses'), ('tv_device_name', name),
    ]
    for resource, text in [*identity, ('tv_battery_percent', percent)]:
        SubElement(root, 'node', {'package': PACKAGE, 'resource-id': f'{PACKAGE}:id/{resource}', 'text': text})
    if charging:
        SubElement(root, 'node', {'package': PACKAGE, 'resource-id': f'{PACKAGE}:id/iv_battery_recharge'})
    if disconnected:
        SubElement(root, 'node', {'package': PACKAGE, 'text': 'Connection failed. Try again later.'})
    return tostring(root)


def events(path):
    with path.open(encoding='utf-8-sig', newline='') as file:
        return list(csv.DictReader(file))


@pytest.mark.parametrize('title_name', [False, True])
def test_monitor_continues_after_full(tmp_path, title_name):
    def layout(percent, **kwargs):
        return page(percent, title_name=title_name, **kwargs)

    pages = [layout('83%'), layout('83%', charging=True), layout('83%', charging=True),
             layout('85%', charging=True), layout('100%', disconnected=True),
             layout('100%', name='Another Glasses'), layout('-', charging=True),
             layout('84%', charging=True), layout('100%', charging=True),
             layout('100%'), layout('100%'), layout('100%', charging=True),
             layout('99%', charging=True), layout('100%', charging=True)]
    pending = iter(enumerate(pages, start=1))
    stop = Event()

    def read(target):
        index, source = next(pending)
        if index == len(pages):
            stop.set()
        return read_home(source, PACKAGE, target)

    output = tmp_path / 'battery.csv'
    result = record_samples(output, read, stop, lambda message: None, interval=0)

    rows = events(output)
    assert [row['事件'] for row in rows] == [
        '起始读数', '充电图标变化', '电量变化', '读数中断', '读数恢复', '电量变化', '电量变化', '已达100%',
        '充电图标变化', '充电图标变化', '电量变化', '电量变化', '已达100%', '手动停止',
    ]
    assert [(row['上一有效电量%'], row['当前电量%']) for row in rows if row['事件'] == '电量变化'] == [
        ('83', '85'), ('85', '84'), ('84', '100'), ('100', '99'), ('99', '100'),
    ]
    assert [row['详情'] for row in rows if row['事件'] == '充电图标变化'] == [
        '充电图标出现', '充电图标消失', '充电图标出现',
    ]
    assert all(row['眼镜名称'] == 'Example Glasses' for row in rows)
    assert result == '已停止监测。'


@pytest.mark.parametrize('raw', ['', '-', '101%', '1000%', '100mAh'])
def test_invalid_percents(raw):
    with pytest.raises(ValueError, match='有效眼镜电量'):
        read_home(page(raw), PACKAGE)


def test_initial_full(tmp_path):
    output = tmp_path / 'battery.csv'
    stop = Event()
    record_samples(output, lambda target: read_home(page('100％'), PACKAGE, target),
                   stop, lambda message: stop.set())
    assert [row['事件'] for row in events(output)] == ['起始读数', '已达100%', '手动停止']


def test_manual_stop_keeps_readings(tmp_path):
    output = tmp_path / 'battery.csv'
    stop = Event()
    record_samples(output, lambda target: read_home(page('50%'), PACKAGE, target),
                   stop, lambda message: stop.set())
    assert [row['事件'] for row in events(output)] == ['起始读数', '手动停止']
