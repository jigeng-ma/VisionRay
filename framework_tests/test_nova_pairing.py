import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from studio.nova import NovaPage
from studio.runner import registry


class NovaPairingTests(unittest.TestCase):
    def test_registration_is_nova_only_and_numbered(self):
        entries = registry(Path(__file__).resolve().parents[1], 'Nova')
        nova = [item for (sheet, _), item in entries.items() if sheet == 'Nova']
        self.assertEqual({item['automation_id'] for item in nova},
                         {'VisionRay_0179', 'VisionRay_0180', 'VisionRay_0181', 'VisionRay_0182',
                          'VisionRay_0183', 'VisionRay_0184', 'VisionRay_0185', 'VisionRay_0186',
                          'VisionRay_0187', 'VisionRay_0188', 'VisionRay_0189',
                          'VisionRay_0190', 'VisionRay_0191', 'VisionRay_0192',
                          'VisionRay_0193', 'VisionRay_0194', 'VisionRay_0195',
                          'VisionRay_0196'})
        self.assertTrue(all(item['products'] == ['Nova'] and item['glasses_adb_required']
                            for item in nova))

    def test_pair_selects_usb_serial_suffix(self):
        android = Mock()
        android.context = {'config': {'package': 'app'}, 'glasses': 'B4900PA25JA0F9'}
        android.wait.side_effect = lambda fn, *_, **__: fn()
        with patch('studio.nova.NovaSimulatedEvents') as events:
            page = NovaPage(android)
            entry = Mock()
            add_device_calls = 0

            def element(label, resource=None):
                nonlocal add_device_calls
                if label == 'Add Device':
                    add_device_calls += 1
                    return entry if add_device_calls <= 2 else None
                return None if label == 'Binding Failed' else entry

            page._text = Mock(side_effect=element)
            page.contains = Mock(return_value=True)
            page.pair()
        self.assertIn(('SN:A25JA0F9',), [call.args for call in page._text.call_args_list])
        events.return_value.pairing_mode.assert_called_once()


if __name__ == '__main__':
    unittest.main()
