"""Flow Nova 眼镜 Wi-Fi 连接与切换。"""

import configparser
from pathlib import Path
from xml.etree import ElementTree as ET

from .errors import TestBlocked
from .home_device import HomeDevicePage
from .devices import Adb


CONFIG = Path(__file__).resolve().parents[1] / 'configs' / 'nova_wifi.ini'


def network(key, path=CONFIG):
    parser = configparser.ConfigParser()
    if not parser.read(path, encoding='utf-8') or key not in parser:
        raise TestBlocked(f'缺少 Nova Wi-Fi 本地配置 [{key}]：请填写 configs/nova_wifi.ini。')
    ssid = parser[key].get('ssid', '').strip()
    password = parser[key].get('password', '')
    if not ssid or not password:
        raise TestBlocked(f'Nova Wi-Fi [{key}] 的 ssid 或 password 未填写。')
    return ssid, password


class NovaWifiPage:
    def __init__(self, android):
        self.a = android
        self.d = android.driver
        self.package = android.context['config']['package']

    def open(self):
        HomeDevicePage(self.a).setting('Network Settings')
        self.a.wait(lambda: self._visible('Glasses Wi-Fi'), 'Glasses Wi-Fi 入口', 15).click()
        serial = self.a.context['glasses']
        if Adb().shell(serial, 'settings', 'get', 'global', 'wifi_on').strip() == '0':
            switches = [e for e in self.d.find_elements('id', self.package + ':id/wifiSwitch')
                        if e.is_displayed()]
            if len(switches) != 1:
                raise AssertionError('Nova Wi-Fi 关闭且未找到唯一的开启开关。')
            switches[0].click()
            self.a.assert_wait(lambda: Adb().shell(serial, 'settings', 'get', 'global', 'wifi_on').strip(),
                               '1', 'Nova 眼镜 Wi-Fi 开启状态', 20)
        self.a.wait(lambda: self._visible('Available'), '可用 Wi-Fi 列表', 25)

    def _visible(self, label):
        return next((e for e in self.d.find_elements('xpath', f"//*[@text='{label}']")
                     if e.is_displayed()), None)

    def state(self, ssid):
        root = ET.fromstring(self.d.page_source)
        parents = {child: parent for parent in root.iter() for child in parent}
        names = [n for n in root.iter() if n.get('resource-id') == self.package + ':id/tvName'
                 and n.get('text') == ssid]
        if len(names) != 1:
            return None
        row = parents.get(names[0])
        return next((n.get('text') for n in row.iter()
                     if n.get('resource-id') == self.package + ':id/tvState'), None) if row is not None else None

    def connect(self, key):
        ssid, password = network(key)
        self.open()
        if self.state(ssid) == 'Connected':
            self.a.log('nova-wifi-connected', ssid)
            return ssid
        entry = self.a.wait(lambda: self._visible(ssid), f'可用 Wi-Fi {ssid}', 30)
        entry.click()
        def password_prompt():
            fields = [e for e in self.d.find_elements('id', self.package + ':id/et_psw')
                      if e.is_displayed()]
            return fields or self.state(ssid) == 'Connected'
        self.a.wait(password_prompt, f'{ssid} 密码弹窗或直接连接结果', 15,
                    handle_popups=False)
        field = [e for e in self.d.find_elements('id', self.package + ':id/et_psw') if e.is_displayed()]
        if field:
            if len(field) != 1:
                raise AssertionError(f'{ssid} 密码输入框不唯一。')
            field[0].send_keys(password)
            confirms = [e for e in self.d.find_elements('id', self.package + ':id/tv_confirm')
                        if e.is_displayed() and e.text.strip() == 'Connect']
            if len(confirms) != 1:
                raise AssertionError(f'{ssid} 连接确认按钮数量异常：{len(confirms)}。')
            confirms[0].click()
        self.a.assert_wait(lambda: self.state(ssid), 'Connected', f'{ssid} 连接状态', 90)
        self.a.log('nova-wifi-connected', ssid)
        return ssid
