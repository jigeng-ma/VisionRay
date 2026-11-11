import unittest
from unittest.mock import Mock
from xml.etree import ElementTree as ET

from studio.nova_events import NovaSimulatedEvents


def screen(value):
    return ET.fromstring(f'''<hierarchy>
        <node resource-id="com.gzshixiang.sxservice:id/ed_type" text="{value}"
              bounds="[24,104][99,134]" />
        <node clickable="true" bounds="[24,239][168,266]">
            <node text="手机模拟事件" />
        </node>
    </hierarchy>''')


class NovaEventTests(unittest.TestCase):
    def test_asleep_screen_uses_back_once_before_dump(self):
        adb = Mock()
        adb.shell.side_effect = ['mWakefulness=Asleep', 'done', 'mWakefulness=Awake',
                                 'UI hierchary dumped to: /sdcard/visionray_nova_ui.xml',
                                 '<hierarchy />']
        NovaSimulatedEvents('B4900PA25JA0F9', adb)._screen()
        calls = [call.args[1:] for call in adb.shell.call_args_list]
        self.assertEqual(calls.count(('input', 'keyevent', '4')), 1)

    def test_replaces_old_code_and_taps_button_once(self):
        adb = Mock()
        adb.online.return_value = True
        adb.shell.return_value = 'mCurrentFocus=Window{com.gzshixiang.sxservice/.MainActivity}'
        command = NovaSimulatedEvents('B4900PA25JA0F9', adb)
        command._screen = Mock(side_effect=[screen('5'), screen('20')])
        command.send(20)
        calls = [call.args[1:] for call in adb.shell.call_args_list]
        self.assertEqual(calls.count(('input', 'tap', '96', '252')), 1)
        self.assertEqual(calls.count(('input', 'text', '20')), 1)
        self.assertEqual(calls.count(('input', 'keyevent', '67')), 1)

    def test_wrong_readback_does_not_send(self):
        adb = Mock()
        adb.online.return_value = True
        adb.shell.return_value = 'mCurrentFocus=Window{com.gzshixiang.sxservice/.MainActivity}'
        command = NovaSimulatedEvents('B4900PA25JA0F9', adb)
        command._screen = Mock(side_effect=[screen('5'), screen('5'), screen('5'), screen('5')])
        with self.assertRaisesRegex(RuntimeError, '未正确写入'):
            command.send(20)
        self.assertNotIn(('input', 'tap', '96', '252'),
                         [call.args[1:] for call in adb.shell.call_args_list])

    def test_rejects_unknown_code_before_touching_device(self):
        adb = Mock()
        with self.assertRaises(ValueError):
            NovaSimulatedEvents('B4900PA25JA0F9', adb).send(999)
        adb.online.assert_not_called()


if __name__ == '__main__':
    unittest.main()
