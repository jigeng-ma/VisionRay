import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Device:
    serial: str
    state: str
    model: str

    @property
    def label(self):
        return f'{self.model} | {self.serial} | {self.state}'


class Adb:
    def __init__(self, executable=None):
        self.executable = executable or shutil.which('adb')
        if not self.executable:
            raise RuntimeError('未找到 adb，请安装 Android platform-tools 并加入 PATH。')

    def run(self, *args, binary=False, timeout=25):
        result = subprocess.run([self.executable, *args], capture_output=True,
                                timeout=timeout, creationflags=0x08000000 if os.name == 'nt' else 0)
        if result.returncode:
            raise RuntimeError(result.stderr.decode('utf-8', errors='replace').strip())
        return result.stdout if binary else result.stdout.decode('utf-8', errors='replace').strip()

    def devices(self):
        found = []
        for line in self.run('devices', '-l').splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and not line.startswith('*'):
                attrs = dict(p.split(':', 1) for p in parts[2:] if ':' in p)
                found.append(Device(parts[0], parts[1], attrs.get('model', '未知型号')))
        return found

    def shell(self, serial, *args):
        return self.run('-s', serial, 'shell', *args)

    def online(self, serial):
        return any(d.serial == serial and d.state == 'device' for d in self.devices())

    def preflight(self, phone, glasses, package):
        if glasses and phone == glasses:
            raise ValueError('手机与眼镜不能选择同一设备。')
        for serial in filter(None, (phone, glasses)):
            if not self.online(serial):
                raise RuntimeError(f'设备未授权或不在线：{serial}')
        if not self.shell(phone, 'pm', 'path', package).startswith('package:'):
            raise RuntimeError(f'所选手机未安装 {package}')
        return {role: {'serial': serial,
                       'model': self.shell(serial, 'getprop', 'ro.product.model'),
                       'android': self.shell(serial, 'getprop', 'ro.build.version.release'),
                       'build': self.shell(serial, 'getprop', 'ro.build.display.id')}
                for role, serial in [('phone', phone), ('glasses', glasses)] if serial}

    def evidence(self, serial, folder):
        folder.mkdir(parents=True, exist_ok=True)
        try:
            (folder / 'phone.png').write_bytes(self.run('-s', serial, 'exec-out', 'screencap', '-p', binary=True))
        except Exception as exc:
            (folder / 'capture-error.txt').write_text(str(exc), encoding='utf-8')
