import json
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from xml.sax.saxutils import quoteattr
from studio.popups import PopupGuard, contains_device
from studio.errors import TestBlocked
from studio.config import resolve
from studio.pairing import BindingReturnedToModels, PairingPage
from studio.home_device import HomeDevicePage
from studio.android import Android
import framework_tests.test_core as core
fixture=core.fixture

ROOT = Path(__file__).resolve().parents[1]

class HomeSettingTests(unittest.TestCase):
    def test_system_entry_accepts_both_home_labels(self):
        for label in ('System', 'System Settings'):
            a = Mock(context={'config': {'package': 'app'}, 'glasses_name': 'G3'})
            entry = Mock(text=label)
            entry.is_displayed.return_value = True
            a.driver.find_elements.return_value = [entry]
            page = HomeDevicePage(a)
            page.home = Mock()
            page.setting('System Settings')
            entry.click.assert_called_once_with()

def xml(package, texts):
    return '<hierarchy>'+''.join('<node package='+quoteattr(package)+' text='+quoteattr(t)+'/>' for t in texts)+'</hierarchy>'

class PopupTests(unittest.TestCase):
    def setUp(self):
        self.a=Mock()
        self.a.context={'glasses_name':'DPVR G1_13E6','config':resolve(ROOT,'G系列','G1')}
        self.button=Mock()
        self.a.driver.find_elements.return_value=[self.button]
        self.guard=PopupGuard(self.a)

    def test_pair_only_target_and_active_flow(self):
        self.a.driver.page_source=xml('com.android.settings',['Bluetooth pairing request','Pair with DPVR G1_13E6?','Pair'])
        with self.assertRaises(TestBlocked):self.guard.handle()
        self.button.click.assert_not_called()
        self.guard.pairing_active=True
        self.assertTrue(self.guard.handle())
        self.button.click.assert_called_once()
        self.assertEqual(self.guard.pairing_accepted,1)

    def test_wrong_device_or_prefix_collision_never_accepted(self):
        self.guard.pairing_active=True
        for name in ['DPVR G1_9999','DPVR G1_13E60']:
            self.a.driver.page_source=xml('com.android.settings',['Bluetooth pairing request','Pair with '+name+'?','Pair'])
            with self.assertRaises(TestBlocked):self.guard.handle()
        self.button.click.assert_not_called()

    def test_chinese_system_dialog(self):
        self.guard.pairing_active=True
        self.a.driver.page_source=xml('com.android.settings',['蓝牙配对请求','是否与 DPVR G1_13E6 配对?','配对'])
        self.assertTrue(self.guard.handle())

    def test_update_requires_complete_signature_and_can_be_preserved(self):
        pkg=self.a.context['config']['package']
        self.a.driver.page_source=xml(pkg,['System Settings','Firmware Update'])
        self.assertFalse(self.guard.handle())
        self.a.driver.page_source=xml(pkg,['Firmware Update','Update Now','Cancel'])
        self.guard.preserve={'firmware_update'}
        self.assertFalse(self.guard.handle())
        self.guard.preserve.clear()
        self.assertTrue(self.guard.handle())
        self.a.driver.find_elements.assert_called_once()

    def test_firmware_full_page_with_back_button_is_not_treated_as_cancelable_popup(self):
        pkg = self.a.context['config']['package']
        self.a.driver.page_source = (f'<hierarchy><node package="{pkg}" text="Firmware Update"/>'
                                     f'<node package="{pkg}" text="Update Now"/>'
                                     f'<node package="{pkg}" resource-id="{pkg}:id/top_bar_back"/></hierarchy>')
        self.assertFalse(self.guard.handle())
        self.button.click.assert_not_called()

    def test_app_update_and_unknown_modal(self):
        pkg=self.a.context['config']['package']
        self.a.driver.page_source=xml(pkg,['New Update','Update','Cancel'])
        self.assertTrue(self.guard.handle())
        self.a.driver.page_source=xml(pkg,['Delete all data?','Cancel'])
        self.assertFalse(self.guard.handle())
        self.button.click.assert_called_once()

    def test_ambiguous_cancel_blocks(self):
        pkg=self.a.context['config']['package']
        self.a.driver.page_source=xml(pkg,['New Update','Update','Cancel'])
        self.a.driver.find_elements.return_value=[self.button,self.button]
        with self.assertRaises(TestBlocked):self.guard.handle()
        self.button.click.assert_not_called()

    def test_popup_storm_is_bounded(self):
        a=Android(self.a.context);a.driver=Mock();a.popups=Mock();a.popups.handle.return_value=True
        with patch('studio.android.time.sleep'):
            with self.assertRaises(TestBlocked):a.wait(lambda:True,'target')
        self.assertEqual(a.popups.handle.call_count,7)

