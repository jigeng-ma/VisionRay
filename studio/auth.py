"""G00 英文版账号流程。只允许操作用户指定的可销毁测试账号。"""
import re
import json
import os
import time
from pathlib import Path

from .devices import Adb
from .errors import TestBlocked, WaitTimeout
from .mailbox import VerificationMailbox

ROOT = Path(__file__).resolve().parents[1]
AUTH_PATH = ROOT / 'configs' / 'auth_private.json'
AUTH = json.loads(AUTH_PATH.read_text(encoding='utf-8'))
EMAIL = os.environ.get('VISIONRAY_TEST_ACCOUNT', AUTH['account'])
KNOWN_ACCOUNTS = {AUTH['account'], *AUTH.get('alternate_accounts', {})}
if EMAIL not in KNOWN_ACCOUNTS:
    raise ValueError(f'未配置测试账号：{EMAIL}')
PASSWORD = (AUTH['password'] if EMAIL == AUTH['account']
            else AUTH['alternate_accounts'][EMAIL]['password'])


def alternate_password(password):
    return 'NovaQA9!z' if password != 'NovaQA9!z' else 'VisionRay9!z'


def save_password(password, account=None):
    global PASSWORD
    account = account or EMAIL
    if account == AUTH['account']:
        AUTH['password'] = password
    else:
        AUTH['alternate_accounts'][account]['password'] = password
    if account == EMAIL:
        PASSWORD = password
    AUTH_PATH.write_text(json.dumps(AUTH, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


class AuthPage:
    def __init__(self, android, account=None):
        self.a = android
        self.d = android.driver
        self.package = android.context['config']['package']
        self.email = account or EMAIL
        if self.email not in KNOWN_ACCOUNTS:
            raise ValueError(f'未配置测试账号：{self.email}')
        self.mail = VerificationMailbox(ROOT, self.email)
        self.original_password = (AUTH['password'] if self.email == AUTH['account']
                                  else AUTH['alternate_accounts'][self.email]['password'])
        self.password = self.original_password
        self.password_changed = False
        self.keep_code_page = False

    def installed_variant(self):
        """读取手机当前安装包，避免把工作台输入的 debug 版本误当作实际安装版本。"""
        dump = Adb().shell(self.a.context['phone'], 'dumpsys', 'package', self.package)
        version = re.search(r'\bversionName=([^\s]+)', dump)
        if version and version.group(1).lower().endswith('-debug'):
            return 'debug'
        if re.search(r'\b(?:pkgFlags|flags)=\[[^\]]*\bDEBUGGABLE\b', dump):
            return 'debug'
        return 'release' if version else 'unknown'

    def all(self, resource):
        return [e for e in self.d.find_elements('id', self.package + ':id/' + resource) if e.is_displayed()]

    def has(self, resource):
        return bool(self.all(resource))

    def el(self, resource):
        def one():
            found = self.all(resource)
            assert len(found) <= 1, f'{resource} 匹配不唯一'
            return found[0] if found else None
        return self.a.wait(one, resource, 15)

    def click(self, resource):
        self.el(resource).click()

    def hide_keyboard(self):
        if self.d.is_keyboard_shown():
            self.d.hide_keyboard()
            self.a.wait(lambda: not self.d.is_keyboard_shown(), '键盘已收起', 5)
        self.settle()

    def text(self, value):
        return self.a.wait(lambda: next((e for e in self.d.find_elements('xpath',
            f'//*[@package="{self.package}" and @text="{value}"]') if e.is_displayed()), None), value, 20)

    def fill(self, resource, value):
        field = self.el(resource)
        field.clear()
        if value:
            field.send_keys(value)
        self.hide_keyboard()

    def disabled_login_stays_here(self):
        """空值、非法邮箱等本地校验：按钮不可用且等待后仍留在登录页。"""
        button = self.el('tv_login_btn')
        assert not button.is_enabled(), '不合法登录输入时 Log in 应置灰'
        button.click()
        time.sleep(3)
        self.text('Log in Your Account')
        assert not self.has('tabIcon'), '不合法登录输入意外进入已登录页'

    def click_privacy_link(self, label):
        """兼容协议文本未单独暴露为 UI 节点的版本。"""
        links = [e for e in self.d.find_elements('xpath', f'//*[@package="{self.package}" and @text="{label}"]')
                 if e.is_displayed()]
        if len(links) == 1:
            links[0].click()
            return
        text = self.el('tv_privacy')
        content = text.text
        start = content.find(label)
        if start < 0:
            raise TestBlocked(f'登录页未显示协议链接：{label}')
        rect = text.rect
        # 文本链接没有独立资源 ID 时，按链接在整行中的字符位置点击。
        x = int(rect['x'] + rect['width'] * (start + len(label) / 2) / len(content))
        y = int(rect['y'] + rect['height'] / 2)
        self.d.execute_script('mobile: clickGesture', {'x': x, 'y': y})

    def assert_page_title(self, title):
        def visible_privacy_page():
            # 协议页由系统浏览器承载时，不属于 App package；页面地址仍可作为加载成功信号。
            return any(e.is_displayed() and (
                title.lower() in e.text.lower() or 'rs.dpaiglasses.com' in e.text.lower()
            ) for e in self.d.find_elements('xpath', '//*[@text]'))

        self.a.wait(visible_privacy_page, title + ' 页面标题', 20)

    def no_new_mail(self, checkpoint):
        time.sleep(3)
        latest = self.mail.checkpoint()
        assert latest['uid'] == checkpoint['uid'], '本不应发送验证码，但邮箱收到了新邮件'

    def value(self, resource):
        field = self.el(resource)
        value = field.text
        return '' if value == field.get_attribute('hint') else value

    def settle(self):
        time.sleep(.8)

    def leave_pending_guide(self):
        """恢复上轮遗留的使用引导，保证账号流程从可导航页面开始。"""
        if self.a.find('pair.skip_title'):
            self.a.click('pair.skip_confirm')
            self.a.wait(lambda: self.has('tabIcon'), '确认跳过引导后主页面', 15)
        elif self.a.find('pair.tutorial_begin'):
            self.a.click('pair.skip')
            self.a.element('pair.skip_title')
            self.a.click('pair.skip_confirm')
            self.a.wait(lambda: self.has('tabIcon'), '跳过引导后主页面', 15)

    def home(self):
        self.a.ensure_foreground()
        from .firmware_ota import leave_failed_update
        leave_failed_update(self.a)
        self.leave_pending_guide()
        self.a.wait(lambda: any(self.has(k) for k in ('tabIcon', 'tv_login_by_email',
            'back_iv', 'tv_cancel')), '账号流程页面加载完成', 25)
        for _ in range(9):
            self.leave_pending_guide()
            if self.has('tv_login_by_email'):
                self.click('tv_skip')
                self.a.wait(lambda: self.has('tabIcon'), 'Skip 后主页面', 15)
            tabs = self.all('tabIcon')
            if tabs:
                tabs[-1].click()
                self.text('Account')
                return
            if self.d.is_keyboard_shown():
                self.d.hide_keyboard()
            else:
                self.d.back()
            self.settle()
            self.a.wait(lambda: any(self.has(k) for k in ('tabIcon', 'tv_login_by_email',
                'back_iv', 'tv_cancel')), '返回上一页面', 15)
        raise TestBlocked('无法返回 My；请检查是否停留在配对或首次引导。')

    def account(self):
        self.home()
        hint = self.el('hint').text
        if hint != self.email:
            raise TestBlocked(f'当前账号不是指定测试邮箱：{hint}；不操作其他账号。')
        self.text('Account').click()
        assert self.el('tv_email').text == self.email

    def entry(self):
        self.home()
        hint = self.el('hint').text
        if hint in KNOWN_ACCOUNTS:
            self.text('Account').click()
            self.click('tv_logout')
            # 退出确认框左右按钮的 resource-id 与语义相反，必须同时核对文案。
            assert self.el('tv_cancel').text == 'Log Out'
            self.click('tv_cancel')
        elif hint == 'Not logged in':
            self.text('Account').click()
        else:
            raise TestBlocked('当前登录的是其他账号，不自动退出。')
        self.el('tv_login_by_email')

    def login_page(self):
        self.entry()
        self.click('tv_login_by_email')
        self.text('Log in Your Account')
        self.hide_keyboard()

    def login_result(self, password=None):
        """探测服务端账号状态，不把未注册或密码错误误记为导航超时。"""
        password = self.password if password is None else password
        self.login_page()
        self.fill('et_email', self.email)
        self.fill('et_pwd', password)
        self.click('tv_login_btn')
        def result():
            if self.has('tabIcon'):
                return 'logged_in'
            titles = self.all('tv_title')
            if titles and titles[0].text in ('Not registered', 'Login Failed'):
                return {'Not registered': 'unregistered', 'Login Failed': 'wrong_password'}[titles[0].text]
            return None
        return self.a.wait(result, '登录成功或明确账号状态', 25)

    def login(self, password=None):
        password = self.password if password is None else password
        result = self.login_result(password)
        assert result == 'logged_in', f'登录未成功：{result}'
        self.home()
        assert self.el('hint').text == self.email

    def registered(self, verify_password=False):
        self.home()
        hint = self.el('hint').text
        if hint not in (*KNOWN_ACCOUNTS, 'Not logged in'):
            raise TestBlocked('当前账号不是指定测试邮箱，不恢复其密码。')
        if hint != self.email or verify_password:
            result = self.login_result()
            self.a.log('auth-precondition', {'required': 'registered', 'observed': result})
            if result == 'unregistered':
                self.register()
            elif result == 'wrong_password':
                self.reset(self.password)
                self.login()
                self.password_changed = False
        else:
            assert self.el('hint').text == self.email, '只允许指定测试账号'
        self.home()
        assert self.el('hint').text == self.email, '准备后未登录指定测试账号'

    def unregistered(self, allow_delete=True):
        self.home()
        if self.el('hint').text not in (*KNOWN_ACCOUNTS, 'Not logged in'):
            raise TestBlocked('当前账号不是指定测试邮箱，不改变账号状态。')
        # 本地登录提示可能过期；用服务端结果决定是否还需要注销。
        result = self.login_result()
        self.a.log('auth-precondition', {'required': 'unregistered', 'observed': result})
        if result != 'unregistered':
            if not allow_delete:
                raise TestBlocked('测试账号仍已注册；本用例限制只发一封验证码，前置条件不自动注销。')
            if result == 'wrong_password':
                self.reset(self.password)
                self.login()
                self.password_changed = False
            self.delete()

    def prepare(self, number):
        self.a.log('auth-prepare', f'AUTH_{number:03d}')
        # 页面检查不依赖服务端账号；不能为检查空输入而强制登录或注册。
        neutral = {1, 3, 4, 5, 6, 11, 22, 23, 50, 51, 52, 57}
        absent = {15, 16, 17, 24, 28, 29, 30, 31, 32, 33, 34, 37, 38, 41, 42, 43, 44, 45, 46, 47, 48, 49, 55, 56}
        try:
            if number in absent:
                self.unregistered()
            elif number not in neutral:
                self.registered(verify_password=True)
            self.home()
        except (AssertionError, TimeoutError) as exc:
            self.a.capture('precondition-failed')
            raise TestBlocked(f'AUTH_{number:03d} 前置条件准备失败：{exc}') from exc

    def email_page(self, mode):
        self.login_page() if mode == 'reset' else self.entry()
        self.click('tv_forgot_pwd' if mode == 'reset' else 'tv_create_new_account')
        self.text('Find your account' if mode == 'reset' else "What's your email?")
        self.hide_keyboard()

    def new_code(self, trigger):
        checkpoint = self.mail.checkpoint()
        since = float(Adb().shell(self.a.context['phone'], 'date', '+%s'))
        trigger()
        try:
            self.el('et_code1')
            result = self.mail.wait_for_code(checkpoint)
        except TimeoutError as exc:
            self.a.capture('mail-code-unavailable')
            message = self.request_failure(since)
            raise TestBlocked(message or str(exc)) from exc
        except Exception:
            self.a.capture('mail-code-unavailable')
            raise
        assert re.fullmatch(r'\d{6}', result['code']), '邮件验证码不是6位数字'
        return result['code']

    def request_failure(self, since):
        """调试版将短暂 toast 对应的业务错误写入 OKHttp 日志；只返回错误文案。"""
        adb = Adb()
        phone = self.a.context['phone']
        pid = adb.shell(phone, 'pidof', self.package).split()[0]
        log = adb.run('-s', phone, 'logcat', '--pid=' + pid, '-d', '-v', 'epoch', '-t', '1500')
        messages = []
        for line in log.splitlines():
            stamp = re.match(r'\s*(\d+\.\d+)', line)
            if not stamp or float(stamp[1]) < since or 'OKHttp' not in line or '{' not in line:
                continue
            try:
                body = json.loads(line[line.index('{'):])
            except ValueError:
                continue
            if body.get('success') is False and isinstance(body.get('message'), str):
                messages.append(body['message'])
        return messages[-1] if messages else ''

    def request_code(self, trigger):
        """每个测试动作只允许一次发码，避免自动重试耗尽日配额。"""
        used = self.mail.today_code_count()
        if used >= 50:
            raise TestBlocked(f'{self.mail.account} 今日已接收 {used} 条验证码，达到每天 50 条上限。')
        since = float(Adb().shell(self.a.context['phone'], 'date', '+%s'))
        trigger()
        try:
            self.a.wait(lambda: self.has('et_code1') or self.has('tvDesc'), '发送验证码页面响应', 8)
        except WaitTimeout:
            message = self.request_failure(since)
        else:
            if self.has('et_code1'):
                return
            message = self.el('tvDesc').text
        raise TestBlocked('发送验证码被拒绝：' + (message or '未取得可确认的发送结果'))

    def code_page(self, mode):
        self.email_page(mode)
        self.fill('et_email', self.email)
        code = self.new_code(lambda: self.request_code(lambda: self.click('tv_email_next')))
        self.text('Enter your verification code')
        assert self.email in self.el('tv_summary').text
        for i in range(1, 7):
            self.el(f'et_code{i}')
        return code

    def resend_code(self):
        def trigger():
            used = self.mail.today_code_count()
            if used >= 50:
                raise TestBlocked(f'{self.mail.account} 今日已接收 {used} 条验证码，达到每天 50 条上限。')
            since = float(Adb().shell(self.a.context['phone'], 'date', '+%s'))
            self.click('tv_resend_captcha')
            self.settle()
            message = self.request_failure(since)
            if message:
                raise TestBlocked('重发验证码被拒绝：' + message)
        self.a.wait(lambda: self.el('tv_resend_captcha').is_enabled(), '允许重新发送', 75)
        return self.new_code(trigger)

    def enter_code(self, code):
        for i in range(6, 0, -1):
            self.el(f'et_code{i}').clear()
        # 每格单独填入，避免不同键盘的粘贴分发行为不一致。
        for i, digit in enumerate(code, 1):
            self.el(f'et_code{i}').send_keys(digit)
        if self.d.is_keyboard_shown():
            self.d.hide_keyboard()

    def verify(self, code, mode):
        self.enter_code(code)
        self.click('tv_captcha_next')
        self.text('Create new password' if mode == 'reset' else 'Create password')

    def password_page(self, mode):
        self.verify(self.code_page(mode), mode)

    def delete_prompt(self):
        self.registered()
        self.account()
        self.click('cl_delete_account')
        self.text('Delete Account')

    def start_delete_code(self):
        def trigger():
            self.delete_prompt()
            self.click('tv_confirm')
        self.request_code(trigger)

    def delete_code(self):
        code = self.new_code(self.start_delete_code)
        self.text('ID Verification')
        assert self.email in self.el('tv_summary').text
        return code

    def delete(self):
        code = self.delete_code()
        # 输入第6位会自动提交注销，随后确认游客状态。
        self.enter_code(code)
        self.a.wait(lambda: self.has('tabIcon'), '注销后主页面', 25)
        self.home()
        assert self.el('hint').text == 'Not logged in'

    def register(self, password=None):
        password = self.password if password is None else password
        self.password_page('register')
        self.complete_registration(password)

    def complete_registration(self, password=None):
        """当前已在 Create password 页时提交注册，避免重复发送验证码。"""
        password = self.password if password is None else password
        self.fill('et_pwd', password)
        self.click('tv_pwd_ok')
        self.a.wait(lambda: self.has('tabIcon'), '注册后自动登录', 25)
        self.home()
        assert self.el('hint').text == self.email
        self.password = password
        save_password(password, self.email)
        self.password_changed = password != self.original_password

    def reset(self, password):
        self.password_page('reset')
        self.complete_password_reset(password)

    def complete_password_reset(self, password):
        """在现有 Create new password 页提交密码，不再次请求验证码。"""
        self.fill('et_pwd', password)
        self.click('tv_pwd_ok')
        self.text('Log in Your Account')
        self.password = password
        save_password(password, self.email)
        self.password_changed = password != self.original_password

    def restore(self):
        if self.password_changed:
            self.reset(self.original_password)
            self.login(self.original_password)
            self.password_changed = False
        # 注册/注销页检查允许保留未注册状态，下一条从真实状态准备。
        # 避免每条重复注销+注册耗尽邮箱配额，也不让无关 UI 用例因强制登录报错。
        self.home()

    def eye(self, rounds):
        self.fill('et_pwd', self.password)
        assert self.el('et_pwd').get_attribute('password') == 'true'
        for _ in range(rounds):
            self.click('iv_hide_pwd')
            assert self.el('et_pwd').get_attribute('password') == 'false'
            assert self.value('et_pwd') == self.password
            self.click('iv_hide_pwd')
            assert self.el('et_pwd').get_attribute('password') == 'true'
        self.click('iv_hide_pwd')
        assert self.value('et_pwd') == self.password
        self.click('iv_hide_pwd')

    def unchanged(self, marker):
        self.settle()
        self.el(marker)
        assert not self.has('tabIcon'), '意外进入已登录页面'

    def wrong_login(self):
        self.login_page()
        self.fill('et_email', self.email)
        self.fill('et_pwd', 'wrong123')
        self.click('tv_login_btn')
        self.text('Login Failed')
        self.text('Incorrect account or password.')

    def unregistered_login(self, mode='login'):
        # 调用前由 prepare 校验未注册；此处执行被测登录/找回动作。
        self.login_page() if mode == 'login' else self.email_page('reset')
        self.fill('et_email', self.email)
        if mode == 'login':
            self.fill('et_pwd', self.password)
        self.click('tv_login_btn' if mode == 'login' else 'tv_email_next')
        self.text('Not registered')

    def restart(self):
        Adb().shell(self.a.context['phone'], 'am', 'force-stop', self.package)
        self.a.ensure_foreground()
        self.a.wait(lambda: self.has('tabIcon'), '重启后主页', 25)
        self.home()
        assert self.el('hint').text == self.email
