"""G00_登录注册。编号与表格 B 列一一对应，可由工作台单条执行。"""
import re
import json
import os
import time
from pathlib import Path
from xml.etree import ElementTree as ET
import pytest
from studio.auth import AUTH, ROOT, AuthPage, EMAIL, PASSWORD, alternate_password, install_auth_variant
from studio.devices import Adb
from studio.errors import TestBlocked, WaitTimeout
from studio.mailbox import VerificationMailbox


# 只列出有完整动作和断言的用例；未实现项不注册占位测试。
IMPLEMENTED = [1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 22, 23, 25, 26, 27,
               24, 28, 29, 31, 34, 42, 43, 44, 45, 46, 49,
               50, 51, 52, 53, 55, 56, 57, 58, 59, 62, 67, 71, 72, 73, 74,
               75, 76, 78, 79, 80, 81, 82, 87, 88, 89, 90, 91, 93, 94, 95,
               30, 32, 33, 37, 38, 39, 41, 47, 48]
REGISTRATION = {24, 28, 29, 30, 31, 32, 33, 34, 37, 38, 41, 42, 43, 44, 45, 46, 47, 48, 49}
REG_PASSWORD = {42, 43, 44, 45, 46, 47, 48, 49}
RESET_PASSWORD = {72, 78}
RESET_PASSWORD_FOLLOWUPS = (73, 74, 75, 76)
TEMP_PASSWORD = alternate_password(PASSWORD)
SHARED_CODE_CASES = (24, 28, 34, 38, 29, 30, 32, 33)
PASSWORD_PAGE_FOLLOWUPS = (42, 43, 44, 45, 49, 47)


def shared_code_file():
    context = os.environ.get('GLASSES_RUN_CONTEXT')
    if not context:
        raise TestBlocked('这组用例需要工作台轮次；请从 C-L_024 开始连续执行。')
    return Path(context).parent / 'registration-code.json'


def save_shared_code(code, number, old_code=None):
    path = shared_code_file()
    sent_at = time.time() if number in (24, 34) else json.loads(path.read_text(encoding='utf-8'))['sent_at']
    data = {'account': EMAIL, 'code': code, 'sent_at': sent_at, 'last_case': number}
    if number == 34:
        data['old_code'] = old_code
    path.write_text(json.dumps(data), encoding='utf-8')


def load_shared_code(page, number):
    path = shared_code_file()
    if not path.is_file():
        raise TestBlocked('缺少 C-L_024 的验证码会话；此用例不会自行重新发码。')
    data = json.loads(path.read_text(encoding='utf-8'))
    previous = SHARED_CODE_CASES[SHARED_CODE_CASES.index(number) - 1]
    if data.get('account') != EMAIL or data.get('last_case') != previous:
        raise TestBlocked(f'C-L_{number:03d} 需要紧接 C-L_{previous:03d}，且使用同一邮箱。')
    if time.time() - data.get('sent_at', 0) >= 30 * 60:
        raise TestBlocked('C-L_024 的验证码已过 30 分钟有效期；此用例不会自行重新发码。')
    if not re.fullmatch(r'\d{6}', str(data.get('code', ''))):
        raise TestBlocked('共享验证码记录无效。')
    if not page.has('et_code1') or EMAIL not in page.el('tv_summary').text:
        raise TestBlocked('验证码页面已丢失；请重新从 C-L_024 开始执行。')
    page.enter_code('')
    return data['code']


def clear_shared_code():
    context = os.environ.get('GLASSES_RUN_CONTEXT')
    if context:
        (Path(context).parent / 'registration-code.json').unlink(missing_ok=True)


def password_page_file():
    return shared_code_file().with_name('registration-password-page.json')


def reset_password_page_file():
    return shared_code_file().with_name('reset-password-page.json')


def previous_password_file():
    return shared_code_file().with_name('previous-password.json')


def delete_verification_page_file():
    return shared_code_file().with_name('delete-verification-page.json')


def deleted_account_flow_file():
    return shared_code_file().with_name('deleted-account-flow.json')


def continue_deleted_account_flow(page, number):
    previous = {94: 93, 95: 94}[number]
    path = deleted_account_flow_file()
    if not path.is_file():
        raise TestBlocked(f'VisionRay_{number - 19:04d} 需要紧接 VisionRay_{previous - 19:04d} 的账号状态。')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('account') != EMAIL or data.get('last_case') != previous:
        raise TestBlocked(f'VisionRay_{number - 19:04d} 需要紧接 VisionRay_{previous - 19:04d}，且使用同一邮箱。')
    page.home()
    expected = 'Not logged in' if number == 94 else EMAIL
    if page.el('hint').text != expected:
        raise TestBlocked(f'VisionRay_{number - 19:04d} 前置账号状态不符，应为 {expected}。')


