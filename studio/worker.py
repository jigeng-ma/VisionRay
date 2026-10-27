"""每条用例在独立进程执行，隔离 pytest 导入缓存并支持超时停止。"""
import json
import re
import sys
from pathlib import Path
import pytest


class Recorder:
    def __init__(self):
        self.reports = []

    def pytest_runtest_logreport(self, report):
        self.reports.append({'when': report.when, 'outcome': report.outcome,
                             'properties': dict(report.user_properties), 'detail': str(report.longrepr) if report.longrepr else ''})


def failure_detail(report):
    """有明确断言消息时直接给工作台展示；完整 pytest 堆栈仍在 pytest.log。"""
    detail = report['detail']
    if report['when'] == 'call':
        match = re.search(r'^E\s+AssertionError:\s*(.+)$', detail, re.MULTILINE)
        if match:
            return match.group(1).strip()
    return detail


def main():
    plugin = Recorder()
    code = pytest.main([sys.argv[1], '-q', '--tb=short', '-p', 'no:cacheprovider'], plugins=[plugin])
    failed = [r for r in plugin.reports if r['outcome'] == 'failed']
    if failed:
        status = 'ERROR' if any(r['when'] != 'call' for r in failed) else 'FAIL'
        detail = '\n'.join(failure_detail(r) for r in failed)
    elif any(r['outcome'] == 'skipped' for r in plugin.reports):
        status, detail = ('BLOCKED' if any(r['properties'].get('studio_status') == 'BLOCKED' for r in plugin.reports) else 'SKIPPED'), '\n'.join(r['detail'] for r in plugin.reports if r['outcome'] == 'skipped')
    elif code == 0 and any(r['when'] == 'call' and r['outcome'] == 'passed' for r in plugin.reports):
        status = 'PASS'
        detail = next((r['properties'].get('studio_detail', '') for r in plugin.reports
                       if r['when'] == 'call' and r['outcome'] == 'passed'), '')
    else:
        status, detail = 'ERROR', f'pytest 未正常完成，用例收集或执行错误：{code}'
    Path(sys.argv[2]).write_text(json.dumps({'status': status, 'detail': detail}, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
