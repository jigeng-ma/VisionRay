"""独立监测 VisionRay 首页显示的眼镜充电状态。"""

import csv
from datetime import datetime
from pathlib import Path
import queue
import re
import threading
import time
from xml.etree import ElementTree


def read_home(source, package, target=None):
    """从同一份页面快照读取设备名、电量和充电图标。"""
    nodes = [node for node in ElementTree.fromstring(source).iter()
             if node.get('package') == package and node.get('displayed') != 'false']

    def by_id(name):
        return [node for node in nodes if node.get('resource-id') == f'{package}:id/{name}']

    titles = by_id('devices_title')
    if not titles:
        raise ValueError('请打开 VisionRay 首页。')
    if any(node.get('text') in ('Connection failed. Try again later.', '连接失败，请稍后再试')
           for node in nodes):
        raise ValueError('VisionRay 显示连接失败，等待眼镜重连。')
    names = [node.get('text', '').strip() for node in by_id('tv_device_name')]
    names = [name for name in names if name]
    # 新版首页将已连接眼镜的名称放在带背景的标题栏，不再渲染旧设备名控件。
    if not names and len(titles) == 1 and by_id('home_top_bg') and by_id('devices_menu'):
        title = titles[0].get('text', '').strip()
        if title:
            names = [title]
    if len(names) != 1:
        raise ValueError('请在 VisionRay 首页连接并显示一副目标眼镜。')
    name = names[0]
    if target is not None and name != target:
        raise ValueError(f'当前显示 {name}，请切回 {target}。')
    values = by_id('tv_battery_percent')
    raw = values[0].get('text', '').strip() if len(values) == 1 else ''
    percent = re.fullmatch(r'(\d{1,3})\s*[%％]', raw)
    if not percent or int(percent[1]) > 100:
        raise ValueError('等待 VisionRay 显示有效眼镜电量。')
    return name, int(percent[1]), bool(by_id('iv_battery_recharge'))


def record_samples(path, read, stop, show, phone='', interval=1.0):
    """即时保存事件，并以单调时钟安排轮询。"""
    started = time.monotonic()
    next_poll = started
    target = previous = None
    interrupted = False
    with path.open('x', encoding='utf-8-sig', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['时间', '累计秒数', '事件', '手机序列号', '眼镜名称',
                         '上一有效电量%', '当前电量%', '充电图标', '详情'])
        file.flush()

        def write(event, sample=None, detail=''):
            writer.writerow([datetime.now().astimezone().isoformat(timespec='milliseconds'),
                             f'{time.monotonic() - started:.3f}', event, phone, target,
                             previous[1] if previous else None, sample[1] if sample else None,
                             ('显示' if sample[2] else '未显示') if sample else None, detail])
            file.flush()

        while not stop.is_set():
            try:
                sample = read(target)
            except (ValueError, ElementTree.ParseError) as exc:
                if not interrupted:
                    write('读数中断', detail=str(exc))
                    interrupted = True
                show(str(exc))
            else:
                target, percent, charging = sample
                if interrupted:
                    write('读数恢复', sample)
                    interrupted = False
                if previous is None:
                    write('起始读数', sample)
                else:
                    if percent != previous[1]:
                        write('电量变化', sample)
                    if charging != previous[2]:
                        detail = '充电图标出现' if charging else '充电图标消失'
                        write('充电图标变化', sample, detail)
                if percent == 100 and (previous is None or previous[1] != 100):
                    write('已达100%', sample)
                icon = '充电图标显示' if charging else '充电图标未显示'
                show(f'{target}  {percent}%  ·  {icon}')
                previous = sample
            next_poll = max(next_poll + interval, time.monotonic())
            stop.wait(max(0, next_poll - time.monotonic()))
        write('手动停止')
        return '已停止监测。'