def continue_delete_verification_page(page):
    path = delete_verification_page_file()
    if not path.is_file():
        raise TestBlocked('VisionRay_0073 需要紧接 VisionRay_0072 的注销验证码页，不重新发送验证码。')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('account') != EMAIL or data.get('last_case') != 90:
        raise TestBlocked('VisionRay_0073 需要紧接 VisionRay_0072，且使用同一邮箱。')
    if not page.has('et_code1') or EMAIL not in page.el('tv_summary').text:
        raise TestBlocked('VisionRay_0072 留下的注销验证码页已丢失，不能重新发码代替。')
    page.text('ID Verification')


def load_previous_password(page):
    path = previous_password_file()
    if not path.is_file():
        raise TestBlocked('VisionRay_0065 需要紧接 VisionRay_0064；缺少上次重置前的旧密码记录。')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('account') != EMAIL or data.get('last_case') != 78 or data.get('new_password') != page.password:
        raise TestBlocked('VisionRay_0065 需要紧接 VisionRay_0064，且使用同一邮箱和新密码。')
    old_password = data.get('old_password')
    if not old_password or old_password == page.password:
        raise TestBlocked('VisionRay_0064 未留下与新密码不同的旧密码，无法验证失效。')
    return old_password


def continue_reset_password_page(page, number):
    path = reset_password_page_file()
    previous = {73: 72, 74: 73, 75: 74, 76: 75}[number]
    automation = {72: 60, 73: 61, 74: 62, 75: 144, 76: 63}
    if not path.is_file():
        raise TestBlocked(f'VisionRay_{automation[number]:04d} 需要紧接 VisionRay_{automation[previous]:04d} 的重置密码页，不重新发送验证码。')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('account') != EMAIL or data.get('last_case') != previous:
        raise TestBlocked(f'VisionRay_{automation[number]:04d} 需要紧接 VisionRay_{automation[previous]:04d}，且使用同一邮箱。')
    if not page.has('et_pwd'):
        raise TestBlocked('前一用例的重置密码页已丢失，不能重新发码代替。')
    page.text('Create new password')


def continue_password_page(page, number):
    path = password_page_file()
    previous = {42: 31, 43: 42, 44: 43, 45: 44, 49: 45, 47: 46}[number]
    if not path.is_file():
        prior_id = {42: 39, 49: 45}.get(number, previous)
        automation_id = {49: 47, 47: 123}.get(number, number)
        raise TestBlocked(f'VisionRay_{automation_id:04d} 需要紧接 VisionRay_{prior_id:04d} 的密码页，不重新发送验证码。')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('account') != EMAIL or data.get('last_case') != previous or not page.has('et_pwd'):
        raise TestBlocked('前一用例的 Create password 页面已丢失，不能重新发码代替。')
    page.text('Create password')


def load_pre_resend_code():
    data = json.loads(shared_code_file().read_text(encoding='utf-8'))
    if data.get('last_case') != 34 or not re.fullmatch(r'\d{6}', str(data.get('old_code', ''))):
        raise TestBlocked('C-L_038 缺少 C-L_034 重发前的旧验证码。')
    return data['old_code']


def used_code_file():
    return shared_code_file().with_name('used-registration-code.json')


def save_used_code(code, sent_at):
    used_code_file().write_text(json.dumps({'account': EMAIL, 'code': code,
                                            'sent_at': sent_at, 'last_case': 37}), encoding='utf-8')


def load_used_code():
    path = used_code_file()
    if not path.is_file():
        raise TestBlocked('C-L_039 需要紧接本轮成功的 C-L_037，且不重新发送验证码。')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('account') != EMAIL or data.get('last_case') != 37 or not re.fullmatch(r'\d{6}', str(data.get('code', ''))):
        raise TestBlocked('C-L_037 的旧验证码记录无效。')
    return data['code']


@pytest.fixture
def context(context):
    # 邮件轮询最长90秒，不能沿用驱动默认60秒空闲超时。
    return dict(context, config=dict(context['config'], new_command_timeout=180))


