import tempfile
import threading
import unittest
import json
from pathlib import Path
from unittest.mock import Mock, patch

from studio.runner import execute_many, sheet_runs
from studio.ui import App


class MultiRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contexts = [
            {'config': {'product': 'G系列', 'model': model}, 'glasses_name': f'DPVR {model}_1234'}
            for model in ('G1', 'G3')]
        self.modules = {'G01_配对': {'cases': [{'sheet': 'G01_配对', 'id': 'PAIR_001'}]}}
        self.entries = {('G01_配对', 'PAIR_001'): {'models': ['G1', 'G3']}}

    @patch('studio.runner.registry')
    @patch('studio.runner.inspect')
    @patch('studio.runner._execute')
    def test_setup_failure_does_not_prevent_next_model(self, run, inspect, registry):
        inspect.return_value = self.modules
        registry.return_value = self.entries
        run.side_effect = [RuntimeError('first setup failed'),
                           {'folder': str(self.root / 'runs' / 'second'),
                            'summary': {'G01_配对': {'PASS': 1}},
                            'manifest': {'state': 'COMPLETED', 'export': 'SUCCESS'}}]
        events = []
        result = execute_many(self.root, self.root / 'input.xlsx', None, ['G01_配对'],
                              self.contexts, threading.Event(), lambda *event: events.append(event))
        self.assertEqual(run.call_count, 2)
        self.assertEqual([m['status'] for m in result['models']], ['ERROR', 'COMPLETED'])
        self.assertEqual(result['summary']['G01_配对']['PASS'], 1)
        self.assertIn('first setup failed', (Path(result['folder']) / 'batch.json').read_text(encoding='utf-8'))

    @patch('studio.runner.registry')
    @patch('studio.runner.inspect')
    @patch('studio.runner._execute')
    def test_failed_case_does_not_prevent_next_model(self, run, inspect, registry):
        inspect.return_value = self.modules
        registry.return_value = self.entries
        run.side_effect = [
            {'folder': str(self.root / 'runs' / 'first'), 'summary': {'G01_配对': {'FAIL': 1}},
             'manifest': {'state': 'COMPLETED', 'export': 'SUCCESS'}},
            {'folder': str(self.root / 'runs' / 'second'), 'summary': {'G01_配对': {'PASS': 1}},
             'manifest': {'state': 'COMPLETED', 'export': 'SUCCESS'}}]
        result = execute_many(self.root, self.root / 'input.xlsx', None, ['G01_配对'],
                              self.contexts, threading.Event(), lambda *_: None)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(result['summary']['G01_配对'], {'FAIL': 1, 'PASS': 1})

    @patch('studio.runner.registry')
    @patch('studio.runner.inspect')
    @patch('studio.runner._execute')
    def test_same_case_is_attributed_to_each_model(self, run, inspect, registry):
        inspect.return_value = self.modules
        registry.return_value = {('G01_配对', 'PAIR_001'):
                                 {'models': ['G1', 'G3'], 'automation_id': 'VisionRay_0001'}}
        for name, status in [('first', 'PASS'), ('second', 'FAIL')]:
            folder = self.root / 'runs' / name
            folder.mkdir(parents=True)
            (folder / 'results.json').write_text(json.dumps([
                {'sheet': 'G01_配对', 'id': 'PAIR_001', 'status': status,
                 'detail': '', 'duration': 1}]), encoding='utf-8')
        run.side_effect = [
            {'folder': str(self.root / 'runs' / name),
             'summary': {'G01_配对': {status: 1}},
             'manifest': {'state': 'COMPLETED', 'export': 'SUCCESS'}}
            for name, status in [('first', 'PASS'), ('second', 'FAIL')]]
        result = execute_many(self.root, self.root / 'input.xlsx', None, ['G01_配对'],
                              self.contexts, threading.Event(), lambda *_: None)
        self.assertEqual([(case['model'], case['id'], case['status']) for case in result['cases']],
                         [('G1', 'PAIR_001', 'PASS'), ('G3', 'PAIR_001', 'FAIL')])
        report = (Path(result['folder']) / 'report.html').read_text(encoding='utf-8')
        self.assertIn('VisionRay_0001', report)
        self.assertIn('DPVR G3_1234', report)

    @patch('studio.runner.registry')
    @patch('studio.runner.inspect')
    @patch('studio.runner._execute')
    def test_explicit_stop_prevents_next_model(self, run, inspect, registry):
        inspect.return_value = self.modules
        registry.return_value = self.entries
        stop = threading.Event()
        def first(*_):
            stop.set()
            return {'folder': str(self.root / 'runs' / 'first'),
                    'summary': {'G01_配对': {'INTERRUPTED': 1}},
                    'manifest': {'state': 'INTERRUPTED', 'export': 'SUCCESS'}}
        run.side_effect = first
        result = execute_many(self.root, self.root / 'input.xlsx', None, ['G01_配对'],
                              self.contexts, stop, lambda *_: None)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(result['manifest']['state'], 'INTERRUPTED')

    @patch('studio.runner.registry')
    @patch('studio.runner.inspect')
    @patch('studio.runner._execute')
    def test_unimplemented_model_is_skipped_without_installing(self, run, inspect, registry):
        inspect.return_value = self.modules
        registry.side_effect = [{}, self.entries]
        run.return_value = {'folder': str(self.root / 'runs' / 'second'),
                            'summary': {'G01_配对': {'PASS': 1}},
                            'manifest': {'state': 'COMPLETED', 'export': 'SUCCESS'}}
        result = execute_many(self.root, self.root / 'input.xlsx', None, ['G01_配对'],
                              self.contexts, threading.Event(), lambda *_: None)
        self.assertEqual(run.call_count, 1)
        self.assertEqual([m['status'] for m in result['models']], ['NOT_IMPLEMENTED', 'COMPLETED'])

    def test_sheet_assignment_preserves_excel_order_and_merges_adjacent_sheets(self):
        selected = ['A', 'B', 'C', 'D']
        runs = sheet_runs(selected, self.contexts, {'A': 1, 'B': 1, 'C': 0, 'D': 1})
        self.assertEqual([(context['config']['model'], sheets) for context, sheets in runs],
                         [('G3', ['A', 'B']), ('G1', ['C']), ('G3', ['D'])])
        with self.assertRaisesRegex(ValueError, '每个已选 Sheet'):
            sheet_runs(selected, self.contexts, {'A': 0})

    @patch('studio.runner.registry')
    @patch('studio.runner.inspect')
    @patch('studio.runner._execute')
    def test_only_assigned_sheets_run_on_each_device(self, run, inspect, registry):
        inspect.return_value = {
            sheet: {'cases': [{'sheet': sheet, 'id': f'{sheet}_001'}]}
            for sheet in ('A', 'B', 'C')}
        registry.return_value = {(sheet, f'{sheet}_001'): {'models': ['G1', 'G3']}
                                 for sheet in ('A', 'B', 'C')}
        run.return_value = {'folder': str(self.root / 'runs' / 'child'),
                            'summary': {}, 'manifest': {'state': 'COMPLETED', 'export': 'SUCCESS'}}
        execute_many(self.root, self.root / 'input.xlsx', None, ['A', 'B', 'C'],
                     self.contexts, threading.Event(), lambda *_: None,
                     sheet_targets={'A': 1, 'B': 1, 'C': 0})
        self.assertEqual([(call.args[4]['config']['model'], call.args[3]) for call in run.call_args_list],
                         [('G3', ['A', 'B']), ('G1', ['C'])])