class ScrollTests(unittest.TestCase):
    def test_g_series_switch_uses_one_rapid_eleven_tap_sequence(self):
        a=Mock();a.context={'config':{'package':'app','pairing':{'model_label_id':'label'}}}
        tabs=[Mock(),Mock(),Mock()]
        for tab in tabs: tab.is_displayed.return_value=True
        name=Mock();name.text='VisionRay';name.is_displayed.return_value=True
        a.driver.find_elements.return_value=tabs
        a.wait.side_effect=['models', Mock(), name, tabs, Mock()]
        with patch('studio.pairing.time.sleep'), patch.object(PairingPage, '_model_names', return_value=set()):
            PairingPage(a).enable_g_series_models()
        self.assertEqual(name.click.call_count,11)
        self.assertEqual(a.wait.call_count,5)

    def test_add_device_login_redirect_restores_account_before_models(self):
        a=Mock();a.context={'config':{'package':'app','pairing':{'model_label_id':'label'}}}
        a.wait.side_effect=['login', Mock()]
        a.driver.find_elements.return_value=[Mock(text=name, is_displayed=Mock(return_value=True))
                                             for name in ('DPVR G1', 'DPVR G3', 'DPVR G6')]
        with patch('studio.auth.AuthPage') as auth, patch.object(
            PairingPage, '_model_names', return_value={'DPVR G1', 'DPVR G3', 'DPVR G6'}):
            PairingPage(a).enable_g_series_models()
        auth.return_value.registered.assert_called_once_with()
        self.assertEqual(a.click.call_args_list[:2], [unittest.mock.call('pair.add')] * 2)

    def test_checks_last_page_even_when_scroll_returns_false(self):
        a=Mock();a.context={'config':{'pairing':{'max_scrolls':12,'model_label_id':'label'}}}
        first=Mock();first.text='DPVR G1'
        last=Mock();last.text='DPVR G6'
        a.driver.find_elements.side_effect=[[first],[last]]
        a.driver.execute_script.return_value=False
        with patch('studio.pairing.time.sleep'), patch.object(PairingPage, '_scroll_models_top'):
            PairingPage(a).select_model('DPVR G6')
        last.click.assert_called_once();first.click.assert_not_called()

    def test_missing_g_model_enables_it_then_retries_once(self):
        a=Mock();a.context={'config':{'pairing':{'max_scrolls':0,'model_label_id':'label'}}}
        found=Mock();found.text='DPVR G1';found.is_displayed.return_value=True
        a.driver.find_elements.side_effect=[[], [], [found]]
        page=PairingPage(a);page.enable_g_series_models=Mock()
        page.select_model('DPVR G1')
        page.enable_g_series_models.assert_called_once()
        found.click.assert_called_once()

class RoutingTests(unittest.TestCase):
    setUp = core.CoreTests.setUp
    @patch('studio.runner.Adb')
    def test_model_filter_and_bluetooth_only(self, adb):
        from studio.runner import execute
        fixture(self.file,{'G01_配对':self.rows})
        (self.root/'cases').mkdir()
        (self.root/'cases/test_stub.py').write_text('def test_case(): pass')
        entry={'sheet':'G01_配对','id':'001','node':'cases/test_stub.py::test_case','models':['G3'],'glasses_adb_required':False}
        (self.root/'cases/registry.json').write_text(json.dumps([entry]))
        adb.return_value.preflight.return_value={}
        adb.return_value.shell.return_value='versionName=1.2.42-debug'
        (self.root/'configs').mkdir()
        (self.root/'configs/catalog.json').write_bytes((ROOT/'configs/catalog.json').read_bytes())
        context={'phone':'p','glasses':None,'glasses_name':'DPVR G1_13E6','app_version':'1.2.42-debug',
                 'config':{'package':'app','model':'G1','configured':True}}
        with patch('studio.pgyer.resolve_build', return_value='test-build'), patch(
            'studio.pgyer.download', return_value=self.root/'app.apk'
        ), patch('studio.pgyer.install'):
            result=execute(self.root,self.file,__import__('studio.workbook',fromlist=['Mapping']).Mapping(),['G01_配对'],context,threading.Event(),lambda *a:None)
        self.assertEqual(result['summary']['G01_配对'],{'NOT_APPLICABLE':1})
        adb.return_value.online.assert_called_once_with('p')

class DelayedPairingTests(unittest.TestCase):
    def test_tutorial_alone_does_not_complete_required_pairing(self):
        a=Mock();a.context={'config':{'pairing':{'require_pairing_prompt':True,'late_popup_timeout':60,'optional_observation_seconds':30,'tutorial_activity':'tutorial'}}}
        a.driver.current_activity='tutorial';a.find.return_value=True;a.popups.pairing_accepted=0
        def wait(predicate,label,timeout):
            self.assertFalse(predicate())
            a.popups.pairing_accepted=1
            self.assertTrue(predicate())
        a.wait.side_effect=wait
        with patch('studio.pairing.time.monotonic',side_effect=[0,6,7]):
            PairingPage(a).observe_late_pairing()

    def test_optional_pairing_still_observes_a_window(self):
        a=Mock();a.context={'config':{'pairing':{'require_pairing_prompt':False,'late_popup_timeout':60,'optional_observation_seconds':30,'tutorial_activity':'tutorial'}}}
        a.driver.current_activity='tutorial';a.find.return_value=True;a.popups.pairing_accepted=0
        def wait(predicate,label,timeout):
            self.assertFalse(predicate())
            self.assertTrue(predicate())
        a.wait.side_effect=wait
        with patch('studio.pairing.time.monotonic',side_effect=[0,1,31]):
            PairingPage(a).observe_late_pairing()

