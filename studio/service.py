import json
import os
import signal
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


def restart_stale_sdk(root):
    """Restart a local Appium listener that inherited a deleted Android SDK path."""
    if os.name != 'nt':
        raise RuntimeError('请重启 Appium 服务并重新运行环境配置。')
    script = (
        '$c=Get-NetTCPConnection -LocalPort 4723 -State Listen -ErrorAction Stop | '
        'Where-Object {$_.LocalAddress -in @("127.0.0.1","0.0.0.0","::1")} | '
        'Select-Object -First 1; '
        'if (-not $c) {exit 2}; '
        '$p=Get-CimInstance Win32_Process -Filter ("ProcessId="+$c.OwningProcess); '
        'if (-not $p -or $p.CommandLine -notmatch "appium") {exit 3}; '
        'Write-Output $p.ProcessId'
    )
    result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', script],
                            capture_output=True, text=True, timeout=15)
    if result.returncode != 0 or not result.stdout.strip().isdigit():
        raise RuntimeError('本机 4723 端口的服务无法确认是 Appium；请关闭该服务后重试。')
    os.kill(int(result.stdout.strip()), signal.SIGTERM)
    for _ in range(30):
        if not status():
            return start(root)
        time.sleep(.5)
    raise RuntimeError('旧 Appium 服务未退出；请关闭该服务后重试。')