@pytest.fixture
def auth(android, context, request):
    page = AuthPage(android)
    google_login = request.node.callspec.params['number'] == 5
    try:
        if google_login:
            install_auth_variant(android, context, 'release')
            page.login_page()
        yield page
    finally:
        if google_login:
            install_auth_variant(android, context, 'debug')
            android.ensure_foreground()
            android.wait(lambda: page.has('tv_login_by_email') or page.has('tabIcon'),
                         '重装 debug 后完成首次启动协议确认', 30)
            android.capture('google-debug-restored')
        elif not page.keep_code_page:
            # 清理失败作为 teardown ERROR，不能掩盖账号未恢复的事实。
            page.restore()


@pytest.mark.parametrize('number', IMPLEMENTED, ids=lambda n: f'AUTH_{n:03d}')
def test_auth(auth, number, request):
    try:
        if number == 41:
            new_email = next((account for account in (AUTH['account'], *AUTH.get('alternate_accounts', {}))
                              if account != EMAIL), None)
            if not new_email:
                raise TestBlocked('C-L_041 需要另一个已配置授权码的测试邮箱。')
            # 更换邮箱要求新地址尚未注册；这是前置准备，正式测试仍只发原、新各一封。
            AuthPage(auth.a, account=new_email).unregistered()
        if number not in (39, 79, 91, 94, 95) and number not in RESET_PASSWORD_FOLLOWUPS and number not in PASSWORD_PAGE_FOLLOWUPS and number not in SHARED_CODE_CASES[1:]:
            auth.prepare(number)
        if number in PASSWORD_PAGE_FOLLOWUPS:
            continue_password_page(auth, number)
        if number in RESET_PASSWORD_FOLLOWUPS:
            continue_reset_password_page(auth, number)
        if number == 91:
            continue_delete_verification_page(auth)
        if number in (94, 95):
            continue_deleted_account_flow(auth, number)
        code = (load_shared_code(auth, number) if number in SHARED_CODE_CASES[1:]
                else load_used_code() if number == 39
                else load_previous_password(auth) if number == 79 else None)
        issued_code = run_case(auth, number, code)
        if number in (24, 34):
            save_shared_code(issued_code, number, old_code=code if number == 34 else None)
        elif number in SHARED_CODE_CASES[1:-1]:
            save_shared_code(code, number)
        elif number == 33:
            clear_shared_code()
        elif number in (31, 42, 43, 44, 45, 46):
            password_page_file().write_text(json.dumps({'account': EMAIL, 'last_case': number}), encoding='utf-8')
        elif number in (49, 47):
            password_page_file().unlink(missing_ok=True)
        elif number == 37:
            save_used_code(*issued_code)
            auth.keep_code_page = True
        elif number == 39:
            used_code_file().unlink(missing_ok=True)
        elif number in (72, 73, 74, 75):
            reset_password_page_file().write_text(json.dumps({'account': EMAIL, 'last_case': number}), encoding='utf-8')
        elif number == 76:
            reset_password_page_file().unlink(missing_ok=True)
        elif number == 78:
            previous_password_file().write_text(json.dumps({
                'account': EMAIL, 'last_case': 78,
                'old_password': issued_code, 'new_password': auth.password}), encoding='utf-8')
        elif number == 79:
            previous_password_file().unlink(missing_ok=True)
        elif number == 90:
            delete_verification_page_file().write_text(json.dumps({
                'account': EMAIL, 'last_case': 90}), encoding='utf-8')
        elif number == 91:
            delete_verification_page_file().unlink(missing_ok=True)
        elif number in (93, 94):
            deleted_account_flow_file().write_text(json.dumps({
                'account': EMAIL, 'last_case': number}), encoding='utf-8')
        elif number == 95:
            deleted_account_flow_file().unlink(missing_ok=True)
        if number in SHARED_CODE_CASES[:-1]:
            auth.keep_code_page = True
        if number in (31, 42, 43, 44, 45, 46):
            auth.keep_code_page = True
        if number in (72, 73, 74, 75):
            auth.keep_code_page = True
        if number == 90:
            auth.keep_code_page = True
        auth.a.capture(f'AUTH_{number:03d}-passed')
    except TestBlocked as exc:
        if number in SHARED_CODE_CASES:
            clear_shared_code()
        auth.a.capture(f'AUTH_{number:03d}-blocked')
        request.node.user_properties.append(('studio_status', 'BLOCKED'))
        pytest.skip(str(exc))
    except Exception:
        if number in SHARED_CODE_CASES:
            clear_shared_code()
        auth.a.capture(f'AUTH_{number:03d}-failed')
        raise


