"""G00_登录注册。编号与表格 B 列一一对应，可由工作台单条执行。"""
import re
import pytest
from studio.auth import AuthPage, EMAIL, PASSWORD
from studio.errors import TestBlocked


# 只列出有完整动作和断言的用例；未实现项不注册占位测试。
IMPLEMENTED = [1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 22, 23, 25, 26, 27,
               24, 28, 29, 31, 34, 40, 42, 43, 44, 45, 46, 49,
               50, 51, 52, 53, 55, 56, 57, 58, 59, 62, 67, 71, 72, 73, 74,
               76, 78, 79, 80, 81, 82, 87, 88, 89, 90, 91, 93, 94, 95,
               30, 32, 33, 37, 38, 41, 47, 48]
REGISTRATION = {24, 28, 29, 30, 31, 32, 33, 34, 37, 38, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49}
REG_PASSWORD = {42, 43, 44, 45, 46, 47, 48, 49}
RESET_PASSWORD = {72, 73, 74, 78}


@pytest.fixture
def context(context):
    # 邮件轮询最长90秒，不能沿用驱动默认60秒空闲超时。
    return dict(context, config=dict(context['config'], new_command_timeout=180))


@pytest.fixture
def auth(android):
    page = AuthPage(android)
    try:
        yield page
    finally:
        # 清理失败作为 teardown ERROR，不能掩盖账号未恢复的事实。
        page.restore()


@pytest.mark.parametrize('number', IMPLEMENTED, ids=lambda n: f'AUTH_{n:03d}')
def test_auth(auth, number, request):
    try:
        auth.prepare(number)
        run_case(auth, number)
        auth.a.capture(f'AUTH_{number:03d}-passed')
    except TestBlocked as exc:
        auth.a.capture(f'AUTH_{number:03d}-blocked')
        request.node.user_properties.append(('studio_status', 'BLOCKED'))
        pytest.skip(str(exc))
    except Exception:
        auth.a.capture(f'AUTH_{number:03d}-failed')
        raise


def run_case(p, n):
    if n in REGISTRATION:
        code = p.code_page('register')
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
        p.login_page()
        p.click('tv_login_by_google')
        account = p.a.wait(lambda: next((e for e in p.d.find_elements(
            'xpath', "//*[@text='majigeng2016@163.com']") if e.is_displayed()), None),
                           'Google 账号 majigeng2016@163.com', 15)
        account.click()
        p.a.wait(lambda: p.has('tabIcon'), 'Google 登录成功', 30)
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
        p.d.back(); p.text('Log in Your Account')
    elif n in (9, 10):
        p.login_page()
        p.fill('et_email', '' if n == 9 else EMAIL)
        p.fill('et_pwd', '123456')
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
            p.a.wait(lambda: any(e.is_displayed() and e.get_attribute('className') == 'android.widget.Toast'
                                 for e in p.d.find_elements('xpath', '//*')) or p.has('tvDesc'),
                     '断网登录失败提示', 12)
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
    elif n in (24, 28, 29, 30, 31, 32, 33, 34, 37, 38, 40, 41):
        check_code(p, n, code, 'register')
    elif n in (42, 43, 44, 45, 46, 49, 72, 73, 74, 78):
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
        elif n in (49, 78):
            p.fill('et_pwd', PASSWORD)
            p.click('tv_pwd_ok')
            if n == 49:
                p.a.wait(lambda: p.has('tabIcon'), '注册后自动登录', 25)
                p.home()
                assert p.el('hint').text == EMAIL
            else:
                p.text('Log in Your Account')
                assert p.value('et_email') == EMAIL
                p.login()
    elif n in (55, 56):
        p.unregistered_login('reset')
        assert p.el('tv_confirm').text == 'Create Account'
        assert p.el('tv_cancel').text == 'Cancel'
        p.click('tv_confirm' if n == 55 else 'tv_cancel')
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
    elif n in (76, 79):
        p.reset('NovaQA9!z')
        if n == 79:
            p.login_page()
            p.fill('et_email', EMAIL)
            p.fill('et_pwd', PASSWORD)
            p.click('tv_login_btn')
            p.text('Login Failed')
            p.click('tv_cancel')
        p.login('NovaQA9!z')
        p.reset(PASSWORD)
        p.login()
        p.password_changed = False
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
                    valid = PASSWORD if i == 0 else 'NovaQA9!z'
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
        checkpoint = p.mail.checkpoint()
        p.start_delete_code()
        p.text('ID Verification')
        assert EMAIL in p.el('tv_summary').text
        for i in range(1, 7):
            p.el(f'et_code{i}')
        if n == 90:
            retry = p.el('tv_retry')
            match = re.search(r'(\d+)s', retry.text)
            assert match and 55 <= int(match[1]) <= 60, '初始倒计时不是60秒附近'
            assert not retry.is_enabled()
            assert re.fullmatch(r'\d{6}', p.mail.wait_for_code(checkpoint)['code'])
        p.click('tv_cancel')
        assert p.el('tv_email').text == EMAIL
    elif n in (93, 94):
        p.delete()
        if n == 93:
            p.login_page()
            p.fill('et_email', EMAIL)
            p.fill('et_pwd', PASSWORD)
            p.click('tv_login_btn')
            p.text('Not registered')
        else:
            p.register()
            p.login()
    elif n == 95:
        p.registered()
        p.restart()
        p.account()
    else:
        raise AssertionError(f'编号未实现：{n}')


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
            for index in range(1, 7):
                p.el(f'et_code{index}').clear()
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
    elif n in (34, 40, 67):
        p.a.wait(lambda: p.el('tv_resend_captcha').is_enabled(), '允许重新发送', 75)
        p.resend_code()
        assert EMAIL in p.el('tv_summary').text
    elif n == 37:
        # 验证码有效期为 30 分钟；每分钟触碰一次 UI，避免 Appium 空闲会话超时。
        for minute in range(28):
            __import__('time').sleep(60)
            p.a.capture(f'AUTH_037-wait-{minute + 1:02d}m')
        p.verify(code, mode)
        p.complete_registration(); p.delete()
    elif n == 38:
        second = p.resend_code()
        p.enter_code(code)
        p.click('tv_captcha_next')
        assert p.el('tv_title').text == 'Incorrect verification code'
        p.click('tv_confirm')
        p.verify(second, mode)
        p.complete_registration(); p.delete()
    elif n == 41:
        p.enter_code('000000')
        p.click('tv_captcha_next')
        assert p.el('tv_title').text == 'Incorrect verification code'
        p.click('tv_confirm')
        p.click('tv_update_email_address')
        p.text("What's your email?")
        p.fill('et_email', EMAIL)
        fresh = p.new_code(lambda: p.request_code(lambda: p.click('tv_email_next')))
        p.verify(fresh, mode)
        p.complete_registration(); p.delete()
    elif n == 47:
        p.fill('et_pwd', 'Qa1!z9')
        assert p.el('tv_pwd_ok').is_enabled()
        p.complete_registration('Qa1!z9')
        p.entry(); p.login('Qa1!z9')
        p.reset(PASSWORD); p.login(); p.password_changed = False
    elif n == 48:
        for value in (' Qa1!z9', 'Qa1!z9 ', 'Qa 1!z9'):
            p.fill('et_pwd', value)
            assert p.value('et_pwd') == value.replace(' ', ''), '密码输入端未过滤空格'
