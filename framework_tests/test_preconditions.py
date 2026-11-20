from unittest.mock import Mock, patch

import pytest

from studio.preconditions import needs_business_preparation, prepare_business


@pytest.mark.parametrize('node,expected', [
    ('cases/g5/test_firmware_ota.py::test_g5_ota[isp-optional]', True),
    ('cases/g_series/test_g7.py::test_g7_device_settings', True),
    ('cases/g_series/test_g7.py::test_pair_flow_pro_pilot', False),
    ('cases/g_series/test_auth.py::test_auth[AUTH_001]', False),
    ('cases/g5/test_pairing.py::test_pair_flow_echo_pilot', False),
    ('cases/g5/test_device_management.py::test_g5_pending_media_unpair', True),
    ('cases/g_series/test_settings.py::test_system_single_unbind', True),
])
def test_business_preparation_scope(node, expected):
    assert needs_business_preparation(node) == expected


def test_fresh_login_restores_binding_with_skip_and_restores_options():
    android = Mock()
    android.find.return_value = False
    with patch('studio.auth.AuthPage') as auth, \
         patch('studio.home_device.HomeDevicePage') as home, \
         patch('studio.pairing.PairingPage') as pairing, \
         patch('studio.pairing.discovery_panel', return_value=None):
        auth.return_value.has.return_value = True
        options = {'skip_tutorial': False, 'require_pairing_prompt': True}
        pairing.return_value.options = options
        home.return_value.connected.side_effect = lambda: (
            options['skip_tutorial'] is True or pytest.fail('must skip tutorial'))
        prepare_business(android)
        auth.return_value.login_for_pairing.assert_called_once()
        home.return_value.connected.assert_called_once()
        assert options == {'skip_tutorial': False, 'require_pairing_prompt': True}


def test_existing_business_page_is_left_untouched():
    android = Mock()
    android.find.return_value = False
    with patch('studio.auth.AuthPage') as auth, \
         patch('studio.home_device.HomeDevicePage') as home, \
         patch('studio.pairing.discovery_panel', return_value=None):
        auth.return_value.has.return_value = False
        prepare_business(android)
        auth.return_value.registered.assert_not_called()
        home.assert_not_called()


def test_unbound_discovery_card_is_closed_before_account_navigation():
    android = Mock()
    android.find.return_value = False
    events = []
    with patch('studio.auth.AuthPage') as auth, \
         patch('studio.home_device.HomeDevicePage'), \
         patch('studio.pairing.PairingPage') as pairing, \
         patch('studio.pairing.discovery_panel', return_value=Mock()):
        auth.return_value.has.return_value = False
        auth.return_value.registered.side_effect = lambda: events.append('account')
        pairing.return_value.options = {'skip_tutorial': False, 'require_pairing_prompt': True}
        pairing.return_value.cancel_discovery.side_effect = lambda: events.append('cancel')
        prepare_business(android)
    assert events == ['cancel', 'account']