def run_case(p, n, shared_code=None):
    code_sent_at = time.time() if n == 37 else None
    code = shared_code
    if n in REGISTRATION and n not in PASSWORD_PAGE_FOLLOWUPS:
        code = shared_code if n in SHARED_CODE_CASES[1:] else p.code_page('register')
        if n in REG_PASSWORD:
            p.verify(code, 'register')
    if n in RESET_PASSWORD:
        p.password_page('reset')

    if n == 1:
        p.entry()
        controls = [p.el(key) for key in ('tv_skip', 'tv_login_by_email', 'tv_login_by_google', 'tv_create_new_account')]
        assert [e.text for e in controls] == ['Skip', 'Log in with Email', 'Log in with Google', 'Create Account']
        rects = [e.rect for e in controls]
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                assert a['x'] + a['width'] <= b['x'] or b['x'] + b['width'] <= a['x'] or a['y'] + a['height'] <= b['y'] or b['y'] + b['height'] <= a['y'], '入口控件重叠'
    elif n in (3, 4):
        p.entry()
        p.click('tv_skip')
        p.home()
        assert p.el('hint').text == 'Not logged in'
        if n == 4:
            p.text('Account').click()
            for label in ('Log in with Email', 'Log in with Google', 'Create Account'):
                p.text(label)
    elif n == 5:
        # Google 入口只在登录方式选择页；邮箱密码页没有该控件。
        variant = p.installed_variant()
        if variant != 'release':
            raise AssertionError(f'Google 登录用例需要 release 包，当前安装的是 {variant} 包。')
        p.entry()
        p.click('tv_login_by_google')
        account = p.a.wait(lambda: next((e for e in p.d.find_elements(
            'xpath', "//*[contains(@text, 'majigeng2016@163.com') or "
                     "contains(@content-desc, 'majigeng2016@163.com')]"
                     "/ancestor-or-self::*[@clickable='true'][1]") if e.is_displayed()), None),
                           'Google 账号选择项 majigeng2016@163.com', 20)
        account.click()
        try:
            result = p.a.wait(lambda: 'login_failed' if 'Login Failed' in p.d.page_source else
                              'success' if p.has('tabIcon') else None,
                              'Google 登录成功或明确失败提示', 75)
        except WaitTimeout:
            # 服务端错误提示有时恰好在超时截图期间出现。
            if 'Login Failed' not in p.d.page_source:
                raise AssertionError('Google 登录等待 75 秒后既未进入已登录首页，也未显示 Login Failed。') from None
            result = 'login_failed'
        if result == 'login_failed':
            variant = p.installed_variant()
            if variant == 'debug':
                raise AssertionError('debug不支持google登录，需要release版本')
            raise AssertionError(f'{variant}版本 Google 登录提示 Login Failed；请检查账号或服务端日志。')
        p.home(); p.text('Account').click(); p.click('tv_logout'); p.click('tv_cancel')
        p.el('tv_login_by_email')
    elif n == 6:
        p.login_page()
        for key in ('et_email', 'et_pwd', 'iv_hide_pwd', 'tv_login_btn', 'tv_forgot_pwd', 'back_iv'):
            p.el(key)
        assert p.el('tv_login_btn').text == 'Log in'
        assert p.el('tv_forgot_pwd').text.startswith('Forgot Password')
        assert all(t in p.el('tv_privacy').text for t in ('User Agreement', 'Privacy Policy'))
    elif n == 11:
        p.login_page()
        p.eye(1)
    elif n in (7, 8):
        p.login_page()
        title = 'User Agreement' if n == 7 else 'Privacy Policy'
        p.click_privacy_link(title)
        p.assert_page_title(title)
        for _ in range(3):
            p.d.back()
            if p.d.current_package == p.package:
                break
        if p.d.current_package != p.package:
            raise AssertionError(f'退出 {title} 后仍停留在系统浏览器，未返回 APP。')
        if p.has('tv_login_by_email'):
            raise AssertionError(f'退出 {title} 后返回登录方式选择页，未保留原邮箱登录页。')
        p.text('Log in Your Account')
    elif n in (9, 10):
        p.login_page()
        p.fill('et_email', '' if n == 9 else EMAIL)
        p.fill('et_pwd', '' if n == 10 else p.password)
        p.disabled_login_stays_here()
    elif n == 13:
        adb = Adb(); serial = p.a.context['phone']
        original = adb.shell(serial, 'settings', 'get', 'system', 'time_12_24')
        try:
            for value in ('12', '24'):
                adb.shell(serial, 'settings', 'put', 'system', 'time_12_24', value)
                p.registered(verify_password=True)
                p.entry(); p.login()
        finally:
            if original and original != 'null':
                adb.shell(serial, 'settings', 'put', 'system', 'time_12_24', original)
            else:
                adb.shell(serial, 'settings', 'delete', 'system', 'time_12_24')
    elif n == 14:
        p.login_page(); p.fill('et_email', 'a@b'); p.fill('et_pwd', '123456')
        p.disabled_login_stays_here()
    elif n == 20:
        p.login_page(); p.fill('et_email', EMAIL); p.fill('et_pwd', PASSWORD)
        adb = Adb(); serial = p.a.context['phone']
        try:
            adb.shell(serial, 'svc', 'wifi', 'disable')
            adb.shell(serial, 'svc', 'data', 'disable')
            p.click('tv_login_btn')
            def failure_prompt():
                # Appium 把短暂 Toast 合并进 page_source；读取后可能立即清除，
                # 因此此处直接检查同一次 XML 快照，不能先交给通用弹窗处理。
                nodes = ET.fromstring(p.d.page_source).iter()
                return next((text for node in nodes if (text := node.get('text', '')) and
                             ('network connection failed' in text.lower() or
                              node.get('resource-id', '').endswith(':id/tvDesc'))), None)
            prompt = p.a.wait(failure_prompt, '断网登录失败提示', 15, handle_popups=False)
            p.a.log('offline-login-prompt', prompt)
            assert 'network connection failed' in prompt.lower(), f'断网登录提示内容不符：{prompt}'
            p.text('Log in Your Account')
        finally:
            adb.shell(serial, 'svc', 'wifi', 'enable')
            adb.shell(serial, 'svc', 'data', 'enable')
        p.login()
    elif n == 12:
        p.login()
        p.account()
    elif n in (15, 16, 17):
        p.unregistered_login()
        assert p.el('tv_cancel').text == 'Cancel'
        assert p.el('tv_confirm').text == 'Create Account'
        p.click('tv_cancel' if n == 17 else 'tv_confirm')
        p.text('Log in Your Account' if n == 17 else "What's your email?")
        if n in (16, 17):
            assert p.value('et_email') == EMAIL, '邮箱未保留'
            p.fill('et_email', 'abc')
            assert p.value('et_email') == 'abc'
    elif n in (18, 19):
        p.wrong_login()
        assert p.el('tv_cancel').text == 'Cancel'
        assert p.el('tv_confirm').text == 'Reset Password'
        p.click('tv_cancel' if n == 18 else 'tv_confirm')
        p.text('Log in Your Account' if n == 18 else 'Find your account')
        if n == 19:
            assert p.value('et_email') == EMAIL
            p.fill('et_email', 'abc')
            assert p.value('et_email') == 'abc'
    elif n in (22, 23, 26, 27):
        p.email_page('register')
        if n == 22:
            for key in ('et_email', 'tv_email_next', 'back_iv'):
                p.el(key)
            assert all(t in p.el('tv_privacy').text for t in ('User Agreement', 'Privacy Policy'))
        elif n == 23:
            p.fill('et_email', '')
            p.click('tv_email_next')
            p.unchanged('layout_email')
        else:
            p.fill('et_email', EMAIL)
            p.click('tv_email_next')
            p.text('Email registered')
            p.click('tv_confirm' if n == 26 else 'tv_cancel')
            p.text('Log in Your Account' if n == 26 else "What's your email?")
            assert p.value('et_email') == EMAIL
            if n == 27:
                p.fill('et_email', 'abc')
                assert p.value('et_email') == 'abc'
    elif n == 25:
        p.email_page('register')
        checkpoint = p.mail.checkpoint()
        p.fill('et_email', 'abc')
        p.click('tv_email_next')
        p.unchanged('layout_email')
        p.no_new_mail(checkpoint)
    elif n in (24, 28, 29, 30, 31, 32, 33, 34, 37, 38, 41, 47, 48):
        fresh_code = check_code(p, n, code, 'register')
    elif n == 39:
        # 注销入口会发送新码；此处只验证注册旧码在注销流程中被拒绝，
        # 不能单独证明失效原因是已使用、新码覆盖还是自然过期。
        p.start_delete_code()
        p.text('ID Verification')
        assert EMAIL in p.el('tv_summary').text, '注销验证码页不是原测试邮箱'
        p.enter_code(shared_code)
        if not p.has('tvDesc') and p.has('tv_captcha_next') and p.el('tv_captcha_next').is_enabled():
            p.click('tv_captcha_next')
        p.a.assert_wait(lambda: p.has('tvDesc') or p.has('tabIcon'), True,
                        '旧验证码提交后出现错误提示或注销结果', 20)
        if p.has('tabIcon') and not p.has('tvDesc'):
            raise AssertionError('注册旧验证码被接受，账号已注销')
        message = ' '.join((p.el('tv_title').text, p.el('tvDesc').text)).lower()
        assert (any(word in message for word in ('code', 'verification', '验证码')) and
                any(word in message for word in ('incorrect', 'invalid', 'expired', 'error', 'failed', 'used',
                                                 '错误', '失效', '过期', '无效'))), \
            f'旧验证码未被明确判定错误或失效：{message}'
        p.click('tv_confirm')
        p.home()
        assert p.el('hint').text == EMAIL, '旧验证码提交后账号已注销'
    elif n in (42, 43, 44, 45, 46, 49, 72, 73, 74, 75, 78):
        if n in (42, 72):
            for key in ('et_pwd', 'iv_hide_pwd', 'tv_pwd_ok', 'back_iv'):
                p.el(key)
            assert '6' in p.el('tv_input_email_sub_title').text
            if n == 42:
                assert all(t in p.el('tv_privacy').text for t in ('User Agreement', 'Privacy Policy'))
        elif n in (43, 44, 73):
            p.eye(1 if n == 43 else 10)
        elif n in (45, 74):
            p.fill('et_pwd', '1234q')
            assert not p.el('tv_pwd_ok').is_enabled()
            if n == 45:
                p.el('et_pwd').click()
                p.d.press_keycode(123)  # MOVE_END 后实际键入，send_keys 会替换原值。
                p.d.press_keycode(51)  # KEYCODE_W
                p.hide_keyboard()
                assert p.el('tv_pwd_ok').is_enabled()
        elif n == 75:
            p.fill('et_pwd', 'a' * 30)
            assert p.value('et_pwd') == 'a' * 30, '30 位新密码未完整输入'
            assert p.el('tv_pwd_ok').is_enabled(), '30 位合规新密码无法提交'
            p.el('et_pwd').click()
            p.d.press_keycode(123)
            p.d.press_keycode(30)
            p.hide_keyboard()
            assert p.value('et_pwd') == 'a' * 30, '第 31 位字符未被限制'
            p.fill('et_pwd', '')
        elif n == 46:
            p.click('iv_hide_pwd')
            p.fill('et_pwd', 'a' * 30)
            assert p.value('et_pwd') == 'a' * 30
            p.el('et_pwd').click()
            p.d.press_keycode(123)
            p.d.press_keycode(30)  # KEYCODE_B
            p.hide_keyboard()
            assert p.value('et_pwd') == 'a' * 30, '第31字符未被拦截'
            assert p.el('tv_pwd_ok').is_enabled()
            p.fill('et_pwd', '')
            assert p.value('et_pwd') == '', '长度校验后未清空密码输入框'
        elif n == 49:
            p.complete_registration()
        elif n == 78:
            old_password = p.password
            new_password = alternate_password(old_password)
            p.complete_password_reset(new_password)
            p.password_changed = False  # 新密码已保存为当前密码，下一条用旧密码验证。
            previous_password_file().write_text(json.dumps({
                'account': EMAIL, 'last_case': 78,
                'old_password': old_password, 'new_password': p.password}), encoding='utf-8')
            assert p.value('et_email') == EMAIL
            p.login(new_password)
            return old_password
    elif n in (55, 56):
        p.unregistered_login('reset')
        assert p.el('tv_confirm').text == 'Create Account'
        assert p.el('tv_cancel').text == 'Cancel'
        # 此确认框的 resource-id 在部分版本中与文案语义相反，按可见文案点击。
        p.text('Create Account' if n == 55 else 'Cancel').click()
        p.text("What's your email?" if n == 55 else 'Find your account')
        assert p.value('et_email') == EMAIL, '邮箱未保留'
        p.fill('et_email', 'abc')
        assert p.value('et_email') == 'abc'
    elif n in (50, 51, 52, 57):
        p.login_page()
        value = {50: '', 51: 'abc', 52: EMAIL, 57: ''}[n]
        p.fill('et_email', value)
        p.click('tv_forgot_pwd')
        p.text('Find your account')
        assert p.value('et_email') == value
        if n == 51:
            p.click('tv_email_next')
            p.text('Format Error')
            assert p.el('tvDesc').text == 'Incorrect email format, please check and re-enter.'
            p.click('tv_confirm')
            p.text('Find your account')
            assert p.value('et_email') == value and not p.has('et_code1'), '非法邮箱未被拦截'
        if n == 52:
            p.fill('et_email', 'abc')
            assert p.value('et_email') == 'abc'
        if n == 57:
            p.click('back_iv')
            p.text('Log in Your Account')
    elif n in (53, 58, 59, 62, 67):
        code = p.code_page('reset')
        check_code(p, n, code, 'reset')
    elif n == 71:
        for button in ('tv_update_email_address', 'back_iv'):
            p.code_page('reset')
            p.click(button)
            p.text('Find your account')
            p.fill('et_email', 'abc')
            assert p.value('et_email') == 'abc'
    elif n == 76:
        p.complete_password_reset(TEMP_PASSWORD)
        p.password_changed = False  # 新密码已保存为测试账号当前密码，无需再次发码恢复。
        p.login(TEMP_PASSWORD)
    elif n == 79:
        assert shared_code != p.password, '旧密码与新密码相同，无法验证旧密码失效'
        assert p.login_result(shared_code) == 'wrong_password', '重置前的旧密码仍可登录'
        p.text('Login Failed')
        p.click('tv_cancel')
        p.login(p.password)
    elif n in (80, 81, 82, 87, 88, 89):
        p.registered()
        p.account()
        if n == 80:
            for label in ('Change Password', 'Delete Account', 'Log Out'):
                p.text(label)
        elif n in (81, 82):
            p.click('cl_change_pwd')
            fields = ('et_old_pwd', 'et_new_pwd', 'et_again_pwd')
            p.password_changed = True  # 产品若错误接受无效输入，仍需通过邮箱恢复。
            for missing in range(3):
                for i, field in enumerate(fields):
                    valid = PASSWORD if i == 0 else TEMP_PASSWORD
                    p.fill(field, ('' if n == 81 else '1234q') if i == missing else valid)
                p.click('tv_submit_btn')
                p.settle()
                if p.has('tvDesc'):
                    title, message = p.el('tv_title').text, p.el('tvDesc').text
                    assert (title == 'Format Error' and 'at least 6' in message) or (
                        title == 'Failed' and message == 'The two passwords you entered do not match.'), (title, message)
                    assert p.el('tv_confirm').text == 'OK'
                    p.click('tv_confirm')
                p.text('Change Password')
                assert p.has(fields[missing]), '无效输入意外离开修改页'
            p.login()
            p.password_changed = False
        elif n in (87, 88):
            p.click('tv_logout')
            desc = p.el('tvDesc').text.lower()
            assert 'glass' in desc and 'ai' in desc
            assert p.el('tv_cancel').text == 'Log Out'
            assert p.el('tv_confirm').text == 'Cancel'
            p.click('tv_cancel' if n == 87 else 'tv_confirm')
            if n == 87:
                p.el('tv_login_by_email')
            else:
                assert p.el('tv_email').text == EMAIL
        else:
            p.click('cl_delete_account')
            desc = p.el('tvDesc').text.lower()
            assert all(t in desc for t in ('server', 'unrecoverable', 'pictures', 'videos'))
            p.click('tv_cancel')
            assert p.el('tv_email').text == EMAIL
    elif n in (90, 91):
        if n == 90:
            checkpoint = p.mail.checkpoint()
            p.start_delete_code()
            p.text('ID Verification')
            assert EMAIL in p.el('tv_summary').text
            for i in range(1, 7):
                p.el(f'et_code{i}')
            retry = p.el('tv_retry')
            match = re.search(r'(\d+)s', retry.text)
            assert match and 55 <= int(match[1]) <= 60, '初始倒计时不是60秒附近'
            assert not retry.is_enabled()
            assert re.fullmatch(r'\d{6}', p.mail.wait_for_code(checkpoint)['code'])
        else:
            p.click('tv_cancel')
            assert p.el('tv_email').text == EMAIL
    elif n == 93:
        p.delete()
        p.login_page()
        p.fill('et_email', EMAIL)
        p.fill('et_pwd', p.password)
        p.click('tv_login_btn')
        p.text('Not registered')
    elif n == 94:
        p.register()
        p.login()
    elif n == 95:
        p.restart()
        p.account()
    else:
        raise AssertionError(f'编号未实现：{n}')
    return ((code, code_sent_at) if n == 37 else fresh_code if n == 34
            else code if n == 24 else None)


