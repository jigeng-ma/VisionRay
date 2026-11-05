import collections
import hashlib
import html
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
import urllib.request
from datetime import datetime
from dataclasses import asdict
from .devices import Adb
from .workbook import inspect, export


def ordered_plan(cases, selected, entries):
    sheet_order = {name: index for index, name in enumerate(selected)}
    return sorted(cases, key=lambda case: (sheet_order[case['sheet']],
                  entries.get((case['sheet'], case['id']), {}).get('execution_order', 100000), case['row']))


def case_applies(item, config):
    return (not item.get('models') or config['model'] in item['models']) and (not item.get('products') or config['product'] in item['products'])


def save_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def unbind_before_reinstall(root, context, adb, emit):
    """卸载现有 APP 前尽量解除当前眼镜绑定。"""
    package = context['config']['package']
    installed = adb.shell(context['phone'], 'pm', 'list', 'packages', package)
    if f'package:{package}' not in installed.splitlines():
        return
    from .service import start
    from .android import Android
    from .home_device import HomeDevicePage
    emit('service', '卸载前检查眼镜绑定状态…')
    android = None
    binding_confirmed = False
    try:
        start(root)
        android = Android(context).connect()
        android.ensure_foreground()
        page = HomeDevicePage(android)
        for _ in range(7):
            if android.find('pair.add') or android.find('pair.models_title'):
                emit('service', '当前未绑定眼镜，继续安装。')
                return
            if android.find('pair.home_title') or android.find('pair.tutorial_begin'):
                binding_confirmed = True
                page.unbind()
                emit('service', '已解绑眼镜，继续安装。')
                return
            source = android.driver.page_source
            if any(f'{package}:id/{marker}' in source for marker in
                   ('tv_login_by_email', 'll_user_privacy', 'tvPolicyTitle')):
                emit('service', 'APP 尚未登录或仍在首次启动页，继续安装。')
                return
            android.driver.press_keycode(4)
            time.sleep(.4)
        emit('service', '卸载前无法确认眼镜绑定状态，继续卸载安装。')
    except Exception as exc:
        if binding_confirmed:
            raise
        emit('service', f'卸载前无法确认眼镜绑定状态（{exc}），继续卸载安装。')
    finally:
        if android is not None:
            android.close()


def pairing_result(status, detail, case_dir, glasses_name):
    """仅将确实停在目标眼镜搜索阶段的结果标记为执行异常。"""
    missing = '搜索不到目标眼镜' in detail or any(
        f'{label}{glasses_name}' in detail
        for label in ('等待超时：搜索目标眼镜 ', '等待超时：重搜目标眼镜 ')
    )
    if not missing and status == 'ERROR' and detail.startswith('用例超时'):
        steps = case_dir / 'steps.jsonl'
        if steps.is_file():
            search_events = ('search-started', 'pair-search-retry', 'target-found', 'bind')
            last = None
            for line in steps.read_text(encoding='utf-8').splitlines():
                try:
                    event = json.loads(line).get('event')
                except ValueError:
                    continue
                if event in search_events:
                    last = event
            missing = last in search_events[:2]
    if missing:
        return 'ERROR', f'搜索不到目标眼镜 {glasses_name}'
    return status, detail


def write_report(folder, run_id, context, records, entries):
    from .report import write_report as render_report
    render_report(folder, run_id, context, records, entries)


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
    # 新工作簿将同型号的各模块合并在一个 Sheet；保留旧 Sheet 键以兼容历史工作簿。
    if product in ('G系列', 'G7'):
        aliases = {'G00_登录注册': 'APP_注册登录'}
        model_sheet = 'G7' if product == 'G7' else 'G1_G3_G6'
        for (sheet, case_id), item in list(found.items()):
            if sheet == '基础项':
                continue
            if sheet == 'G00_登录注册':
                target_sheet = aliases[sheet]
            else:
                if product == 'G7' and item.get('models') == ['G7']:
                    pass
                elif product == 'G系列' and item.get('models') == ['G7']:
                    continue
                target_sheet = model_sheet
            alias = dict(item, sheet=target_sheet)
            if target_sheet in ('G1_G3_G6', 'G7'):
                # 合并 Sheet 的行顺序就是执行顺序；旧模块的优先级不能跨模块混排。
                alias.pop('execution_order', None)
            if product == 'G7' and target_sheet == 'G7' and not item.get('models'):
                alias['models'] = ['G7']
            elif product == 'G系列' and target_sheet == 'G1_G3_G6' and item.get('models'):
                alias['models'] = [model for model in item['models'] if model in ('G1', 'G3', 'G6')]
            found[(target_sheet, case_id)] = alias
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


