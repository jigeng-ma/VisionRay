import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape
from studio.workbook import Mapping, inspect, export
from studio.config import merge
from studio.runner import execute, RunLock, ordered_plan


def fixture(path, sheets):
    """小型工作簿测试夹具，不涉及用户模板改写。"""
    with ZipFile(path, 'w', ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets)+1)) + '</Types>')
        z.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + ''.join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, name in enumerate(sheets, 1)) + '</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets)+1)) + '</Relationships>')
        for i, (name, rows) in enumerate(sheets.items(), 1):
            xml = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            for n, values in enumerate(rows, 1):
                xml += f'<row r="{n}">' + ''.join(f'<c r="{col}{n}" t="inlineStr"><is><t>{escape(text)}</t></is></c>' for col, text in values.items()) + '</row>'
            z.writestr(f'xl/worksheets/sheet{i}.xml', xml + '</sheetData></worksheet>')
        z.writestr('custom/preserved.bin', b'unchanged-object')


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file = self.root / 'input.xlsx'
        self.rows = [{'A': '用例编号', 'F': '用例标题', 'L': '实际结果'}, {'A': '001', 'F': '测试', 'L': 'Passed'}]

    def test_header_rows_duplicates_and_id_only(self):
        fixture(self.file, {'模块': self.rows + [{'A': '001', 'F': '重复'}, {'A': '999'}], '第二行表头': [{'A': '说明'}] + self.rows, '空表': []})
        data = inspect(self.file, Mapping())
        self.assertEqual(data['第二行表头']['header'], 2)
        self.assertEqual(data['模块']['cases'][0]['id'], '001')
        self.assertEqual(len(data['模块']['warnings']), 1)
        self.assertEqual(data['模块']['ignored_id_only'], 1)
        self.assertEqual(data['空表']['cases'], [])

    def test_export_matches_ids_preserves_source_and_clears_unselected(self):
        fixture(self.file, {'模块': self.rows + [{'A': '002', 'F': '另一条', 'L': 'Failed'}], '未选': self.rows})
        original = self.file.read_bytes()
        target = self.root / 'result.xlsx'
        export(self.file, target, Mapping(), [{'sheet': '模块', 'id': '002', 'status': 'PASS'}])
        self.assertEqual(original, self.file.read_bytes())
        with ZipFile(target) as z:
            self.assertIn('Passed', z.read('xl/worksheets/sheet1.xml').decode())
            self.assertNotIn('Passed', z.read('xl/worksheets/sheet2.xml').decode())
            self.assertEqual(z.read('custom/preserved.bin'), b'unchanged-object')
        with self.assertRaises(ValueError):
            export(self.file, target, Mapping(), [])
        with self.assertRaises(ValueError):
            export(self.file, self.root/'bad.xlsx', Mapping(result_col='A'), [])

    def test_merge_isolated_overrides(self):
        base = {'capabilities': {'photo': True, 'video': False}, 'values': [1]}
        result = merge(base, {'capabilities': {'video': True}, 'values': [2]})
        self.assertTrue(result['capabilities']['photo'])
        self.assertTrue(result['capabilities']['video'])
        self.assertFalse(base['capabilities']['video'])
        self.assertEqual(result['values'], [2])

    @patch('studio.runner.Adb')
    def test_selection_persistence_and_no_fabricated_pass(self, adb):
        fixture(self.file, {'选择': self.rows, '未选择': self.rows})
        (self.root/'cases').mkdir()
        (self.root/'cases/registry.json').write_text('[]')
        adb.return_value.preflight.return_value = {}
        context = {'phone': 'p', 'glasses': 'g', 'glasses_name': '测试眼镜', 'config': {'package': 'test.app', 'model': 'test'}}
        out = execute(self.root, self.file, Mapping(), ['选择'], context, threading.Event(), lambda *a: None)
        self.assertEqual(out['summary']['选择'], {'NOT_IMPLEMENTED': 1})
        self.assertEqual(out['summary']['未选择'], {'NOT_RUN': 1})
        folder = Path(out['folder'])
        self.assertTrue((folder/'results.sqlite').exists())
        self.assertTrue((folder/'results.xlsx').exists())
        second = execute(self.root, self.file, Mapping(), ['选择'], context, threading.Event(), lambda *a: None)
        self.assertNotEqual(out['folder'], second['folder'])
        with RunLock(self.root):
            with self.assertRaises(RuntimeError):
                with RunLock(self.root):
                    pass

    @patch('studio.runner.Adb')
    def test_stop_preserves_not_run(self, adb):
        fixture(self.file, {'选择': self.rows})
        (self.root/'cases').mkdir()
        (self.root/'cases/registry.json').write_text('[]')
        adb.return_value.preflight.return_value = {}
        stop = threading.Event()
        stop.set()
        context = {'phone': 'p', 'glasses': 'g', 'glasses_name': '测试', 'config': {'package': 'test.app', 'model': 'test'}}
        out = execute(self.root, self.file, Mapping(), ['选择'], context, stop, lambda *a: None)
        self.assertEqual(out['manifest']['state'], 'INTERRUPTED')
        self.assertEqual(out['summary']['选择'], {'NOT_RUN': 1})

    @patch('studio.runner.subprocess.Popen')
    @patch('studio.runner.Adb')
    def test_stop_terminates_current_case_and_persists_interrupted(self, adb, popen):
        fixture(self.file, {'选择': self.rows + [{'A': '002', 'F': '后续用例'}]})
        (self.root/'cases').mkdir()
        (self.root/'cases/test_fake.py').write_text('def test_case(): pass')
        (self.root/'cases/registry.json').write_text(json.dumps([{'sheet':'选择','id':'001','node':'cases/test_fake.py::test_case','diagnostic':True}]), encoding='utf-8')
        adb.return_value.preflight.return_value = {}
        adb.return_value.online.return_value = True
        popen.return_value.poll.side_effect = [None, 0]
        class StopDuringCase(threading.Event):
            def wait(self, timeout=None):
                self.set()
                return True
        context = {'phone':'p','glasses':'g','glasses_name':'测试','config':{'package':'test.app','model':'test'}}
        out = execute(self.root, self.file, Mapping(), ['选择'], context, StopDuringCase(), lambda *a: None)
        popen.return_value.terminate.assert_called_once()
        self.assertEqual(out['summary']['选择'], {'INTERRUPTED':1,'NOT_RUN':1})

    def test_execution_order_keeps_guide_begin_and_done_contiguous(self):
        cases = [{'sheet': 'G02_使用引导', 'id': 'UG_001', 'row': 2},
                 {'sheet': 'G02_使用引导', 'id': 'UG_002', 'row': 3},
                 {'sheet': 'G02_使用引导', 'id': 'UG_003', 'row': 4}]
        entries = {('G02_使用引导', 'UG_001'): {'execution_order': 10},
                   ('G02_使用引导', 'UG_003'): {'execution_order': 20},
                   ('G02_使用引导', 'UG_002'): {'execution_order': 30}}
        self.assertEqual([c['id'] for c in ordered_plan(cases, ['G02_使用引导'], entries)],
                         ['UG_001', 'UG_003', 'UG_002'])

    def test_selected_modules_follow_excel_sheet_order(self):
        fixture(self.file, {'G00_登录注册': self.rows, 'G01_配对': self.rows,
                            'G02_使用引导': self.rows})
        # 输入模拟 UI 集合的任意枚举顺序；执行器应按工作簿顺序恢复。
        modules = inspect(self.file, Mapping())
        selected = [name for name in modules if name in {'G02_使用引导', 'G00_登录注册'}]
        self.assertEqual(selected, ['G00_登录注册', 'G02_使用引导'])

    def test_changed_workbook_rejected(self):
        fixture(self.file, {'选择': self.rows})
        with self.assertRaisesRegex(ValueError, '已发生变化'):
            execute(self.root, self.file, Mapping(), ['选择'], {'input_sha256':'old'}, threading.Event(), lambda *a:None)


if __name__ == '__main__':
    unittest.main(verbosity=2)
