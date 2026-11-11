import unittest

from studio.errors import TestBlocked
from studio.nova_ota import firmware_version, target_for_current, assert_result


class FakeAdb:
    def __init__(self, value):
        self.value = value

    def shell(self, serial, *args):
        assert serial == 'B4900PA25JA0F9'
        assert args == ('getprop', 'ro.build.dp_customer.version')
        return self.value


class NovaOtaTests(unittest.TestCase):
    def test_nova_target_boundaries(self):
        self.assertEqual(target_for_current('7.33.0', 'upgrade')['task_id'], 167)
        self.assertEqual(target_for_current('V7.33.1', 'downgrade')['task_id'], 168)
        with self.assertRaisesRegex(TestBlocked, '当前实际版本 7.33.2'):
            target_for_current('7.33.2', 'upgrade')

    def test_nova_usb_version_and_downgrade_result(self):
        serial = 'B4900PA25JA0F9'
        self.assertEqual(firmware_version(serial, FakeAdb('G1PV002SP_7.33.2')), '7.33.2')
        target = target_for_current('7.33.1', 'downgrade')
        self.assertIn('提示解绑属于预期', assert_result(serial, target, FakeAdb('G1PV002SP_7.33.0')))
        with self.assertRaisesRegex(AssertionError, '实际版本未达到目标'):
            assert_result(serial, target, FakeAdb('G1PV002SP_7.33.1'))
