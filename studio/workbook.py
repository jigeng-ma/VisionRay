"""OOXML 定点回填：保留图片、样式和未修改的工作簿组件。"""
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
import posixpath
import re
import os

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
ROW = re.compile(r'<row\b[^>]*\br="(\d+)"[^>]*>.*?</row>', re.S)
CELL = re.compile(r'<c\b[^>]*?(?:/>|>.*?</c>)', re.S)
LABELS = {'PASS': '通过', 'FAIL': '失败', 'ERROR': '执行异常', 'BLOCKED': '阻塞',
          'NOT_IMPLEMENTED': '未实现', 'NOT_APPLICABLE': '不适用', 'SKIPPED': '跳过',
          'NOT_RUN': '未执行', 'INTERRUPTED': '中断', 'RUNNING': '执行中'}
EXCEL_LABELS = {'PASS': 'Passed', 'FAIL': 'Failed', 'ERROR': 'Block', 'BLOCKED': 'Block',
                'NOT_APPLICABLE': 'N/A', 'NOT_IMPLEMENTED': '', 'SKIPPED': '',
                'NOT_RUN': '', 'INTERRUPTED': ''}


def colnum(value):
    if not re.fullmatch('[A-Za-z]{1,3}', value):
        raise ValueError('列名请填写 A、L 等 Excel 列字母。')
    number = 0
    for ch in value.upper():
        number = number * 26 + ord(ch) - 64
    if number > 16384:
        raise ValueError('列名超出 Excel 范围。')
    return number


@dataclass(frozen=True)
class Mapping:
    header_row: int = 0  # 0 自动识别每个 Sheet 的表头
    id_col: str = 'A'
    result_col: str = 'L'

    def validate(self):
        if self.header_row < 0:
            raise ValueError('表头行不能为负数；0 表示自动识别。')
        cols = [colnum(self.id_col), colnum(self.result_col)]
        if cols[0] == cols[1]:
            raise ValueError('编号列与结果列不能相同。')
        return cols


