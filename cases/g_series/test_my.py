"""G10_我的：列表项的行点击、箭头点击和侧滑返回。"""

import pytest

from studio.errors import TestBlocked
from studio.my_page import MyPage


def run(android, label):
    try:
        page = MyPage(android)
        page.open()
        page.assert_two_entries(label)
    except TestBlocked as exc:
        android.capture('my-blocked')
        pytest.skip(str(exc))


def test_account(android): run(android, 'Account')
def test_file_history(android): run(android, 'File History')
def test_background_activity_permission(android): run(android, 'Background Activity Permission')
def test_permission(android): run(android, 'Permission')
def test_personal_info_privacy(android): run(android, 'Personal Info & Privacy')
def test_feedback(android): run(android, 'Feedback')
def test_about_app(android): run(android, 'About App')
