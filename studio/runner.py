import collections
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
import html
import urllib.request
from datetime import datetime
from dataclasses import asdict
from .devices import Adb
from .workbook import inspect, export


def ordered_plan(cases, selected, entries):
    sheet_order = {name: index for index, name in enumerate(selected)}
    return sorted(cases, key=lambda case: (sheet_order[case['sheet']],
                  entries.get((case['sheet'], case['id']), {}).get('execution_order', 100000), case['row']))


def save_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def registry(root, product=None):
    cases = (Path(root) / 'cases').resolve()
    manifest = json.loads((cases / 'registry.json').read_text(encoding='utf-8'))
    if isinstance(manifest, list):
        # 兼容既有小型测试夹具；正式项目使用分产品注册表。
        groups = [(manifest, cases, None)]
    else:
        paths = [(manifest['common'], None)] if manifest.get('common') else []
        if product in manifest.get('products', {}):
            paths.append((manifest['products'][product], product))
        groups = []
        for relative, owner in paths:
            path = (cases / relative).resolve()
            if not path.is_relative_to(cases) or not path.is_file():
                raise ValueError('产品注册表路径无效：' + relative)
            groups.append((json.loads(path.read_text(encoding='utf-8')), path.parent, owner))
    found = {}
    for data, directory, owner in groups:
        for entry in data:
            item = dict(entry)
            key = (item['sheet'], item['id'])
            if key in found:
                raise ValueError(f'当前产品自动化注册表重复：{key}')
            node_path = (Path(root) / item['node'].split('::')[0]).resolve()
            if not node_path.is_relative_to(directory) or not node_path.is_file():
                raise ValueError(f'用例实现必须位于所属产品目录：{item["node"]}')
            if owner:
                item['products'] = [owner]
            found[key] = item
    return found


class RunLock:
    def __init__(self, root):
        self.path = Path(root) / 'runs/.execution.lock'

    def __enter__(self):
        self.path.parent.mkdir(exist_ok=True)
        self.file = self.path.open('a+b')
        self.file.seek(0)
        self.file.write(b'0')
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('此工作台已有测试正在执行，请先结束该轮次。')
        return self

    def __exit__(self, *args):
        self.file.close()


def execute(root, source, mapping, selected, context, stop, emit, timeout=180):
    root = Path(root).resolve()
    with RunLock(root):
        return _execute(root, source, mapping, selected, context, stop, emit, timeout)


