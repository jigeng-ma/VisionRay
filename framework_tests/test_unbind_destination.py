from unittest.mock import Mock, patch

import pytest

from studio.home_device import HomeDevicePage


@pytest.mark.parametrize('state', ['empty', 'discovery'])
def test_g5_single_unbind_accepts_both_unbound_destinations(state):
    android = Mock(context={'glasses_name': 'DPVR G5-0791',
                            'config': {'package': 'test.app', 'model': 'G5'}})
    button = Mock()
    android.driver.find_elements.return_value = [button]
    android.find.side_effect = lambda key: state == 'empty' and key == 'pair.add'
    android.wait.side_effect = lambda predicate, *_: predicate()
    page = HomeDevicePage(android)
    page.pending_media_unpair_actions = Mock(return_value=None)
    with patch('studio.pairing.discovery_panel', return_value=Mock() if state == 'discovery' else None):
        assert page.unbind() is False
    button.click.assert_called_once()