class HomeCompletionTests(unittest.TestCase):
    def test_app_binding_failure_reports_dialog_without_timeout(self):
        a = Mock()
        a.context = {'glasses_name': 'DPVR G3_ADA2', 'config': resolve(ROOT, 'G系列', 'G3')}
        a.find.side_effect = lambda key: key == 'pair.binding_failed'
        a.wait.side_effect = lambda predicate, *_: predicate()
        with self.assertRaisesRegex(AssertionError, 'Binding Failed'):
            PairingPage(a).finish_binding()
        a.capture.assert_called_once_with('binding-failed')

    def test_bluetooth_prompt_is_accepted_before_skipping_tutorial(self):
        a = Mock()
        a.context = {'glasses_name': 'DPVR G3_ADA2', 'config': resolve(ROOT, 'G系列', 'G3')}
        a.context['config']['pairing']['skip_tutorial'] = True
        a.popups.pairing_accepted = 0
        page = PairingPage(a)
        page.on_tutorial = Mock(return_value=True)
        page.on_target_home = Mock(return_value=True)
        a.find.return_value = False
        def wait(predicate, label, *_):
            if label == '引导页蓝牙配对确认或等待已配对设备':
                a.popups.pairing_accepted = 1
            return predicate()
        a.wait.side_effect = wait
        def click(key):
            if key == 'pair.skip':
                self.assertEqual(a.popups.pairing_accepted, 1)
        a.click.side_effect = click
        page.observe_late_pairing = Mock()
        page.finish_binding()
        page.observe_late_pairing.assert_called_once_with()

    def test_model_page_after_bind_fails_without_retry(self):
        a = Mock()
        a.context = {'glasses_name': 'DPVR G1_13E6', 'config': resolve(ROOT, 'G系列', 'G1')}
        page = PairingPage(a)
        page.prepare_search = Mock()
        page.bind = Mock(side_effect=BindingReturnedToModels('returned'))
        with self.assertRaisesRegex(BindingReturnedToModels, 'returned'):
            page.run()
        page.bind.assert_called_once_with()
        a.driver.press_keycode.assert_not_called()

    def test_return_to_model_selection_reports_incomplete_binding(self):
        a = Mock()
        a.context = {'glasses_name': 'DPVR G1_13E6', 'config': resolve(ROOT, 'G系列', 'G1')}
        a.context['config']['pairing']['skip_tutorial'] = True
        page = PairingPage(a)
        page.on_tutorial = Mock(return_value=True)
        a.find.side_effect = lambda key: key == 'pair.models_title'
        a.wait.side_effect = lambda predicate, *_: predicate()
        with self.assertRaisesRegex(AssertionError, '绑定未完成'):
            page.finish_binding()

    def test_home_requires_target_device(self):
        a=Mock();a.context={'glasses_name':'DPVR G1_13E6','config':resolve(ROOT,'G系列','G1')}
        page=PairingPage(a);a.driver.current_activity=page.options['home_activity'];a.find.return_value=True
        device=Mock();device.text='DPVR G1_9999';a.driver.find_elements.return_value=[device]
        self.assertFalse(page.on_target_home())
        device.text='DPVR G1_13E6'
        self.assertTrue(page.on_target_home())

    def test_late_pair_on_home_requires_confirmation(self):
        a=Mock();a.context={'glasses_name':'DPVR G1_13E6','config':resolve(ROOT,'G系列','G1')}
        a.context['config']['pairing']['skip_tutorial']=True
        page=PairingPage(a);a.driver.current_activity=page.options['home_activity'];a.find.return_value=True
        device=Mock();device.text='DPVR G1_13E6';a.driver.find_elements.return_value=[device]
        a.popups.pairing_accepted=0
        def wait(predicate,label,timeout):
            self.assertFalse(predicate())
            a.popups.pairing_accepted=1
            self.assertTrue(predicate())
        a.wait.side_effect=wait
        with patch('studio.pairing.time.monotonic',side_effect=[0,6,8]):
            page.observe_late_pairing()


class NameRoutingTests(unittest.TestCase):
    def test_name_overrides_manual_model(self):
        from studio.config import resolve_device
        for model in ['G1','G3','G6']:
            c=resolve_device(ROOT,'G系列','G1',f'DPVR {model}_ABC123')
            self.assertEqual(c['model'],model)
            self.assertEqual(c['pairing']['model_label'],'DPVR '+model)

    def test_reject_incomplete_or_unknown_names(self):
        from studio.config import model_from_name
        for name in ['','DPVR G1','DPVR G1_','DPVR G10_13E6','DPVR G2_13E6','other G1_13E6']:
            with self.assertRaises(ValueError):model_from_name(ROOT,name)

    def test_all_g_models_share_capabilities(self):
        configs=[resolve(ROOT,'G系列',m) for m in ['G1','G3','G6']]
        self.assertEqual(configs[0]['capabilities'],configs[1]['capabilities'])
        self.assertEqual(configs[1]['capabilities'],configs[2]['capabilities'])