def _execute(root, source, mapping, selected, context, stop, emit, timeout):
    # 执行入口再次解析，防止绕过窗口时使用与名称不符的型号配置。
    if context.get('config', {}).get('product') == 'G系列' or context.get('glasses_name', '').upper().startswith('DPVR G'):
        from .config import resolve_device
        old = context['config']
        config = resolve_device(root, old.get('product'), old.get('model'), context['glasses_name'])
        config['pairing']['skip_tutorial'] = old.get('pairing', {}).get('skip_tutorial', False)
        context = dict(context, config=config)
    input_hash = hashlib.sha256(Path(source).read_bytes()).hexdigest()
    if context.get('input_sha256') and context['input_sha256'] != input_hash:
        raise ValueError('Excel 已发生变化，请重新读取并选择模块。')
    modules = inspect(source, mapping)
    if hashlib.sha256(Path(source).read_bytes()).hexdigest() != input_hash:
        raise ValueError('读取期间 Excel 被修改，请重新读取。')
    if not selected or set(selected) - set(modules):
        raise ValueError('请至少选择一个有效模块。')
    # UI 用 set 保存勾选状态；执行时必须恢复 Excel Sheet 的原始排列，
    # 不能把 set 的无序遍历结果当成模块执行顺序。
    selected = [name for name in modules if name in selected]
    for name in selected:
        if not modules[name]['cases'] or modules[name]['warnings']:
            raise ValueError(f'模块「{name}」为空或存在缺失编号，请先修正。')
    entries = registry(root, context['config'].get('product'))
    adb = Adb()
    devices = adb.preflight(context['phone'], context['glasses'], context['config']['package'])
    if not context['glasses_name'].strip():
        raise ValueError('请填写眼镜名称。')
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    folder = root / 'runs' / run_id
    folder.mkdir(parents=True)
    shutil.copy2(source, folder / 'input.xlsx')
    source = folder / 'input.xlsx'
    if hashlib.sha256(source.read_bytes()).hexdigest() != input_hash:
        raise ValueError('创建执行快照期间 Excel 被修改，请重新读取。')
    manifest = dict(context, run_id=run_id, started=datetime.now().isoformat(), devices=devices,
                    mapping=asdict(mapping), selected=list(selected), state='RUNNING',
                    input_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    save_json(folder / 'manifest.json', manifest)
    save_json(folder / 'context.json', context)
    connection = sqlite3.connect(folder / 'results.sqlite')
    connection.row_factory = sqlite3.Row
    connection.execute('CREATE TABLE results (sheet TEXT, id TEXT, status TEXT, detail TEXT, duration REAL, PRIMARY KEY(sheet,id))')
    all_cases = list({(c['sheet'], c['id']): c for m in modules.values() for c in m['cases']}.values())
    connection.executemany('INSERT INTO results VALUES (?, ?, ?, ?, ?)',
                           [(c['sheet'], c['id'], 'NOT_RUN', '未选择模块' if c['sheet'] not in selected else '尚未执行', 0) for c in all_cases])
    connection.commit()
    plan = ordered_plan([c for c in all_cases if c['sheet'] in selected], selected, entries)
    emit('run', {'folder': str(folder), 'total': len(plan)})
    fatal = None
    appium_ready = False
    try:
        for index, case in enumerate(plan):
            if stop.is_set():
                break
            key = (case['sheet'], case['id'])
            item = entries.get(key)
            start = time.monotonic()
            status, detail = 'NOT_IMPLEMENTED', '此编号尚未关联自动化实现。'
            if item:
                if not adb.online(context['phone']) or (context.get('glasses') and not adb.online(context['glasses'])):
                    fatal = '所选设备断开，停止本轮后续执行。'
                    status, detail = 'ERROR', fatal
                elif (item.get('models') and context['config']['model'] not in item['models']) or (item.get('products') and context['config'].get('product') not in item['products']):
                    status, detail = 'NOT_APPLICABLE', '本轮选择的产品型号与该用例不符。'
                elif item.get('glasses_adb_required', True) and not context.get('glasses'):
                    status, detail = 'BLOCKED', '该用例需要眼镜 USB/ADB 连接，请选择眼镜设备。'
                elif not item.get('diagnostic') and not context['config'].get('configured'):
                    status, detail = 'BLOCKED', '产品型号能力尚未确认，请先补齐配置。'
                elif any(context['config'].get('capabilities', {}).get(c) is False for c in item.get('requires', [])):
                    status, detail = 'NOT_APPLICABLE', '此型号不支持所需功能。'
                elif any(context['config'].get('capabilities', {}).get(c) is None for c in item.get('requires', [])):
                    status, detail = 'BLOCKED', '用例所需能力尚未配置。'
                elif item.get('manual'):
                    status, detail = 'BLOCKED', '本版无人值守执行不支持所需实体动作。'
                else:
                    # 仅在第一条实际 UI 用例前检查服务。未实现、阻塞和筛选掉的用例
                    # 不应因为临时环境没有 Appium 配置而改变其结果。
                    if not appium_ready:
                        if (root / 'configs' / 'environment.json').is_file():
                            from .service import start as start_appium
                            emit('service', '正在检查 Appium 服务…')
                            start_appium(root)
                        appium_ready = True
                    connection.execute('UPDATE results SET status=? WHERE sheet=? AND id=?', ('RUNNING', *key))
                    connection.commit()
                    emit('case_start', case)
                    case_dir = folder / 'evidence' / f'{index + 1:05d}'
                    case_dir.mkdir(parents=True)
                    env = os.environ.copy()
                    env.update(GLASSES_RUN_CONTEXT=str(folder / 'context.json'), PYTHONIOENCODING='utf-8',
                               GLASSES_EVIDENCE_DIR=str(case_dir),
                               PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONPATH=os.pathsep.join([str(root), str(root / 'vendor')]))
                    with (case_dir / 'pytest.log').open('w', encoding='utf-8') as log:
                        command = [sys.executable, '--case-worker'] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'studio.worker']
                        process = subprocess.Popen([*command, item['node'], str(case_dir / 'result.json')],
                            cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=0x08000000 if os.name == 'nt' else 0)
                        reason = None
                        try:
                            while process.poll() is None:
                                if stop.wait(.15):
                                    reason = ('INTERRUPTED', '使用者停止执行。')
                                    break
                                if time.monotonic() - start > item.get('timeout_seconds', timeout):
                                    reason = ('ERROR', f'用例超时（{item.get("timeout_seconds", timeout)} 秒）。')
                                    break
                            if reason:
                                process.terminate()
                                process.wait(timeout=10)
                                status, detail = reason
                            elif (case_dir / 'result.json').exists():
                                answer = json.loads((case_dir / 'result.json').read_text(encoding='utf-8'))
                                status, detail = answer['status'], answer['detail']
                            else:
                                status, detail = 'ERROR', '执行子进程未生成结果，请查看 pytest.log。'
                        finally:
                            if process.poll() is None:
                                process.kill()
                                process.wait()
                            if reason and (case_dir/'session.json').exists():
                                try:
                                    session = json.loads((case_dir/'session.json').read_text(encoding='utf-8'))
                                    request = urllib.request.Request(session['url'].rstrip('/') + '/session/' + session['session_id'], method='DELETE')
                                    with urllib.request.urlopen(request, timeout=10):
                                        pass
                                except Exception as exc:
                                    (case_dir/'session-cleanup.txt').write_text(str(exc), encoding='utf-8')
                    if status in ('FAIL', 'ERROR'):
                        adb.evidence(context['phone'], case_dir)
            duration = time.monotonic() - start
            connection.execute('UPDATE results SET status=?,detail=?,duration=? WHERE sheet=? AND id=?', (status, detail, duration, *key))
            connection.commit()
            emit('case', dict(case, status=status, detail=detail, duration=duration))
            if fatal:
                break
    except Exception as exc:
        fatal = str(exc)
        connection.execute("UPDATE results SET status='ERROR',detail=? WHERE status='RUNNING'", (fatal,))
        connection.commit()
    finally:
        records = [dict(r) for r in connection.execute('SELECT * FROM results')]
        connection.close()
        summary = {name: dict(collections.Counter(r['status'] for r in records if r['sheet'] == name)) for name in modules}
        save_json(folder / 'summary.json', summary)
        save_json(folder / 'results.json', records)
        from .workbook import LABELS
        rows = ''.join('<tr>' + ''.join('<td>' + html.escape(str(r[k])) + '</td>' for k in ('sheet', 'id')) +
                       '<td>' + LABELS[r['status']] + '</td><td>' + html.escape(r['detail']) + '</td></tr>' for r in records)
        (folder / 'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>测试执行报告</title>'
            '<style>body{font:15px system-ui;margin:32px;color:#20334c}table{border-collapse:collapse;width:100%}td,th{border:1px solid #dbe2ed;padding:9px;text-align:left;white-space:pre-wrap}th{background:#eaf1fb}input{padding:10px;width:420px}</style>'
            '<h1>测试执行报告</h1><p>' + html.escape(run_id) + ' · ' + html.escape(context['config']['model']) +
            ' · 眼镜：' + html.escape(context['glasses_name']) + '</p><p>结果以本报告为准。未实现、未执行等状态在 Excel 中保留为空，避免计入原模板已执行数量。</p>'
            '<input placeholder="筛选模块、编号、状态或失败原因" oninput="document.querySelectorAll(\'tbody tr\').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(this.value.toLowerCase()))">'
            '<table><thead><tr><th>模块</th><th>编号</th><th>状态</th><th>说明</th></tr></thead><tbody>' + rows + '</tbody></table></html>', encoding='utf-8')
        manifest.update(state='ERROR' if fatal else 'INTERRUPTED' if stop.is_set() else 'COMPLETED',
                        finished=datetime.now().isoformat(), error=fatal)
        emit('exporting', str(folder))
        try:
            export(source, folder / 'results.xlsx', mapping, records)
            manifest['export'] = 'SUCCESS'
        except Exception as exc:
            manifest.update(export='ERROR', export_error=str(exc))
        save_json(folder / 'manifest.json', manifest)
    return {'folder': str(folder), 'summary': summary, 'manifest': manifest}
