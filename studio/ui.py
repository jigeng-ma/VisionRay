import json
import os
from pathlib import Path
import queue
import threading
import hashlib
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .config import catalog, resolve_device, model_from_name
from .devices import Adb
from .workbook import Mapping, inspect, LABELS, export
from .runner import execute, registry


BLUETOOTH_ONLY = '仅蓝牙连接（眼镜未接 USB）'


class App(tk.Tk):
    def __init__(self, root):
        super().__init__()
        self.root_dir = Path(root)
        self.title('AI 眼镜测试工作台')
        self.geometry('1180x780')
        self.minsize(980, 680)
        self.configure(bg='#f4f7fb')
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.busy = False
        self.modules = {}
        self.selected = set()
        self.devices_by_label = {}
        self.current_folder = None
        self.total = self.completed = self.passed = self.failed = 0
        self.blocked = self.unimplemented = self.not_applicable = self.skipped = 0
        self.controls = []
        self.path = tk.StringVar()
        self.phone = tk.StringVar()
        self.glasses = tk.StringVar()
        self.glasses_name = tk.StringVar()
        self.skip_tutorial = tk.BooleanVar(value=False)
        self.product = tk.StringVar()
        self.model = tk.StringVar()
        self.header = tk.StringVar(value='0')
        self.id_col = tk.StringVar(value='A')
        self.result_col = tk.StringVar(value='L')
        self.status = tk.StringVar(value='选择 Excel 和设备，按 Sheet 执行测试')
        self.run_stats = tk.StringVar(value='本轮结果：待执行 0 / 通过 0 / 失败 0')
        self.data = catalog(root)
        self.build()
        self.glasses_name.trace_add("write", self.detect_model)
        self.after(100, self.poll)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh_devices()

    def build(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10))
        style.configure('TFrame', background='#f4f7fb')
        style.configure('TLabelframe', background='#f4f7fb')
        style.configure('TLabelframe.Label', background='#f4f7fb', foreground='#244262', font=('Microsoft YaHei UI', 10, 'bold'))
        style.configure('TLabel', background='#f4f7fb')
        style.configure('TButton', padding=(10, 5))
        style.configure('Accent.TButton', background='#2463eb', foreground='white')
        style.configure('Treeview', rowheight=29, font=('Microsoft YaHei UI', 10))
        style.configure('Treeview.Heading', font=('Microsoft YaHei UI', 10, 'bold'), padding=5)
        top = tk.Frame(self, bg='#162b49', padx=20, pady=10)
        top.pack(fill='x')
        tk.Label(top, text='AI 眼镜测试工作台', bg='#162b49', fg='white', font=('Microsoft YaHei UI', 18, 'bold')).pack(anchor='w')
        tk.Label(top, text='ANDROID  /  单组设备  /  按 Excel 模块执行', bg='#162b49', fg='#bed0e8', font=('Microsoft YaHei UI', 10)).pack(anchor='w', pady=(4, 0))
        body = ttk.Frame(self, padding=(14, 10))
        body.pack(fill='both', expand=True)
        files = ttk.LabelFrame(body, text='1  选择用例文件', padding=8)
        files.pack(fill='x')
        entry = ttk.Entry(files, textvariable=self.path, state='readonly', width=82)
        entry.grid(row=0, column=0, sticky='w', padx=(0, 8))
        self.button(files, '选择 Excel', self.choose_file).grid(row=0, column=1, padx=(0, 6))
        self.button(files, '重新读取', self.load_file).grid(row=0, column=2)
        ttk.Label(files, text='读取配置：').grid(row=1, column=0, sticky='w', pady=(8, 0))
        for idx, (label, var, width) in enumerate([('表头行（0 自动）', self.header, 5), ('编号列', self.id_col, 5), ('结果列', self.result_col, 5)]):
            column = idx * 2 + 1
            ttk.Label(files, text=label).grid(row=1, column=column, sticky='e', pady=(8, 0))
            e = ttk.Entry(files, textvariable=var, width=width)
            e.grid(row=1, column=column + 1, padx=7, pady=(8, 0))
            self.controls.append((e, 'normal'))
        devices = ttk.LabelFrame(body, text='2  选择本轮设备与型号', padding=8)
        devices.pack(fill='x', pady=6)
        for column in (1, 3):
            devices.columnconfigure(column, weight=0, minsize=300)
        self.phone_box = self.combo(devices, '手机', self.phone, 0, 0)
        self.glasses_box = self.combo(devices, '眼镜设备', self.glasses, 0, 2)
        self.product_box = self.combo(devices, '产品', self.product, 1, 0)
        self.model_box = self.combo(devices, '型号', self.model, 1, 2)
        self.product_box['values'] = list(self.data['products'])
        self.product_box.bind('<<ComboboxSelected>>', self.change_product)
        self.glasses_box.bind('<<ComboboxSelected>>', self.change_glasses)
        ttk.Label(devices, text='眼镜蓝牙完整名称').grid(row=2, column=0, sticky='w', pady=4)
        name = ttk.Entry(devices, textvariable=self.glasses_name, width=30)
        name.grid(row=2, column=1, sticky='w', padx=8)
        self.controls.append((name, 'normal'))
        actions = ttk.Frame(devices)
        actions.grid(row=2, column=2, columnspan=2, sticky='w', padx=8)
        self.button(actions, '刷新设备', self.refresh_devices).pack(side='left')
        self.button(actions, '连接检查', self.preflight).pack(side='left', padx=6)
        self.button(actions, '启动 / 检查 Appium', self.start_service).pack(side='left')
        ttk.Label(devices, text='输入完整蓝牙名称，自动识别 G1/G3/G6；三款共用功能与用例。').grid(row=3, column=0, columnspan=4, sticky='w')
        skip = ttk.Checkbutton(devices, text='配对后跳过引导（验证进入目标眼镜首页）', variable=self.skip_tutorial)
        skip.grid(row=4, column=0, columnspan=4, sticky='w', pady=(5, 0))
        self.controls.append((skip, 'normal'))
        self.product.set('G系列' if 'G系列' in self.data['products'] else next(iter(self.data['products'])))
        self.change_product()
        modules = ttk.LabelFrame(body, text='3  勾选要执行的 Sheet 模块', padding=6)
        modules.pack(fill='both', expand=True)
        bar = ttk.Frame(modules)
        bar.pack(fill='x', pady=(0, 6))
        self.button(bar, '全选可执行模块', lambda: self.select_all(True)).pack(side='left')
        self.button(bar, '取消全选', lambda: self.select_all(False)).pack(side='left', padx=6)
        self.selection_text = tk.StringVar(value='尚未加载 Excel')
        ttk.Label(bar, textvariable=self.selection_text).pack(side='right')
        ttk.Label(bar, textvariable=self.run_stats, font=('Microsoft YaHei UI', 10, 'bold')).pack(side='right', padx=(0, 24))
        columns = ('selected', 'module', 'count', 'ready', 'validation', 'progress')
        self.tree = ttk.Treeview(modules, columns=columns, show='headings', selectmode='browse', height=6)
        for key, label, width in zip(columns, ['选择', 'Sheet / 模块名称', '用例数', '已实现', '检查结果', '本轮结果'], [55, 260, 70, 70, 230, 220]):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=45, stretch=key in ('module', 'validation', 'progress'))
        scroll = ttk.Scrollbar(modules, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<Button-1>', self.toggle)
        self.tree.bind('<Double-1>', self.show_warnings)
        self.tree.tag_configure('invalid', foreground='#a45b00')
        footer = ttk.Frame(body)
        footer.pack(fill='x', pady=(8, 4))
        self.start_button = self.button(footer, '开始执行', self.start, style='Accent.TButton')
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(footer, text='停止执行', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=6)
        ttk.Button(footer, text='打开结果目录', command=self.open_results).pack(side='right')
        self.button(footer, '重新导出历史轮次', self.reexport).pack(side='right', padx=6)
        self.progress = ttk.Progressbar(body, mode='determinate')
        self.progress.pack(fill='x', pady=(4, 3))
        ttk.Label(body, textvariable=self.status, wraplength=1120).pack(anchor='w')
        self.log = tk.Text(body, height=2, font=('Microsoft YaHei UI', 9), bg='#f8fafc', relief='flat', state='disabled')
        self.log.pack(fill='x', pady=(3, 0))

    def button(self, parent, text, command, **kwargs):
        b = ttk.Button(parent, text=text, command=command, **kwargs)
        self.controls.append((b, 'normal'))
        return b

    def combo(self, parent, label, var, row, col):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky='w', pady=4)
        box = ttk.Combobox(parent, textvariable=var, state='readonly', width=30)
        box.grid(row=row, column=col + 1, sticky='ew', padx=8, pady=4)
        self.controls.append((box, 'readonly'))
        return box

    def set_busy(self, busy):
        self.busy = busy
        for widget, state in self.controls:
            widget.configure(state='disabled' if busy else state)
        if not busy:
            self.detect_model()

    def background(self, action, fn):
        self.set_busy(True)
        def worker():
            try:
                self.events.put((action, fn()))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def mapping(self):
        result = Mapping(int(self.header.get()), self.id_col.get().upper(), self.result_col.get().upper())
        result.validate()
        return result

    def choose_file(self):
        path = filedialog.askopenfilename(filetypes=[('Excel 工作簿', '*.xlsx')])
        if path:
            self.path.set(path)
            self.load_file()

    def load_file(self):
        if not self.path.get():
            return
        try:
            mapping = self.mapping()
        except Exception as exc:
            messagebox.showerror('配置错误', str(exc))
            return
        path = self.path.get()
        product = self.product.get()
        self.status.set('正在读取 Sheet 和用例编号…')
        def read():
            before = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            modules = inspect(path, mapping)
            after = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            if before != after:
                raise ValueError('读取期间 Excel 被修改，请重新读取。')
            return modules, registry(self.root_dir, product), mapping, after
        self.background('loaded', read)

    def refresh_devices(self):
        self.status.set('正在扫描 ADB 设备…')
        self.background('devices', lambda: Adb().devices())

    def change_product(self, event=None):
        choices = list(self.data['products'][self.product.get()]['models'])
        self.model_box['values'] = choices
        self.model.set(choices[0])
        self.detect_model()

    def change_glasses(self, event=None):
        # USB 系统型号不是蓝牙完整名称，保留使用者输入。
        self.status.set('请填写眼镜蓝牙完整名称；G 系列型号将自动识别。')

    def detect_model(self, *args):
        name = self.glasses_name.get().strip()
        if self.product.get() == 'G系列' or name.upper().startswith('DPVR G'):
            self.product.set('G系列')
            self.model_box['values'] = list(self.data['products']['G系列']['models'])
            try:
                self.model.set(model_from_name(self.root_dir, name))
            except ValueError:
                self.model.set('')
            self.model_box.configure(state='disabled')
        else:
            self.model_box.configure(state='disabled' if self.busy else 'readonly')
        self.refresh_coverage()

    def refresh_coverage(self):
        if not self.modules or not hasattr(self, 'tree'):
            return
        entries = registry(self.root_dir, self.product.get())
        for row in self.tree.get_children():
            name = self.tree.set(row, 'module')
            values = list(self.tree.item(row, 'values'))
            values[3] = sum((name, c['id']) in entries for c in self.modules[name]['cases'])
            self.tree.item(row, values=values)

    def context(self):
        phone = self.devices_by_label.get(self.phone.get())
        glasses = self.devices_by_label.get(self.glasses.get())
        if not phone or (not glasses and self.glasses.get() != BLUETOOTH_ONLY):
            raise ValueError('请选择手机和眼镜设备。')
        if glasses and phone.serial == glasses.serial:
            raise ValueError('手机和眼镜不能是同一设备。')
        if not self.glasses_name.get().strip():
            raise ValueError('请填写眼镜蓝牙完整名称。')
        config = resolve_device(self.root_dir, self.product.get(), self.model.get(), self.glasses_name.get())
        config.setdefault('pairing', {})['skip_tutorial'] = self.skip_tutorial.get()
        return {'phone': phone.serial, 'glasses': glasses.serial if glasses else None, 'glasses_name': self.glasses_name.get().strip(),
                'config': config}

    def preflight(self):
        try:
            context = self.context()
        except Exception as exc:
            messagebox.showerror('选择不完整', str(exc))
            return
        self.background('preflight', lambda: Adb().preflight(context['phone'], context['glasses'], context['config']['package']))

    def start_service(self):
        from .service import start
        self.status.set('正在检查并启动本机 Appium 服务…')
        self.background('service', lambda: start(self.root_dir))

    def select_all(self, value):
        self.selected = {s for s, m in self.modules.items() if m['cases'] and not m['warnings']} if value else set()
        self.render_selection()

    def toggle(self, event):
        if self.busy or self.tree.identify_column(event.x) != '#1':
            return
        row = self.tree.identify_row(event.y)
        if not row:
            return
        name = self.tree.set(row, 'module')
        module = self.modules[name]
        if not module['cases'] or module['warnings']:
            self.status.set('该 Sheet 不可执行：' + '; '.join(module['warnings'][:3] or [module['reason']]))
            return
        if name in self.selected:
            self.selected.remove(name)
        else:
            self.selected.add(name)
        self.render_selection()

    def show_warnings(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            name = self.tree.set(row, 'module')
            m = self.modules[name]
            messagebox.showinfo(name, '\n'.join(m['warnings']) or m['reason'] or '编号校验通过。用例实现覆盖情况见“已实现”列。')

    def render_selection(self):
        for row in self.tree.get_children():
            name = self.tree.set(row, 'module')
            m = self.modules[name]
            self.tree.set(row, 'selected', '☑' if name in self.selected else '☐' if m['cases'] and not m['warnings'] else '—')
        self.selection_text.set(f'已选 {len(self.selected)} 个模块 / {sum(len(self.modules[s]["cases"]) for s in self.selected)} 条用例')

    def refresh_run_stats(self):
        pending = max(0, self.total - self.completed)
        values = [('待执行', pending), ('通过', self.passed), ('失败', self.failed),
                  ('阻塞', self.blocked), ('未实现', self.unimplemented),
                  ('不适用', self.not_applicable), ('跳过', self.skipped)]
        self.run_stats.set('本轮结果：' + ' / '.join(f'{label} {count}' for label, count in values
                                                if count or label in ('待执行', '通过', '失败')))

    def start(self):
        try:
            context, mapping = self.context(), self.mapping()
            if mapping != self.loaded_mapping:
                raise ValueError('列映射已修改，请先点击“重新读取”。')
            if not self.selected:
                raise ValueError('请勾选至少一个有用例且校验通过的模块。')
            context['input_sha256'] = self.loaded_hash
        except Exception as exc:
            messagebox.showerror('无法开始', str(exc))
            return
        # self.selected 是集合，只用于保存勾选状态；执行顺序以表格模块的显示顺序为准。
        selected, source = [name for name in self.modules if name in self.selected], self.path.get()
        self.completed = self.passed = self.failed = 0
        self.blocked = self.unimplemented = self.not_applicable = self.skipped = 0
        self.total = 0
        self.refresh_run_stats()
        self.progress['value'] = 0
        self.stop_event.clear()
        self.stop_button.configure(state='normal')
        self.status.set('执行前检查与保存本轮输入…')
        self.background('done', lambda: execute(self.root_dir, source, mapping, selected, context,
                            self.stop_event, lambda kind, value: self.events.put((kind, value))))

    def stop(self):
        self.stop_event.set()
        self.stop_button.configure(state='disabled')
        self.status.set('正在停止当前用例并保存结果…')

    def open_results(self):
        path = Path(self.current_folder) if self.current_folder else self.root_dir / 'runs'
        path.mkdir(exist_ok=True)
        os.startfile(path)

    def reexport(self):
        folder = filedialog.askdirectory(initialdir=self.root_dir / 'runs', title='选择包含 manifest.json 的执行轮次目录')
        if not folder:
            return
        def action():
            import sqlite3
            from datetime import datetime
            p = Path(folder)
            manifest = json.loads((p / 'manifest.json').read_text(encoding='utf-8'))
            with sqlite3.connect(p / 'results.sqlite') as db:
                db.row_factory = sqlite3.Row
                records = [dict(r) for r in db.execute('SELECT * FROM results')]
            for row in records:
                if row['status'] == 'RUNNING':
                    row['status'] = 'INTERRUPTED'
            target = p / ('results_reexport_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.xlsx')
            export(p / 'input.xlsx', target, Mapping(**manifest['mapping']), records)
            return str(target)
        self.background('reexport', action)

    def write_log(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def poll(self):
        try:
            # 限制每轮消息处理量，几千条快速结果也不会饿死窗口事件循环。
            for _ in range(100):
                kind, value = self.events.get_nowait()
                if kind in ('loaded', 'devices', 'preflight', 'done', 'error', 'reexport', 'service'):
                    self.set_busy(False)
                if kind == 'devices':
                    self.devices_by_label = {d.label: d for d in value}
                    for box, var in [(self.phone_box, self.phone), (self.glasses_box, self.glasses)]:
                        box['values'] = list(self.devices_by_label) + ([BLUETOOTH_ONLY] if box is self.glasses_box else [])
                        if var.get() not in box['values']:
                            var.set('')
                    self.status.set(f'发现 {len(value)} 台设备，请分别选择手机与眼镜。')
                elif kind == 'loaded':
                    self.modules, entries, self.loaded_mapping, self.loaded_hash = value
                    self.selected.clear()
                    self.tree.delete(*self.tree.get_children())
                    for name, m in self.modules.items():
                        ready = sum((name, c['id']) in entries for c in m['cases'])
                        check = f'{len(m["warnings"])} 项问题，双击查看' if m['warnings'] else m['reason'] or (f'忽略 {m["ignored_id_only"]} 行仅编号' if m['ignored_id_only'] else f'编号有效 / 表头第 {m["header"]} 行')
                        self.tree.insert('', 'end', values=('☐', name, len(m['cases']), ready, check, '未执行'),
                                         tags=('invalid',) if m['warnings'] or not m['cases'] else ())
                    self.render_selection()
                    self.status.set(f'已读取全部 {len(self.modules)} 个 Sheet。汇总页、空表及编号异常模块保留显示，禁止执行。')
                    self.refresh_coverage()
                elif kind == 'preflight':
                    self.status.set('连接检查通过；蓝牙眼镜的身份和绑定结果将在用例中验证。')
                    self.write_log(json.dumps(value, ensure_ascii=False))
                elif kind == 'run':
                    self.current_folder = value['folder']
                    self.total = value['total']
                    self.progress['maximum'] = max(1, self.total)
                    self.refresh_run_stats()
                    self.write_log('开始轮次：' + Path(self.current_folder).name)
                elif kind == 'case_start':
                    self.status.set(f'正在执行：{value["sheet"]} / {value["id"]}')
                elif kind == 'case':
                    self.completed += 1
                    if value['status'] == 'PASS':
                        self.passed += 1
                    elif value['status'] in ('FAIL', 'ERROR'):
                        self.failed += 1
                    elif value['status'] == 'BLOCKED':
                        self.blocked += 1
                    elif value['status'] == 'NOT_IMPLEMENTED':
                        self.unimplemented += 1
                    elif value['status'] == 'NOT_APPLICABLE':
                        self.not_applicable += 1
                    elif value['status'] == 'SKIPPED':
                        self.skipped += 1
                    self.refresh_run_stats()
                    self.progress['value'] = self.completed
                    self.status.set(f'{self.completed}/{self.total}  {value["sheet"]} / {value["id"]}：{LABELS[value["status"]]}')
                    for row in self.tree.get_children():
                        if self.tree.set(row, 'module') == value['sheet']:
                            self.tree.set(row, 'progress', f'{value["id"]} · {LABELS[value["status"]]}')
                elif kind == 'exporting':
                    self.stop_button.configure(state='disabled')
                    self.status.set('正在生成独立 Excel 结果文件并校验完整性…')
                elif kind == 'done':
                    self.stop_button.configure(state='disabled')
                    self.current_folder = value['folder']
                    for row in self.tree.get_children():
                        name = self.tree.set(row, 'module')
                        self.tree.set(row, 'progress', ' / '.join(f'{LABELS[k]} {v}' for k, v in value['summary'].get(name, {}).items()))
                    m = value['manifest']
                    result = '已停止' if m['state'] == 'INTERRUPTED' else '执行异常' if m['state'] == 'ERROR' else '本轮结束'
                    text = result + '。' + ('Excel 已生成。' if m['export'] == 'SUCCESS' else 'Excel 导出失败，可重新导出：' + m.get('export_error', ''))
                    self.status.set(text)
                    self.write_log(text + '  ' + self.current_folder)
                elif kind == 'reexport':
                    self.status.set('重新导出完成：' + value)
                elif kind == 'service':
                    self.status.set(value)
                elif kind == 'error':
                    self.stop_button.configure(state='disabled')
                    self.status.set('操作失败：' + value)
                    self.write_log(value)
                    messagebox.showerror('操作失败', value)
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def close(self):
        if self.busy:
            self.stop()
            self.status.set('正在处理或保存结果，请完成后关闭窗口。')
        else:
            self.destroy()