def monitor_phone(root, phone, path, stop, show):
    from selenium.common.exceptions import InvalidSessionIdException, WebDriverException
    from .android import Android
    from .config import catalog
    from .devices import Adb
    from .errors import WaitTimeout
    from .runner import RunLock
    from .service import start

    config = catalog(root)['common']
    package = config['package']
    android = Android({'config': config, 'phone': phone})

    def read(target):
        try:
            if android.driver is None:
                android.connect()
                # 首页动画持续运行时也允许抓取 XML，避免等待界面空闲拖慢采样。
                android.driver.update_settings({'waitForIdleTimeout': 0})
                try:
                    android.ensure_foreground()
                except WaitTimeout as exc:
                    raise ValueError('请将 VisionRay 切回前台并打开首页。') from exc
            return read_home(android.driver.page_source, package, target)
        except InvalidSessionIdException as exc:
            android.driver = None
            raise ValueError('Appium 会话已断开，等待重建。') from exc
        except WebDriverException as exc:
            message = ' '.join((exc.msg or str(exc)).split())
            raise ValueError(f'暂时无法读取 VisionRay 页面：{message[:180]}') from exc

    with RunLock(root):
        show('正在连接手机并启动 Appium…')
        Adb().preflight(phone, None, package)
        if stop.is_set():
            return '已停止监测。'
        start(root)
        try:
            return record_samples(path, read, stop, show, phone)
        finally:
            try:
                android.close()
            except WebDriverException:
                pass


def open_window(parent):
    """使用工作台已识别的手机，独立于 Excel 和用例执行入口。"""
    import tkinter as tk
    from tkinter import ttk

    if getattr(parent, 'battery_window', None) and parent.battery_window.winfo_exists():
        parent.battery_window.lift()
        return
    window = parent.battery_window = tk.Toplevel(parent)
    window.title('眼镜充电监测')
    window.resizable(True, False)
    panel = ttk.Frame(window, padding=16)
    panel.pack(fill='both', expand=True)
    devices = {label: device for label, device in parent.devices_by_label.items()
               if device.state == 'device' and label != parent.glasses.get()}
    phone = tk.StringVar(value=parent.phone.get() if parent.phone.get() in devices
                         else next(iter(devices)) if len(devices) == 1 else '')
    ttk.Label(panel, text='手机').pack(anchor='w')
    picker = ttk.Combobox(panel, textvariable=phone, values=list(devices), state='readonly', width=58)
    picker.pack(fill='x', pady=(3, 8))
    ttk.Label(panel, text='在 VisionRay 首页连接眼镜并保持亮屏。插上眼镜充电线后开始。').pack(anchor='w')
    status = tk.StringVar(value='请选择已授权的手机。' if devices else '请连接手机，在工作台刷新设备后重新打开。')
    output = tk.StringVar()
    ttk.Label(panel, textvariable=status, wraplength=460).pack(anchor='w', pady=(10, 3))
    ttk.Label(panel, textvariable=output, wraplength=460).pack(anchor='w', pady=(0, 8))
    buttons = ttk.Frame(panel)
    buttons.pack(fill='x')
    events = queue.Queue()
    stop = threading.Event()
    closing = False
    running = False

    def poll():
        nonlocal running
        while not events.empty():
            kind, message = events.get_nowait()
            status.set(message)
            if kind == 'done':
                running = False
                if closing:
                    window.destroy()
                    return
                start_button.configure(state='normal')
                stop_button.configure(state='disabled')
                picker.configure(state='readonly')
        if running:
            window.after(100, poll)

    def begin():
        nonlocal running
        if phone.get() not in devices:
            status.set('请选择已授权的手机。')
            return
        serial = devices[phone.get()].serial
        root = Path(parent.root_dir)
        path = root / 'runs' / 'battery-monitor' / datetime.now().strftime('%Y%m%d_%H%M%S_%f.csv')
        output.set(str(path))
        status.set('正在准备监测…')
        stop.clear()
        running = True
        picker.configure(state='disabled')
        start_button.configure(state='disabled')
        stop_button.configure(state='normal')

        def worker():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                result = monitor_phone(root, serial, path, stop, lambda msg: events.put(('status', msg)))
            except Exception as exc:
                result = f'监测失败：{exc}'
            events.put(('done', result))

        threading.Thread(target=worker).start()
        window.after(100, poll)

    def close():
        nonlocal closing
        if running:
            closing = True
            stop.set()
            status.set('正在结束监测并保存记录…')
        else:
            window.destroy()

    start_button = ttk.Button(buttons, text='开始监测', command=begin)
    start_button.pack(side='left')
    stop_button = ttk.Button(buttons, text='停止监测', command=stop.set, state='disabled')
    stop_button.pack(side='left', padx=6)
    window.request_close = close
    window.protocol('WM_DELETE_WINDOW', close)
