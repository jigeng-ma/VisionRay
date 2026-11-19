"""业务用例在重装或未绑定状态下恢复登录、目标绑定和首页。"""
from pathlib import PurePosixPath


def needs_business_preparation(nodeid):
    path, _, name = nodeid.replace('\\', '/').partition('::')
    filename = PurePosixPath(path).name
    return not (filename in {'test_auth.py', 'test_pairing.py',
                             'test_pairing_cards.py'}
                or 'pair' in name.lower().replace('unpair', '')
                or 'bind' in name.lower().replace('unbind', ''))


def prepare_business(android, *, force=False):
    from .auth import AuthPage
    from .home_device import HomeDevicePage
    from .pairing import PairingPage, discovery_panel

    android.ensure_foreground()
    auth = AuthPage(android)
    fresh = force or auth.has('tv_login_by_email') or any(android.find(key) for key in (
        'pair.add', 'pair.tutorial_begin', 'pair.skip_title')) or discovery_panel(android) is not None
    if not fresh:
        return
    android.log('business-preparation', '恢复登录、目标绑定并跳过新手引导')
    if auth.has('tv_login_by_email'):
        auth.login_for_pairing()
    else:
        auth.registered()
    pairing = PairingPage(android)
    original = pairing.options.copy()
    try:
        pairing.options.update(skip_tutorial=True, require_pairing_prompt=False)
        HomeDevicePage(android).connected()
    finally:
        pairing.options.clear()
        pairing.options.update(original)
    android.capture('business-preparation-target-ready')
