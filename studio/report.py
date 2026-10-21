"""Standalone HTML report for a completed test run."""

from collections import Counter, defaultdict
from html import escape
from pathlib import Path
import re

from .workbook import LABELS


STATUSES = ('PASS', 'FAIL', 'ERROR', 'BLOCKED', 'SKIPPED', 'INTERRUPTED',
            'NOT_IMPLEMENTED', 'NOT_APPLICABLE', 'NOT_RUN', 'RUNNING')
ACTIVE = ('PASS', 'FAIL', 'ERROR')
GROUPS = (
    ('通过', ('PASS',), 'PASS'),
    ('失败', ('FAIL', 'ERROR'), 'FAIL'),
    ('待处理', ('BLOCKED', 'SKIPPED', 'INTERRUPTED', 'NOT_RUN', 'RUNNING'), 'PENDING'),
    ('未覆盖', ('NOT_IMPLEMENTED', 'NOT_APPLICABLE'), 'UNCOVERED'),
)
STATUS_GROUP = {status: name for _, statuses, name in GROUPS for status in statuses}


def _brief(detail):
    lines = [line.strip() for line in str(detail or '').splitlines() if line.strip()]
    error = next((line[2:].strip() for line in reversed(lines) if line.startswith('E ')), None)
    if error:
        return error[:220]
    skipped = re.search(r'(?:Skipped|Blocked):\s*([^\n\r]+)', str(detail))
    if skipped:
        return skipped.group(1).rstrip("')")[:220]
    return (lines[0] if lines else '')[:220]


def write_report(folder, run_id, context, records, entries):
    folder = Path(folder)
    totals = Counter(record['status'] for record in records)
    modules = defaultdict(Counter)
    for record in records:
        modules[record['sheet']][record['status']] += 1

    total = len(records)
    executed = sum(totals[status] for status in ACTIVE)
    cards = [('用例总数', total, 'all'), ('实际执行', executed, 'all')]
    cards += [(label, sum(totals[status] for status in statuses), name)
              for label, statuses, name in GROUPS]
    card_html = ''.join(f'<div class="card {name}"><span>{escape(label)}</span><strong>{count}</strong></div>'
                        for label, count, name in cards)

    status_columns = ''.join(f'<th>{label}</th>' for label, _, _ in GROUPS)
    module_rows = []
    for module, counts in modules.items():
        count = sum(counts.values())
        cells = ''.join(f'<td class="num {name}">{sum(counts[s] for s in statuses) or "—"}</td>'
                        for _, statuses, name in GROUPS)
        module_rows.append(f'<tr><th scope="row">{escape(module)}</th><td class="num">{count}</td>'
                           f'<td class="num">{sum(counts[s] for s in ACTIVE)}</td>{cells}</tr>')

    detail_rows = []
    for record in records:
        module, case_id, status = record['sheet'], record['id'], record['status']
        automation_id = entries.get((module, case_id), {}).get('automation_id', '')
        evidence = folder / 'evidence' / automation_id if automation_id else None
        evidence_text = escape(automation_id) if automation_id else '—'
        if evidence and evidence.is_dir():
            evidence_text = f'<a href="evidence/{escape(automation_id, quote=True)}/">{evidence_text}</a>'
        detail = str(record.get('detail') or '')
        if detail:
            brief = escape(_brief(detail))
            explanation = (f'<details><summary>{brief}</summary><pre>{escape(detail)}</pre></details>'
                           if '\n' in detail or len(detail) > 220 else escape(detail))
        else:
            explanation = '—'
        detail_rows.append(f'<tr data-module="{escape(module, quote=True)}" data-group="{STATUS_GROUP[status]}">'
                           f'<td>{escape(module)}</td><td>{escape(case_id)}</td><td>{evidence_text}</td>'
                           f'<td><span class="badge {escape(status)}">{escape(LABELS[status])}</span></td>'
                           f'<td>{explanation}</td></tr>')

    options = ''.join(f'<option value="{escape(module, quote=True)}">{escape(module)}</option>' for module in modules)
    status_options = ''.join(f'<option value="{name}">{label}（{sum(totals[s] for s in statuses)}）</option>'
                             for label, statuses, name in GROUPS)
    model = escape(str(context.get('config', {}).get('model', '')))
    glasses = escape(str(context.get('glasses_name', '')))
    version = escape(str(context.get('app_version', '')))
    page = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>测试执行报告 · {escape(run_id)}</title>
