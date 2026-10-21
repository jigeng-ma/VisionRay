"""G10_我的：列表项的行点击、箭头点击和侧滑返回。"""

import pytest

from studio.errors import TestBlocked
from studio.my_page import MyPage
from studio.feedback_page import FeedbackPage


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


def feedback(android, request, case_id):
    try:
        FeedbackPage(android).submit_and_verify(case_id)
    except TestBlocked as exc:
        android.capture('feedback-blocked')
        request.node.user_properties.append(('studio_status', 'BLOCKED'))
        pytest.skip(str(exc))


def test_feedback_idea_allow(android, request):
    feedback(android, request, 'MY_008')


def test_feedback_bug_deny(android, request):
    feedback(android, request, 'MY_009')