class QueueContextTests(unittest.TestCase):
    def test_sheet_target_stays_with_named_device_after_queue_reorder(self):
        app = App.__new__(App)
        first = {'product': 'G系列', 'model': 'G1', 'glasses_name': 'DPVR G1_1111'}
        second = {'product': 'G系列', 'model': 'G1', 'glasses_name': 'DPVR G1_2222'}
        app.target_queue = [first, second]
        app.sheet_targets = {'G01_配对': App.target_key(second)}
        self.assertEqual(app.target_index('G01_配对'), 1)
        app.target_queue.reverse()
        self.assertEqual(app.target_index('G01_配对'), 0)

    def test_queue_keeps_user_order_and_separate_names(self):
        app = App.__new__(App)
        app.root_dir = Path(__file__).resolve().parents[1]
        app.target_queue = []
        app.devices_by_label = {}
        app.product = Mock(); app.product.get.return_value = 'G1/G3/G6'
        app.model = Mock(); app.model.get.return_value = 'G1'
        app.glasses = Mock(); app.glasses.get.return_value = ''
        app.glasses_name = Mock(); app.glasses_name.get.side_effect = ['DPVR G1_1111', 'DPVR G3_2222']
        app.render_targets = Mock(); app.refresh_coverage = Mock(); app.save_state = Mock()
        app.add_target()
        app.add_target()
        self.assertEqual([t['model'] for t in app.target_queue], ['G1', 'G3'])
        self.assertEqual([t['glasses_name'] for t in app.target_queue], ['DPVR G1_1111', 'DPVR G3_2222'])
        app.queue_view = Mock(); app.queue_view.selection.return_value = ('1',)
        app.move_target(-1)
        self.assertEqual([t['model'] for t in app.target_queue], ['G3', 'G1'])

    def test_non_nova_targets_never_reuse_usb_device(self):
        app = App.__new__(App)
        app.root_dir = Path(__file__).resolve().parents[1]
        app.target_queue = []
        app.extra_glasses = []
        app.devices_by_label = {'phone': Mock(serial='phone-serial')}
        app.phone = Mock(); app.phone.get.return_value = 'phone'
        app.skip_tutorial = Mock(); app.skip_tutorial.get.return_value = False
        app.app_version = Mock(); app.app_version.get.return_value = '1.2.45'
        app.version_placeholder = '如 1.2.39'
        target = {'product': 'G系列', 'model': 'G1', 'glasses_name': 'DPVR G1_1234',
                  'glasses_serial': 'stale-usb'}
        context = app.target_context(target)
        self.assertIsNone(context['glasses'])
        self.assertEqual(context['config']['model'], 'G1')