def check_code(p, n, code, mode):
    if n in (24, 53):
        for key in ('tv_captcha_next', 'tv_update_email_address', 'tv_resend_captcha'):
            p.el(key)
        assert re.fullmatch(r'\d{6}', code)
    elif n in (28, 58):
        assert all(p.value(f'et_code{i}') == '' for i in range(1, 7))
        assert not p.el('tv_captcha_next').is_enabled()
    elif n in (29, 59):
        for value in ('1', '12345'):
            p.enter_code(value)
            assert not p.el('tv_captcha_next').is_enabled()
            p.click('tv_captcha_next')
            p.unchanged('layout_captcha')
    elif n == 30:
        for value in ('abc', '!?', '12a345', '1234567'):
            p.enter_code('')
            p.el('et_code1').send_keys(value)
            p.hide_keyboard()
            assert not p.el('tv_captcha_next').is_enabled(), f'非法验证码 {value!r} 不应通过本地校验'
            p.unchanged('layout_captcha')
    elif n in (31, 62):
        p.verify(code, mode)
    elif n == 32:
        p.enter_code('000000')
        p.click('tv_captcha_next')
        assert p.el('tv_title').text == 'Incorrect verification code'
        p.click('tv_confirm')
        p.text('Enter your verification code')
    elif n == 33:
        p.enter_code('000000')
        p.click('tv_captcha_next')
        assert p.el('tv_title').text == 'Incorrect verification code'
        p.click('tv_confirm')
        p.verify(code, mode)
        p.complete_registration(); p.delete()
    elif n == 34:
        fresh_code = p.resend_code()
        assert re.fullmatch(r'\d{6}', fresh_code), '重发后未收到可用的新验证码邮件'
        assert EMAIL in p.el('tv_summary').text
        return fresh_code
    elif n == 67:
        p.a.assert_wait(lambda: p.el('tv_resend_captcha').is_enabled(), True,
                        '重发验证码按钮可用状态', 75)
        p.resend_code()
        assert EMAIL in p.el('tv_summary').text
    elif n == 37:
        # 验证码有效期为 30 分钟；每分钟触碰一次 UI，避免 Appium 空闲会话超时。
        for minute in range(28):
            __import__('time').sleep(60)
            p.a.capture(f'AUTH_037-wait-{minute + 1:02d}m')
        p.verify(code, mode)
    elif n == 38:
        p.enter_code(load_pre_resend_code())
        p.click('tv_captcha_next')
        assert p.el('tv_title').text == 'Incorrect verification code'
        p.click('tv_confirm')
        p.text('Enter your verification code')
    elif n == 41:
        # 修改邮箱只需原、新邮箱各一封；不注册账号，避免清理时再发注销码。
        new_email = next((account for account in (AUTH['account'], *AUTH.get('alternate_accounts', {}))
                          if account != EMAIL), None)
        if not new_email:
            raise TestBlocked('C-L_041 需要另一个已配置授权码的测试邮箱。')
        p.click('tv_update_email_address')
        p.text("What's your email?")
        p.mail = VerificationMailbox(ROOT, new_email)
        p.fill('et_email', new_email)
        fresh = p.new_code(lambda: p.request_code(lambda: p.click('tv_email_next')))
        assert re.fullmatch(r'\d{6}', fresh), '新邮箱未收到可用验证码'
        assert new_email in p.el('tv_summary').text, '验证码页面未显示新邮箱'
        p.click('back_iv')
        p.text("What's your email?")
    elif n == 47:
        p.fill('et_pwd', 'Qa1!z9')
        assert p.el('tv_pwd_ok').is_enabled()
        p.complete_registration('Qa1!z9')
        # 新密码已保存为该测试账号当前密码；不再发邮件重置回旧密码。
        p.password_changed = False
        p.entry(); p.login('Qa1!z9')
    elif n == 48:
        for value in (' Qa1!z9', 'Qa1!z9 ', 'Qa 1!z9'):
            p.fill('et_pwd', value)
            assert p.value('et_pwd') == value.replace(' ', ''), '密码输入端未过滤空格'
