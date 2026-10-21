"""Read feedback records from the authenticated DPVR management portal."""

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path

from .ota import OtaClient


FIELDS = ('type', 'desc', 'device_log', 'app_log', 'attachment', 'phone_info',
          'app_version', 'device_type', 'device_sn', 'device_version',
          'followup', 'contact', 'created_at')


class _Table(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
        self.links = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'tr':
            self.row = []
        elif tag == 'td' and self.row is not None:
            self.cell, self.links = [], []
        elif self.cell is not None:
            for name in ('href', 'src'):
                if attrs.get(name):
                    self.links.append(attrs[name])

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == 'td' and self.cell is not None:
            value = ' '.join(' '.join(self.cell).split())
            self.row.append({'text': value, 'links': self.links})
            self.cell = self.links = None
        elif tag == 'tr' and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None


class FeedbackClient(OtaClient):
    """Uses the same login and cookie session as OTA management."""

    COMPONENT = 'feed-backs.feed-back-list'
    PATH = '/feedbacks'

    @staticmethod
    def _check_columns(snapshot):
        columns = json.loads(snapshot)['data']['columns'][0]
        actual = tuple(column[0]['field'] for column in columns)
        if actual != FIELDS:
            raise RuntimeError(f'反馈表格字段或顺序已变化：{actual}')

    @staticmethod
    def _rows(html):
        table = _Table()
        table.feed(html)
        result = []
        for cells in table.rows:
            if len(cells) != len(FIELDS):
                raise RuntimeError(f'反馈表格列数改变：期望 {len(FIELDS)}，实际 {len(cells)}。')
            record = {field: cell['text'] for field, cell in zip(FIELDS, cells)}
            record['links'] = {field: cell['links'] for field, cell in zip(FIELDS, cells)
                               if cell['links']}
            result.append(record)
        return result

    def list_feedbacks(self, page=1):
        if type(page) is not int or page < 1:
            raise ValueError('page 必须是正整数。')
        self.login()
        html = self._get(self.PATH)
        snapshot = self._component(html, self.COMPONENT)
        self._check_columns(snapshot)
        if page > 1:
            answer = self._post(snapshot, [{'path': '', 'method': 'gotoPage',
                                            'params': [page, 'page']}], self.PATH)
            component = answer['components'][0]
            actual = json.loads(component['snapshot'])['data']['paginators'][0]['page']
            if actual != page:
                raise ValueError(f'反馈列表没有第 {page} 页。')
            html = component['effects']['html']
        return self._rows(html)

    def all_feedbacks(self, max_pages=100):
        if type(max_pages) is not int or max_pages < 1:
            raise ValueError('max_pages 必须是正整数。')
        self.login()
        html = self._get(self.PATH)
        snapshot = self._component(html, self.COMPONENT)
        self._check_columns(snapshot)
        records = self._rows(html)
        for page in range(2, max_pages + 1):
            answer = self._post(snapshot, [{'path': '', 'method': 'gotoPage',
                                            'params': [page, 'page']}], self.PATH)
            component = answer['components'][0]
            snapshot = component['snapshot']
            actual = json.loads(snapshot)['data']['paginators'][0]['page']
            if actual != page:
                return records
            page_rows = self._rows(component['effects']['html'])
            if not page_rows:
                return records
            records.extend(page_rows)
        raise RuntimeError(f'反馈列表超过 {max_pages} 页；请提高 max_pages 后重试。')


def main():
    parser = argparse.ArgumentParser(description='读取管理后台意见反馈')
    parser.add_argument('--page', type=int, default=1, help='读取指定页，默认第 1 页')
    parser.add_argument('--all', action='store_true', help='读取全部页面')
    parser.add_argument('--output', type=Path, help='将反馈保存为 JSON；省略时输出到终端')
    args = parser.parse_args()
    client = FeedbackClient()
    records = client.all_feedbacks() if args.all else client.list_feedbacks(args.page)
    data = json.dumps(records, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(data + '\n', encoding='utf-8')
        print(f'已读取 {len(records)} 条反馈，保存至 {args.output}')
    else:
        print(data)


if __name__ == '__main__':
    main()
