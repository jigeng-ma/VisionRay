import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request


def status():
    try:
        with urllib.request.urlopen('http://127.0.0.1:4723/status', timeout=2) as response:
            return bool(json.load(response).get('value', {}).get('ready'))
    except Exception:
        return False


def start(root):
    if status():
        return 'Appium 已就绪（127.0.0.1:4723）。'
    root = Path(root)
    config = json.loads((root/'configs/environment.json').read_text(encoding='utf-8'))
    sdk = config.get('android_sdk') or os.environ.get('ANDROID_HOME', '')
    if not (Path(sdk)/'platform-tools/adb.exe').exists():
        raise RuntimeError('Android SDK 未配置，请修改 configs/environment.json 中的 android_sdk。')
    command = shutil.which('appium.cmd') or shutil.which('appium')
    if not command:
        raise RuntimeError('未找到 Appium，请先安装 Appium 及 UiAutomator2 驱动。')
    env = os.environ.copy()
    env.update(ANDROID_HOME=sdk, ANDROID_SDK_ROOT=sdk)
    if config.get('java_home'):
        env['JAVA_HOME'] = config['java_home']
    (root/'runs').mkdir(exist_ok=True)
    with (root/'runs/appium-service.log').open('a', encoding='utf-8') as log:
        process = subprocess.Popen([command, '--address', '127.0.0.1', '--port', '4723', '--log-no-colors'],
            env=env, cwd=root, stdout=log, stderr=subprocess.STDOUT,
            creationflags=0x08000000 if os.name == 'nt' else 0)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if status():
            return 'Appium 已就绪（127.0.0.1:4723）。'
        if process.poll() is not None:
            break
        time.sleep(.5)
    raise RuntimeError('Appium 未就绪，请查看 runs/appium-service.log。')