def sheet_runs(selected, contexts, sheet_targets=None):
    """按工作簿顺序分组；相邻且使用同一设备的 Sheet 共用一次执行轮次。"""
    if sheet_targets is None:
        return [(context, list(selected)) for context in contexts]
    if set(sheet_targets) != set(selected):
        raise ValueError('请为每个已选 Sheet 指定执行设备。')
    groups = []
    for sheet in selected:
        index = sheet_targets[sheet]
        if not isinstance(index, int) or not 0 <= index < len(contexts):
            raise ValueError(f'{sheet} 指定的执行设备已从队列移除，请重新选择。')
        if groups and groups[-1][0] == index:
            groups[-1][1].append(sheet)
        else:
            groups.append((index, [sheet]))
    return [(contexts[index], sheets) for index, sheets in groups]


def execute_many(root, source, mapping, selected, contexts, stop, emit, timeout=180, sheet_targets=None):
    """同一手机按 Sheet 顺序串行运行；前一组失败不影响下一组。"""
    root = Path(root).resolve()
    if not contexts:
        raise ValueError('型号执行队列为空。')
    batch_id = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    batch_folder = root / 'runs' / 'batches' / batch_id
    batch_folder.mkdir(parents=True)
    modules = inspect(source, mapping)
    runs = sheet_runs(selected, contexts, sheet_targets)
    total = sum(len(modules[sheet]['cases']) for sheet in selected) * (len(contexts) if sheet_targets is None else 1)
    results = []
    case_results = []
    summary = collections.defaultdict(collections.Counter)
    emit('batch_start', {'folder': str(batch_folder), 'total': total, 'models': len(runs)})
    with RunLock(root):
        for index, (context, run_sheets) in enumerate(runs, 1):
            if stop.is_set():
                break
            model = context['config']['model']
            emit('model_start', f'{index}/{len(runs)}  {model} · {context["glasses_name"]} · {", ".join(run_sheets)}')
            def forward(kind, value):
                if kind == 'run':
                    emit('model_run', dict(value, model=model))
                elif kind == 'exporting':
                    emit('service', f'{model}：正在生成结果文件…')
                elif kind in ('case', 'case_start'):
                    emit(kind, dict(value, model=model))
                elif kind == 'service':
                    emit(kind, f'{model}：{value}')
                else:
                    emit(kind, value)
            try:
                entries = registry(root, context['config']['product'])
                applicable = any((item := entries.get((sheet, case['id']))) and case_applies(item, context['config'])
                                 for sheet in run_sheets for case in modules[sheet]['cases'])
                if not applicable:
                    row = {'model': model, 'glasses_name': context['glasses_name'],
                           'status': 'NOT_IMPLEMENTED', 'folder': '',
                           'error': '所选模块暂无适用于此型号的自动化用例。', 'summary': {}, 'export': 'SKIPPED'}
                    emit('model_error', f'{model}：所选模块暂无适用的自动化用例，继续下一个型号。')
                else:
                    result = _execute(root, source, mapping, run_sheets, context, stop, forward, timeout)
                    manifest = result['manifest']
                    row = {'model': model, 'glasses_name': context['glasses_name'],
                           'status': manifest['state'], 'folder': result['folder'],
                           'error': manifest.get('error') or '', 'summary': result['summary'],
                           'export': manifest.get('export')}
                    for sheet in run_sheets:
                        summary[sheet].update(result['summary'].get(sheet, {}))
                    result_file = Path(result['folder']) / 'results.json'
                    if result_file.is_file():
                        for case_result in json.loads(result_file.read_text(encoding='utf-8')):
                            if case_result['sheet'] not in run_sheets:
                                continue
                            entry = entries.get((case_result['sheet'], case_result['id']), {})
                            case_results.append(dict(case_result, model=model,
                                                     glasses_name=context['glasses_name'],
                                                     automation_id=entry.get('automation_id', ''),
                                                     run_folder=result['folder']))
            except Exception as exc:
                row = {'model': model, 'glasses_name': context['glasses_name'],
                       'status': 'ERROR', 'folder': '', 'error': str(exc), 'summary': {}, 'export': 'ERROR'}
                emit('model_error', f'{model}：启动或准备失败：{exc}；继续下一个型号。')
            row['sheets'] = run_sheets
            results.append(row)
            save_json(batch_folder / 'batch.json', {'models': results, 'selected': selected,
                                                    'cases': case_results})
    rows = []
    for row in results:
        report = (f'<a href="../../{html.escape(Path(row["folder"]).name)}/report.html">打开报告</a>'
                  if row['folder'] else '')
        counts = collections.Counter()
        for sheet in selected:
            counts.update(row['summary'].get(sheet, {}))
        rows.append('<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
            *[html.escape(str(value)) for value in (row['model'], row['glasses_name'], row['status'],
                counts.get('PASS', 0), counts.get('FAIL', 0) + counts.get('ERROR', 0), row['error'])], report))
    detail_rows = []
    for case in case_results:
        report = f'../../{html.escape(Path(case["run_folder"]).name, quote=True)}/report.html'
        values = (case['model'], case['glasses_name'], case['sheet'], case['id'],
                  case['automation_id'], case['status'], case['detail'])
        detail_rows.append('<tr>' + ''.join(f'<td>{html.escape(str(value))}</td>' for value in values)
                           + f'<td><a href="{report}">打开报告</a></td></tr>')
    (batch_folder / 'report.html').write_text(
        '<!doctype html><meta charset="utf-8"><title>多型号串行执行结果</title>'
        '<h1>多型号串行执行结果</h1><table border="1" cellpadding="8">'
        '<tr><th>型号</th><th>眼镜</th><th>状态</th><th>通过</th><th>失败/异常</th><th>原因</th><th>报告</th></tr>'
        + ''.join(rows) + '</table><h2>用例明细</h2><table border="1" cellpadding="8">'
        '<tr><th>型号</th><th>眼镜</th><th>模块</th><th>用例编号</th><th>自动化编号</th>'
        '<th>状态</th><th>说明</th><th>报告</th></tr>'
        + ''.join(detail_rows) + '</table>', encoding='utf-8')
    manifest = {'state': 'INTERRUPTED' if stop.is_set() else 'COMPLETED',
                'export': 'SUCCESS' if all(r['export'] in ('SUCCESS', 'SKIPPED') for r in results) else 'ERROR',
                'export_error': '部分型号未生成结果；详见批次报告。',
                'model_errors': [r for r in results if r['status'] == 'ERROR']}
    return {'folder': str(batch_folder), 'summary': {k: dict(v) for k, v in summary.items()},
            'manifest': manifest, 'models': results, 'cases': case_results}


