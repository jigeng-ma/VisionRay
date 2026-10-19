from unittest.mock import Mock
import pytest
from studio.ble_commands import BleMediaCommands
from studio.errors import TestBlocked


def test_model_guard_and_exactly_one_click_even_on_error(monkeypatch):
    monkeypatch.setattr('studio.ble_commands.time.sleep', lambda _: None)
    a = Mock(context={'config': {'product': 'G系列', 'model': 'G1', 'package': 'test'}})
    for model in ('G1', 'G3', 'G6'):
        a.context['config']['model'] = model
        p = BleMediaCommands(a)
        p.open = Mock()
        for action, (_, label) in p.BUTTONS.items():
            button = Mock(text=label)
            a.wait.return_value = button
            getattr(p, action)()
            button.click.assert_called_once_with()
        button = Mock(text='拍照')
        button.click.side_effect = RuntimeError('uncertain delivery')
        a.wait.return_value = button
        with pytest.raises(RuntimeError):
            p.take_photo()
        button.click.assert_called_once_with()
    a.context['config']['model'] = 'G2'
    with pytest.raises(TestBlocked):
        BleMediaCommands(a)


def media():
    return BleMediaCommands(Mock(context={'config': {'product': 'G系列', 'model': 'G1', 'package': 'test'}}))


def test_counts_defaults_and_cleanup(monkeypatch):
    monkeypatch.setattr('studio.ble_commands.time.sleep', lambda _: None)
    p = media()
    p._click = Mock()
    p._hold = Mock()
    p._ensure_duration = Mock()
    p.take_photo(3)
    assert p._click.call_count == 3
    p._click.reset_mock()
    p.record_video(count=2)
    assert [c.args[0] for c in p._click.call_args_list] == ['start_video', 'stop_video'] * 2
    p._ensure_duration.assert_called_once_with('video', 15)
    assert [c.args[0] for c in p._hold.call_args_list] == [15, 15]
    p._click.reset_mock()
    p._hold.side_effect = RuntimeError('interrupted')
    with pytest.raises(RuntimeError):
        p.record_audio(duration=40)
    assert [c.args[0] for c in p._click.call_args_list] == ['start_audio', 'stop_audio']
    assert p.a.driver.press_keycode.call_count == 3


def test_permission_page_repairs_media_permissions_and_retries(monkeypatch):
    a = Mock(context={'config': {'product': 'G系列', 'model': 'G3', 'package': 'test'}})
    a.driver.current_activity = 'HomeActivity'
    tab = Mock()
    tab.is_displayed.return_value = True
    title = Mock(text='Permission')
    title.is_displayed.return_value = True
    button = Mock()
    button.is_displayed.return_value = True
    a.driver.find_elements.side_effect = lambda by, value: (
        [tab] if value.endswith(':id/tabIcon') else
        [title] if value.endswith(':id/title_tv') and a.driver.current_activity == 'PermissionActivity' else
        [button] if value.endswith(tuple(':id/' + name for name, _ in BleMediaCommands.BUTTONS.values())) else [])
    a.wait.side_effect = lambda predicate, *_: predicate()
    entries = iter(('PermissionActivity', BleMediaCommands.ACTIVITY))
    menu = Mock()
    menu.click.side_effect = lambda: setattr(a.driver, 'current_activity', next(entries))
    home = Mock()
    home.return_value.text.return_value = menu
    monkeypatch.setattr('studio.ble_commands.HomeDevicePage', home)
    a.driver.press_keycode.side_effect = lambda _: setattr(a.driver, 'current_activity', 'HomeActivity')
    page = BleMediaCommands(a)
    page._enable_media_permissions = Mock()
    page.open()
    page._enable_media_permissions.assert_called_once_with()
    assert menu.click.call_count == 2


def test_permission_setup_turns_on_only_disabled_items():
    p = media()
    enabled = {'Photos': False, 'Microphone': True}
    rows = {}
    for label in enabled:
        row = Mock()
        row.is_displayed.return_value = True
        row.click.side_effect = lambda name=label: enabled.__setitem__(name, True)
        row.find_elements.side_effect = lambda *_args, name=label: [Mock(text='ON', is_displayed=Mock(return_value=True))] if enabled[name] else []
        rows[label] = row
    p.a.driver.find_elements.side_effect = lambda _, xpath: [rows[label] for label in rows if f"@text='{label}'" in xpath]
    p.a.wait.side_effect = lambda predicate, *_: predicate()
    p._enable_media_permissions()
    rows['Photos'].click.assert_called_once_with()
    rows['Microphone'].click.assert_not_called()


def test_every_media_click_observes_three_second_interval(monkeypatch):
    a = Mock(context={'config': {'product': 'G系列', 'model': 'G1', 'package': 'test'}})
    p = BleMediaCommands(a)
    p.open = Mock()
    a.wait.return_value = Mock(text='拍照')
    clock = iter((10, 11, 13))
    monkeypatch.setattr('studio.ble_commands.time.monotonic', lambda: next(clock))
    sleep = Mock()
    monkeypatch.setattr('studio.ble_commands.time.sleep', sleep)
    p._click('take_photo')
    p._click('take_photo')
    sleep.assert_called_once_with(2)


@pytest.mark.parametrize('count', [0, -1, 1.5, True])
def test_bad_count_never_operates(count):
    p = media()
    p._click = Mock()
    with pytest.raises(ValueError):
        p.take_photo(count)
    p._click.assert_not_called()


@pytest.mark.parametrize('kind,duration', [('video',721),('audio',7201),('video',0),('audio',float('nan')),('video',True)])
def test_bad_duration_never_prepares(kind, duration):
    p = media()
    p._ensure_duration = Mock()
    with pytest.raises(ValueError):
        getattr(p, 'record_' + kind)(duration=duration)
    p._ensure_duration.assert_not_called()


def test_setting_sufficient_or_select_smallest_and_read_back(monkeypatch):
    monkeypatch.setattr('studio.ble_commands.HomeDevicePage', Mock())
    p = media()
    p.a.find.return_value = None
    p._read_duration = Mock(return_value=180)
    p._duration_row = Mock()
    p._ensure_duration('video', 15)
    p._duration_row.assert_not_called()
    p._read_duration.side_effect = [180, 720]
    options = [Mock(text='3Min'), Mock(text='12Min')]
    p.a.wait.side_effect = [options, True]
    p._ensure_duration('video', 600)
    options[0].click.assert_not_called()
    options[1].click.assert_called_once()
    p._read_duration.side_effect = [180, 180]
    p.a.wait.side_effect = [options, True]
    with pytest.raises(TestBlocked, match='未生效'):
        p._ensure_duration('video', 600)


def test_unset_duration_is_selected_instead_of_blocked(monkeypatch):
    monkeypatch.setattr('studio.ble_commands.HomeDevicePage', Mock())
    p = media()
    p.a.find.return_value = None
    p._duration_row = Mock()
    p._duration_row.return_value.find_elements.return_value = []
    assert p._read_duration('Video Duration') is None
    p._read_duration = Mock(side_effect=[None, 180])
    option = Mock(text='3Min')
    p.a.wait.side_effect = [[option], True]
    p._ensure_duration('video', 15)
    option.click.assert_called_once_with()
