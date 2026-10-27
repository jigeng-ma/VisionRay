"""Mac 上的 iOS 环境检查与真机冒烟入口：python -m studio.ios。"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def capabilities(config):
    for key in ('udid', 'bundleId'):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f'请在 iOS 配置中填写 {key}')
    result = {'platformName': 'iOS', 'appium:automationName': 'XCUITest',
              'appium:noReset': True, 'appium:autoLaunch': False,
              'appium:newCommandTimeout': 180}
    for key in ('udid', 'bundleId', 'deviceName', 'platformVersion', 'xcodeOrgId',
                'xcodeSigningId', 'updatedWDABundleId', 'xcodeConfigFile'):
        if config.get(key):
            result['appium:' + key] = config[key]
    return result


def doctor():
    if sys.platform != 'darwin':
        raise RuntimeError('iOS 本地自动化需要 macOS、完整 Xcode 和 XCUITest 驱动。')
    for command in (['xcodebuild', '-version'], ['xcrun', 'xctrace', 'list', 'devices'],
                    ['node', '--version'], ['appium', '--version'],
                    ['appium', 'driver', 'doctor', 'xcuitest']):
        if not shutil.which(command[0]):
            raise RuntimeError(f'未安装或 PATH 中找不到 {command[0]}')
        print('\n> ' + ' '.join(command), flush=True)
        subprocess.run(command, check=True, timeout=120)
    from appium.options.ios import XCUITestOptions  # noqa: F401
    print('环境检查完成；签名与 APP 启动仍需执行 smoke 验证。')


def smoke(config, folder):
    caps = capabilities(config)
    from appium import webdriver
    from appium.options.ios import XCUITestOptions
    folder.mkdir(parents=True, exist_ok=False)
    driver = None
    try:
        driver = webdriver.Remote(config.get('appium_url', 'http://127.0.0.1:4723'),
                                  options=XCUITestOptions().load_capabilities(caps))
        if not driver.is_app_installed(config['bundleId']):
            raise RuntimeError('手机尚未安装目标 APP，请先手动安装 iOS 版本。')
        driver.activate_app(config['bundleId'])
        (folder / 'page.xml').write_text(driver.page_source, encoding='utf-8')
        if not driver.save_screenshot(str(folder / 'phone.png')):
            raise RuntimeError('保存截图失败')
        print(f'iOS 会话、APP 启动、页面读取和截图完成：{folder}')
    except Exception as exc:
        (folder / 'error.txt').write_text(str(exc), encoding='utf-8')
        raise
    finally:
        if driver is not None:
            driver.quit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('doctor', 'smoke'))
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/ios.local.json')
    args = parser.parse_args()
    try:
        if args.action == 'doctor':
            doctor()
        else:
            config = json.loads(args.config.read_text(encoding='utf-8-sig'))
            smoke(config, ROOT / 'runs' / ('ios_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid4().hex[:8]))
    except Exception as exc:
        print(f'iOS 检查失败：{exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