def _execute(root, source, mapping, selected, context, stop, emit, timeout):
    # 执行入口再次解析，防止绕过窗口时使用与名称不符的型号配置。
    from .config import resolve_device
    old = context.get('config', {})
    if old.get('product'):
        config = resolve_device(root, old['product'], old.get('model'), context['glasses_name'])
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
    from .pgyer import OVERSEAS_DOWNLOAD_PAGE, download, install, resolve_build
    requested_version = context.get('app_version', '')
    if not requested_version.endswith('-debug'):
        raise ValueError('执行时必须提供 debug 版本号。')
    current_variant = None

    def install_variant(variant):
        nonlocal current_variant
        if variant not in ('debug', 'release'):
            raise ValueError(f'未知 APP 版本类型：{variant}')
        if current_variant == variant:
            return
        version = requested_version if variant == 'debug' else requested_version.removesuffix('-debug')
        emit('service', f'正在从蒲公英定位并下载 {version} {variant} APP…')
        build_key = resolve_build(OVERSEAS_DOWNLOAD_PAGE, version, None, variant)
        filename = version
        safe_version = ''.join(c if c.isalnum() or c in '.-_' else '_' for c in filename)
        apk = download(build_key, root / 'work' / 'downloads' / f'VisionRay-{safe_version}.apk')
        unbind_before_reinstall(root, context, adb, emit)
        emit('service', f'正在卸载旧包并安装 {version} {variant} APP…')
        install(context['phone'], apk, context['config']['package'])
        installed = adb.shell(context['phone'], 'dumpsys', 'package', context['config']['package'])
        installed_versions = re.findall(r'(?m)^\s*versionName=([^\s]+)', installed)
        if version not in installed_versions:
            raise RuntimeError(f'安装后的 APP 版本与输入不符：期望 {version}，实际 {installed_versions or "未读取到"}')
        current_variant = variant

    # 全部用例默认 debug；仅由用例注册表 app_variant=release 覆盖。
    install_variant('debug')
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
    active_case = None
    try:
        for index, case in enumerate(plan):
            if stop.is_set():
                break
            key = (case['sheet'], case['id'])
            active_case = case
            item = entries.get(key)
            start = time.monotonic()
            status, detail = 'NOT_IMPLEMENTED', '此编号尚未关联自动化实现。'
            if item:
                if not adb.online(context['phone']) or (context.get('glasses') and not adb.online(context['glasses'])):
                    fatal = '所选设备断开，停止本轮后续执行。'
                    status, detail = 'ERROR', fatal
                elif not case_applies(item, context['config']):
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
                    install_variant(item.get('app_variant', 'debug'))
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
                    case_dir = folder / 'evidence' / (item.get('automation_id') or case['id'])
                    case_dir.mkdir(parents=True)
                    env = os.environ.copy()
                    env.pop('VISIONRAY_TEST_ACCOUNT', None)
                    if item.get('auth_account'):
                        env['VISIONRAY_TEST_ACCOUNT'] = item['auth_account']
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
                                case_timeout = item.get('timeout_seconds', timeout)
                                if case['sheet'] == 'G00_登录注册':
                                    case_timeout += 300  # 发码限频时等待 5 分钟后重试一次。
                                if time.monotonic() - start > case_timeout:
                                    reason = ('ERROR', f'用例超时（{case_timeout} 秒）。')
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
                    before_pairing = (status, detail)
                    status, detail = pairing_result(status, detail, case_dir, context['glasses_name'])
                    if (status, detail) != before_pairing:
                        save_json(case_dir / 'result.json', {'status': status, 'detail': detail})
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
        updated = connection.execute("UPDATE results SET status='ERROR',detail=? WHERE status='RUNNING'", (fatal,)).rowcount
        if not updated and active_case:
            updated = connection.execute("UPDATE results SET status='ERROR',detail=? WHERE sheet=? AND id=? AND status='NOT_RUN'",
                                        (fatal, active_case['sheet'], active_case['id'])).rowcount
            if updated:
                emit('case', dict(active_case, status='ERROR', detail=fatal, duration=0))
        connection.commit()
    finally:
        records = [dict(r) for r in connection.execute('SELECT * FROM results')]
        connection.close()
        summary = {name: dict(collections.Counter(r['status'] for r in records if r['sheet'] == name)) for name in modules}
        save_json(folder / 'summary.json', summary)
        save_json(folder / 'results.json', records)
        write_report(folder, run_id, context, records, entries)
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