<style>
:root{{--ink:#19304d;--muted:#66788f;--line:#dce5f0;--bg:#f5f8fc;--blue:#1557b0}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 "Microsoft YaHei UI",system-ui,sans-serif}}
main{{max-width:1500px;margin:auto;padding:28px}}h1{{margin:0 0 6px;font-size:27px}}h2{{font-size:19px;margin:0 0 16px}}
.meta{{color:var(--muted);margin:0 0 24px}}section{{background:white;border:1px solid var(--line);border-radius:12px;padding:20px;margin:18px 0;box-shadow:0 2px 9px #17345d0a}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}}.card{{border:1px solid var(--line);border-radius:9px;padding:11px 14px;display:flex;flex-direction:column;min-height:74px}}
.card span{{color:var(--muted);font-size:12px}}.card strong{{font-size:25px;line-height:1.4}}.card.PASS strong,.num.PASS{{color:#12805c}}.card.FAIL strong,.num.FAIL{{color:#c13c3c}}
.card.PENDING strong,.num.PENDING{{color:#ad6a06}}.note{{color:var(--muted);font-size:12px;margin:12px 0 0}}
.scroll{{overflow-x:auto}}table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid var(--line);padding:10px 9px;text-align:left;vertical-align:top}}thead th{{position:sticky;top:0;background:#eaf1fa;white-space:nowrap;z-index:1}}tbody tr:hover{{background:#f8fbff}}
.num{{text-align:center;min-width:57px}}.badge.PASS{{background:#d8f4e8;color:#08734f}}
.badge{{display:inline-block;border-radius:5px;padding:2px 7px;white-space:nowrap;background:#e9edf3;color:#42556c}}.badge.FAIL,.badge.ERROR{{background:#fde7e7;color:#a92929}}.badge.BLOCKED{{background:#fff0d4;color:#915900}}
.filters{{display:flex;flex-wrap:wrap;gap:9px;margin-bottom:12px}}input,select{{border:1px solid #bfccdd;border-radius:6px;padding:9px 11px;background:white;color:var(--ink);font:inherit}}input{{flex:1;min-width:240px}}.shown{{color:var(--muted);font-size:12px;margin:0 0 8px}}
a{{color:var(--blue)}}details summary{{cursor:pointer;max-width:850px;overflow-wrap:anywhere}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5f9;border-radius:6px;padding:12px;max-height:420px;overflow:auto;font:12px/1.5 Consolas,monospace}}
@media(max-width:700px){{main{{padding:12px}}section{{padding:14px}}h1{{font-size:23px}}}}
</style></head><body><main>
<h1>测试执行报告</h1><p class="meta">轮次 {escape(run_id)} · {model} · {glasses} · APP {version}</p>
<section><h2>本轮结果概要</h2><div class="cards">{card_html}</div>
<p class="note">实际执行＝通过＋失败（含执行异常）；待处理＝阻塞、跳过、未执行、中断；未覆盖＝未实现、不适用。明细仍保留原始状态。</p></section>
<section><h2>模块汇总</h2><div class="scroll"><table><thead><tr><th>模块</th><th>总数</th><th>实际执行</th>{status_columns}</tr></thead>
<tbody>{''.join(module_rows)}</tbody></table></div></section>
<section><h2>用例明细</h2><div class="filters"><input id="search" placeholder="搜索模块、用例编号、自动化编号或原因">
<select id="module"><option value="">全部模块</option>{options}</select><select id="status"><option value="">全部状态</option>{status_options}</select></div>
<p class="shown" id="shown"></p><div class="scroll"><table><thead><tr><th>模块</th><th>用例编号</th><th>自动化编号 / 证据</th><th>状态</th><th>说明</th></tr></thead>
<tbody id="cases">{''.join(detail_rows)}</tbody></table></div>
<p class="note">点击自动化编号在当前页面打开同名证据目录；点击说明可展开完整异常。未实现、未执行等状态在 Excel 中保留为空。</p></section>
</main><script>
const search=document.getElementById('search'),module=document.getElementById('module'),status=document.getElementById('status');
const rows=[...document.querySelectorAll('#cases tr')];
function filter(){{const q=search.value.trim().toLowerCase();let shown=0;for(const row of rows){{
const visible=(!module.value||row.dataset.module===module.value)&&(!status.value||row.dataset.group===status.value)&&(!q||row.textContent.toLowerCase().includes(q));
row.hidden=!visible;if(visible)shown++;}}document.getElementById('shown').textContent=`显示 ${{shown}} / ${{rows.length}} 条用例`;}}
for(const control of [search,module,status])control.addEventListener('input',filter);filter();
</script></body></html>'''
    (folder / 'report.html').write_text(page, encoding='utf-8')
