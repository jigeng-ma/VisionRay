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


def environment(name):
    value = os.environ.get(name)
    if value or os.name != 'nt':
        return value
    # 已打开的工作台进程不会自动继承稍后设置的用户环境变量。
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def android_sdk(root, configured=''):
    """Find the SDK used by the workbench, including the local setup bundle."""
    root = Path(root)
    local = Path(os.environ.get('LOCALAPPDATA', '')) if os.environ.get('LOCALAPPDATA') else None
    candidates = [environment('ANDROID_SDK_ROOT'), environment('ANDROID_HOME'),
                  configured, root / '.tools' / 'android-sdk']
    if local:
        candidates.extend((local / 'Android' / 'Sdk', local / 'Android' / 'sdk'))
    adb = shutil.which('adb')
    if adb and Path(adb).parent.name.lower() == 'platform-tools':
        candidates.append(Path(adb).parent.parent)
    for candidate in candidates:
        if candidate and (Path(candidate) / 'platform-tools' / 'adb.exe').is_file():
            return str(Path(candidate).resolve())
    return None


def start(root):
    if status():
        return 'Appium 已就绪（127.0.0.1:4723）。'
    root = Path(root)
    config = json.loads((root/'configs/environment.json').read_text(encoding='utf-8'))
    sdk = android_sdk(root, config.get('android_sdk'))
    if not sdk:
        raise RuntimeError('未找到 Android SDK 的 platform-tools/adb.exe；请运行 setup_environment.cmd，'
                           '或在 configs/environment.json 的 android_sdk 填写 SDK 根目录。')
    command = shutil.which('appium.cmd') or shutil.which('appium')
    if not command:
        raise RuntimeError('未找到 Appium，请先安装 Appium 及 UiAutomator2 驱动。')
    env = os.environ.copy()
    env.update(ANDROID_HOME=sdk, ANDROID_SDK_ROOT=sdk)
    java = environment('JAVA_HOME') or config.get('java_home')
    if java and (Path(java)/'bin/java.exe').is_file():
        env['JAVA_HOME'] = java
    (root/'runs').mkdir(exist_ok=True)
    log_path = root / 'runs/appium-service.log'
    with log_path.open('a', encoding='utf-8') as log:
        process = subprocess.Popen([command, '--address', '127.0.0.1', '--port', '4723', '--log-no-colors'],
            env=env, cwd=root, stdout=log, stderr=subprocess.STDOUT,
            creationflags=0x08000000 if os.name == 'nt' else 0)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if status():
            return 'Appium 已就绪（127.0.0.1:4723）。'
        if process.poll() is not None:
            break
        time.sleep(.5)
    state = f'进程已退出（退出码 {process.returncode}）' if process.poll() is not None else '等待 90 秒仍未就绪'
    try:
        tail = [line.strip() for line in log_path.read_text(encoding='utf-8', errors='replace').splitlines() if line.strip()][-3:]
    except OSError:
        tail = []
    raise RuntimeError('Appium 未就绪：' + state + ('；服务输出：' + ' | '.join(tail) if tail else '') + '。')
