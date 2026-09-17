import time
import json
import os
from pathlib import Path
from .errors import TestBlocked, WaitTimeout
from .popups import PopupGuard


class Android:
    def __init__(self, context):
        self.context = context
        self.driver = None
        self.popups = PopupGuard(self)
        self.capture_index = 0

    def connect(self):
        from appium import webdriver
        from appium.options.android import UiAutomator2Options
        config = self.context['config']
        self.driver = webdriver.Remote(config['appium_url'], options=UiAutomator2Options().load_capabilities({
            'platformName': 'Android', 'appium:automationName': 'UiAutomator2',
            'appium:udid': self.context['phone'], 'appium:appPackage': config['package'],
            'appium:appActivity': config['activity'], 'appium:noReset': True,
            'appium:autoLaunch': False, 'appium:newCommandTimeout': config.get('new_command_timeout', 60)}))
        if os.environ.get('GLASSES_EVIDENCE_DIR'):
            (Path(os.environ['GLASSES_EVIDENCE_DIR'])/'session.json').write_text(json.dumps({
                'url': config['appium_url'], 'session_id': self.driver.session_id}), encoding='utf-8')
        return self

    def ensure_foreground(self):
        package = self.context['config']['package']
        before = self.driver.current_package
        if before != package:
            self.log('launch-app', {'from': before, 'target': package})
            # SplashActivity 会在初始化后结束，activate_app 有时会把任务带回桌面。
            # 使用与桌面图标一致的启动器 Intent，保留当前引导/首页任务状态。
            phone = self.context.get('phone')
            if phone:
                from .devices import Adb
                Adb().shell(phone, 'monkey', '-p', package, '-c', 'android.intent.category.LAUNCHER', '1')
            else:  # 单元测试和没有设备上下文的调用保留 Appium 原生方式。
                self.driver.activate_app(package)
        self.wait(lambda: self.driver.current_package == package, '启动或切回被测 APP', 25)

    def log(self, event, detail):
        print(f'{event}: {detail}', flush=True)
        folder = os.environ.get('GLASSES_EVIDENCE_DIR')
        if folder:
            with (Path(folder)/'steps.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps({'time': time.time(), 'event': event, 'detail': detail}, ensure_ascii=False)+'\n')

    def capture(self, label):
        folder = os.environ.get('GLASSES_EVIDENCE_DIR')
        if not folder or not self.driver:
            return
        self.capture_index += 1
        path = Path(folder)/f'{self.capture_index:03d}-{label}'
        try:
            path.with_suffix('.xml').write_text(self.driver.page_source, encoding='utf-8')
            self.driver.save_screenshot(str(path.with_suffix('.png')))
        except Exception as exc:
            self.log('capture-error', str(exc))

    def find(self, key):
        spec = self.context['config']['elements'][key]
        found = [e for e in self.driver.find_elements(spec['by'], spec['value']) if e.is_displayed()]
        if len(found) > 1:
            raise AssertionError(f'元素 {key} 匹配到 {len(found)} 项，请增加定位范围。')
        return found[0] if found else None

    def wait(self, predicate, label, timeout=10):
        from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
        deadline = time.monotonic() + timeout
        handled = 0
        try:
            while time.monotonic() < deadline:
                try:
                    if self.popups.handle():
                        handled += 1
                        if handled > 6:
                            raise TestBlocked('弹窗反复出现，停止当前用例并保留现场。')
                        time.sleep(.25)
                        continue
                    result = predicate()
                    if result:
                        return result
                except (StaleElementReferenceException, WebDriverException) as exc:
                    self.log('transient-driver-error', str(exc).splitlines()[0])
                time.sleep(.3)
            raise WaitTimeout(f'等待超时：{label}（{timeout} 秒），请查看 XML 和截图。')
        except Exception:
            self.capture('wait-failed')
            raise

    def element(self, key, timeout=10):
        return self.wait(lambda: self.find(key), key, timeout)

    def click(self, key, timeout=10):
        from selenium.common.exceptions import StaleElementReferenceException
        for attempt in range(2):
            try:
                self.element(key, timeout).click()
                self.log('click', key)
                return
            except StaleElementReferenceException:
                if attempt:
                    raise

    def close(self):
        if self.driver:
            self.driver.quit()