def parts(z):
    rels = {r.attrib['Id']: posixpath.normpath(posixpath.join('xl', r.attrib['Target']))
            if not r.attrib['Target'].startswith('/') else r.attrib['Target'].lstrip('/')
            for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
    w = ET.fromstring(z.read('xl/workbook.xml'))
    return [(s.attrib['name'], rels[s.attrib[REL]], s.attrib.get('state', 'visible'))
            for s in w.find('m:sheets', NS)]


def strings(z):
    if 'xl/sharedStrings.xml' not in z.namelist():
        return []
    root = ET.fromstring(z.read('xl/sharedStrings.xml'))
    return [''.join(n.text or '' for n in item.iter() if n.tag.endswith('}t')) for item in root]


def value(raw, shared):
    cell = ET.fromstring(raw)
    if cell.find('f') is not None:
        return None, True
    v = cell.find('v')
    if cell.attrib.get('t') == 's':
        return shared[int(v.text)] if v is not None else None, False
    if cell.attrib.get('t') == 'inlineStr':
        return ''.join(n.text or '' for n in cell.iter('t')), False
    return v.text if v is not None else None, False


def read_sheet(xml, shared, mapping):
    rows, warnings, seen = [], [], set()
    ignored = 0
    header = mapping.header_row or None
    idcol = mapping.id_col.upper()
    header_aliases = {'用例编号', '用例ID', '用例 ID', 'Case ID', 'case_id', '测试编号'}
    for match in ROW.finditer(xml):
        body = match.group()
        if '<v' not in body and '<is' not in body:
            continue
        number = int(match[1])
        cells = {}
        for c in CELL.finditer(body):
            address = re.search(r'\br="([A-Z]+)\d+"', c.group())
            if address:
                cells[address[1]] = c.group()
        if not header:
            if number <= 20 and idcol in cells:
                candidate, _ = value(cells[idcol], shared)
                if candidate in header_aliases:
                    header = number
            continue
        if number <= header:
            continue
        if set(cells) <= {idcol}:
            ignored += 1
            continue
        cid, formula = value(cells[idcol], shared) if idcol in cells else (None, False)
        if formula:
            raise ValueError(f'第 {number} 行编号是公式，无法作为稳定编号。')
        if cid is None or not cid.strip():
            # 有业务标题或步骤却缺编号才提示；图片和空白格式行忽略。
            if any(value(cells[c], shared)[0] for c in ('F', 'H') if c in cells):
                warnings.append(f'第 {number} 行缺少编号')
            continue
        if cid in seen:
            warnings.append(f'重复编号：{cid}（第 {number} 行）')
        seen.add(cid)
        title = value(cells.get('F', '<c/>'), shared)[0] or ''
        rows.append({'id': cid, 'row': number, 'title': title})
    return {'cases': rows, 'warnings': warnings, 'header': header, 'ignored_id_only': ignored,
            'reason': '' if header else '未识别到用例表头（汇总页或空表）'}


def inspect(path, mapping):
    mapping.validate()
    if Path(path).suffix.lower() != '.xlsx':
        raise ValueError('第一版支持 .xlsx 文件。')
    result = {}
    with ZipFile(path) as z:
        shared = strings(z)
        for name, part, state in parts(z):
            try:
                module = read_sheet(z.read(part).decode('utf-8'), shared, mapping)
            except ValueError as exc:
                raise ValueError(f'Sheet「{name}」：{exc}') from exc
            for case in module['cases']:
                case['sheet'] = name
            module.update(hidden=state != 'visible', part=part)
            result[name] = module
    return result


def export(source, destination, mapping, records):
    modules = inspect(source, mapping)
    destination = Path(destination)
    if destination.resolve() == Path(source).resolve() or destination.exists():
        raise ValueError('必须生成新结果文件，不能覆盖模板或已有轮次。')
    lookup = {(r['sheet'], r['id']): r for r in records}
    known = {(s, c['id']) for s, m in modules.items() for c in m['cases']}
    if set(lookup) - known:
        raise ValueError('结果与模板编号不匹配。')
    temporary = destination.with_suffix('.tmp.xlsx')
    try:
        with ZipFile(source) as src, ZipFile(temporary, 'w') as out:
            by_part = {m['part']: (name, m) for name, m in modules.items() if m['cases']}
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename in by_part:
                    name, module = by_part[info.filename]
                    target = {c['row']: c for c in module['cases']}
                    xml = data.decode('utf-8')
                    def replace_row(match):
                        number = int(match[1])
                        if number not in target:
                            return match.group()
                        address = f'{mapping.result_col.upper()}{number}'
                        case = target[number]
                        status = lookup.get((name, case['id']), {}).get('status', 'NOT_RUN')
                        text = EXCEL_LABELS[status]
                        body = match.group()
                        old = next((m for m in CELL.finditer(body) if re.search(r'\br="' + address + r'"', m.group())), None)
                        style = ''
                        if old:
                            if '<f' in old.group():
                                raise ValueError(f'{name}!{address} 为公式，不能回填。')
                            sm = re.search(r'\bs="\d+"', old.group())
                            style = ' ' + sm.group() if sm else ''
                        cell = f'<c r="{address}"{style} t="inlineStr"><is><t>{escape(text)}</t></is></c>' if text else f'<c r="{address}"{style}/>'
                        if old:
                            return body[:old.start()] + cell + body[old.end():]
                        following = next((m for m in CELL.finditer(body) if colnum(re.search(r'\br="([A-Z]+)', m.group())[1]) > colnum(mapping.result_col)), None)
                        at = following.start() if following else body.rfind('</row>')
                        return body[:at] + cell + body[at:]
                    data = ROW.sub(replace_row, xml).encode('utf-8')
                elif info.filename == 'xl/workbook.xml':
                    xml = data.decode('utf-8')
                    calc = '<calcPr calcId="0" fullCalcOnLoad="1" forceFullCalc="1"/>'
                    xml = re.sub(r'<calcPr\b[^>]*/>', calc, xml) if '<calcPr' in xml else xml.replace('</workbook>', calc + '</workbook>')
                    data = xml.encode('utf-8')
                elif info.filename.startswith('xl/worksheets/') and info.filename.endswith('.xml'):
                    # 清理未修改汇总页中的公式缓存，保留公式，交给 Excel 打开时重算。
                    xml = data.decode('utf-8')
                    data = CELL.sub(lambda m: re.sub(r'<v(?:\s[^>]*)?>.*?</v>', '', m.group(), flags=re.S) if '<f' in m.group() else m.group(), xml).encode('utf-8')
                out.writestr(info, data)
        with ZipFile(temporary) as verify:
            if verify.testzip():
                raise RuntimeError('输出文件完整性校验失败。')
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
