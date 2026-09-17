"""框架接入验收场景，不代表真实产品业务功能已覆盖。"""


def test_app_installed(adb, context):
    assert adb.shell(context['phone'], 'pm', 'path', context['config']['package']).startswith('package:')


def test_glasses_online(adb, context):
    assert adb.online(context['glasses'])


def test_about_element(android):
    # 只检查当前 My 页面，不自动导航或修改用户状态。
    import pytest
    if 'About App' not in android.driver.page_source:
        pytest.skip('此检查要求 APP 停留在英文 My 页面。')
    assert android.element('my.about').text == 'About App'


def test_ui_tree(android, context):
    assert android.driver.current_package == context['config']['package']
    assert context['config']['package'] in android.driver.page_source
