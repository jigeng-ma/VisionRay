import json
import os
from pathlib import Path
import queue
import threading
import hashlib
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .config import catalog, resolve_device, model_from_name
from .devices import Adb
from .workbook import Mapping, inspect, LABELS, export, automation_count
from .runner import execute, execute_many, registry, case_applies

PRODUCT_LABELS = {'G系列': 'G1/G3/G6'}


def product_key(label):
    return next((key for key, value in PRODUCT_LABELS.items() if value == label), label)


def product_label(key):
    return PRODUCT_LABELS.get(key, key)


BLUETOOTH_ONLY = '仅蓝牙连接（眼镜未接 USB）'
FINAL_STATUSES = ('PASS', 'FAIL', 'ERROR', 'BLOCKED', 'NOT_IMPLEMENTED', 'NOT_APPLICABLE', 'SKIPPED', 'INTERRUPTED')


def summarize_selected(summary, selected):
    """用落盘的最终汇总重算顶部统计，不能依赖 GUI 消息到达时序。"""
    counts = {status: 0 for status in (*FINAL_STATUSES, 'NOT_RUN', 'RUNNING')}
    for sheet in selected:
        for status, number in summary.get(sheet, {}).items():
            counts[status] = counts.get(status, 0) + number
    return counts


def brief_detail(detail, limit=180):
    """状态栏显示一行可读原因；完整原文仍写入下方日志和结果文件。"""
    text = ' '.join(str(detail).split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


class App(tk.Tk):
    def __init__(self, root):
        super().__init__()
        self.root_dir = Path(root)
        self.state_file = self.root_dir / 'configs' / 'workbench_state.json'
        self.saved_state = self.load_state()
        self.title('AI 眼镜测试工作台')
        width = min(1440, self.winfo_screenwidth() - 80)
        height = min(780, self.winfo_screenheight() - 120)
        self.geometry(f'{width}x{height}+20+20')
        self.minsize(min(640, width), min(400, height))
        self.configure(bg='#f4f7fb')
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.busy = False
        self.running = False
        self.batch_running = False
        self.modules = {}
        self.selected = set()
        self.target_queue = list(self.saved_state.get('target_queue', []))
        self.extra_glasses = list(self.saved_state.get('extra_glasses', []))
        self.sheet_targets = dict(self.saved_state.get('sheet_targets', {}))
        self.failure_details = {}
        self.result_rows = 0
        self.devices_by_label = {}
        self.device_scan_pending = False
        self.current_folder = None
        self.total = self.completed = self.passed = self.failed = 0
        self.blocked = self.unimplemented = self.not_applicable = self.skipped = self.interrupted = 0
        self.controls = []
        self.path = tk.StringVar(value=self.saved_state.get('path', ''))
        self.phone = tk.StringVar(value=self.saved_state.get('phone', ''))
        self.glasses = tk.StringVar(value=self.saved_state.get('glasses', ''))
        self.glasses_name = tk.StringVar(value=self.saved_state.get('glasses_name', ''))
        self.skip_tutorial = tk.BooleanVar(value=self.saved_state.get('skip_tutorial', False))
        self.product = tk.StringVar()
        self.model = tk.StringVar()
        self.header = tk.StringVar(value=self.saved_state.get('header', '0'))
        self.id_col = tk.StringVar(value=self.saved_state.get('id_col', 'A'))
        self.result_col = tk.StringVar(value=self.saved_state.get('result_col', 'M'))
        self.version_placeholder = '如 1.2.39'
        self.app_version = tk.StringVar(value=self.saved_state.get('app_version', self.version_placeholder))
        self.status = tk.StringVar(value='选择 Excel、手机和眼镜，勾选模块后开始测试')
        self.run_stats = tk.StringVar(value='本轮结果：待执行 0 / 通过 0 / 失败 0')
        self.current_case = tk.StringVar(value='当前：尚未开始')
        self.selected_result = tk.StringVar(value='点击结果行查看原因')
        self.data = catalog(root)
        self.build()
        self.glasses_name.trace_add("write", self.detect_model)
        for var in (self.path, self.phone, self.glasses, self.glasses_name, self.skip_tutorial,
                    self.product, self.model, self.header, self.id_col, self.result_col, self.app_version):
            var.trace_add('write', self.save_state)
        self.after(100, self.poll)
        self.after(3000, self.watch_devices)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh_devices()
        if self.path.get() and Path(self.path.get()).is_file():
            self.after(200, self.load_file)

    def load_state(self):
        try:
            value = json.loads(self.state_file.read_text(encoding='utf-8'))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save_state(self, *_):
        if self.busy:
            return
        data = {'path': self.path.get(), 'phone': self.phone.get(), 'glasses': self.glasses.get(),
                'glasses_name': self.glasses_name.get(), 'skip_tutorial': self.skip_tutorial.get(),
                'product': self.product.get(), 'model': self.model.get(), 'header': self.header.get(),
                'id_col': self.id_col.get(), 'result_col': self.result_col.get(),
                'app_version': self.app_version.get(), 'selected': sorted(self.selected),
                'target_queue': self.target_queue, 'sheet_targets': self.sheet_targets,
                'extra_glasses': self.extra_glasses}
        self.saved_state = data
        try:
            self.state_file.parent.mkdir(exist_ok=True)
            temp = self.state_file.with_suffix('.tmp')
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(self.state_file)
        except OSError:
            pass

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
        tk.Label(top, text='选择用例与设备 → 勾选模块 → 开始执行', bg='#162b49', fg='#bed0e8', font=('Microsoft YaHei UI', 10)).pack(anchor='w', pady=(4, 0))
        viewport = ttk.Frame(self)
        viewport.pack(fill='both', expand=True)
        viewport.rowconfigure(0, weight=1)
        viewport.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(viewport, highlightthickness=0, bg='#f4f7fb')
        self.canvas.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(viewport, orient='vertical', command=self.canvas.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(viewport, orient='horizontal', command=self.canvas.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.content = ttk.Frame(self.canvas)
        self.content_window = self.canvas.create_window(0, 0, window=self.content, anchor='nw')
        self.canvas.bind('<Configure>', self.resize_content)
        self.content.bind('<Configure>', self.resize_content)
        self.bind('<MouseWheel>', self.scroll_page, add='+')
        results = ttk.LabelFrame(viewport, text='实时执行结果', padding=8)
        results.grid(row=0, column=2, rowspan=2, sticky='nsew', padx=(6, 8), pady=8)
        results.configure(width=365)
        results.grid_propagate(False)
        results.rowconfigure(2, weight=3)
        results.rowconfigure(5, weight=2)
        results.columnconfigure(0, weight=1)
        ttk.Label(results, textvariable=self.run_stats, wraplength=335,
                  font=('Microsoft YaHei UI', 10, 'bold')).grid(row=0, column=0, sticky='ew', pady=(0, 5))
        ttk.Label(results, textvariable=self.current_case, wraplength=335).grid(row=1, column=0, sticky='ew', pady=(0, 5))
        self.result_view = ttk.Treeview(results, columns=('case', 'status', 'detail'), show='headings', height=12)
        for key, title, width in [('case', '用例', 95), ('status', '结果', 60), ('detail', '原因', 195)]:
            self.result_view.heading(key, text=title)
            self.result_view.column(key, width=width, minwidth=50, stretch=key == 'detail')
        self.result_view.grid(row=2, column=0, sticky='nsew')
        result_scroll = ttk.Scrollbar(results, orient='vertical', command=self.result_view.yview)
        result_scroll.grid(row=2, column=1, sticky='ns')
        self.result_view.configure(yscrollcommand=result_scroll.set)
        for status, color in [('PASS', '#187747'), ('FAIL', '#b42318'), ('ERROR', '#b42318'),
                              ('BLOCKED', '#9a6700'), ('SKIPPED', '#7a6200')]:
            self.result_view.tag_configure(status, foreground=color)
        self.result_view.bind('<<TreeviewSelect>>', self.show_result_detail)
        ttk.Label(results, textvariable=self.selected_result, wraplength=330,
                  justify='left').grid(row=3, column=0, columnspan=2, sticky='ew', pady=(7, 4))
        ttk.Label(results, text='关键日志', font=('Microsoft YaHei UI', 10, 'bold')).grid(row=4, column=0, sticky='w', pady=(5, 3))
        self.log = tk.Text(results, height=10, wrap='word', font=('Microsoft YaHei UI', 9), bg='#f8fafc', relief='flat', state='disabled')
        self.log.grid(row=5, column=0, columnspan=2, sticky='nsew')
        body = ttk.Frame(self.content, padding=(14, 10))
        body.pack(fill='both', expand=True)
        files = ttk.LabelFrame(body, text='1  选择用例文件', padding=8)
        files.pack(fill='x')
        entry = ttk.Entry(files, textvariable=self.path, state='readonly', width=58)
        entry.grid(row=0, column=0, sticky='w', padx=(0, 8))
        self.button(files, '选择 Excel', self.choose_file).grid(row=0, column=1, padx=(0, 6))
        self.button(files, '重新读取', self.load_file).grid(row=0, column=2)
        self.advanced_button = self.button(files, '高级设置 ▸', self.toggle_advanced)
        self.advanced_button.grid(row=0, column=3, padx=(8, 0))
        self.advanced = ttk.Frame(files)
        self.advanced.grid(row=1, column=0, columnspan=4, sticky='w')
        ttk.Label(self.advanced, text='Excel 列映射：').grid(row=0, column=0, sticky='w', pady=(8, 0))
        for idx, (label, var, width) in enumerate([('表头行（0 自动）', self.header, 5), ('编号列', self.id_col, 5), ('结果列', self.result_col, 5)]):
            column = idx * 2 + 1
            ttk.Label(self.advanced, text=label).grid(row=0, column=column, sticky='e', pady=(8, 0))
            e = ttk.Entry(self.advanced, textvariable=var, width=width)
            e.grid(row=0, column=column + 1, padx=7, pady=(8, 0))
            self.controls.append((e, 'normal'))
        self.advanced.grid_remove()
        devices = ttk.LabelFrame(body, text='2  选择本轮设备与型号', padding=8)
        devices.pack(fill='x', pady=6)
        for column in (1, 3):
            devices.columnconfigure(column, weight=0, minsize=245)
        self.phone_box = self.combo(devices, '手机', self.phone, 0, 0)
        self.glasses_box = self.combo(devices, 'Nova 眼镜 USB（可选）', self.glasses, 0, 2)
        self.product_box = self.combo(devices, '产品', self.product, 1, 0)
        self.model_box = self.combo(devices, '型号', self.model, 1, 2)
        self.product_box['values'] = [product_label(key) for key in self.data['products']]
        self.product_box.bind('<<ComboboxSelected>>', self.change_product)
        self.glasses_box.bind('<<ComboboxSelected>>', self.change_glasses)
        ttk.Label(devices, text='眼镜蓝牙完整名称').grid(row=2, column=0, sticky='w', pady=4)
        name = ttk.Entry(devices, textvariable=self.glasses_name, width=26)
        name.grid(row=2, column=1, sticky='w', padx=8)
        self.controls.append((name, 'normal'))
        actions = ttk.Frame(devices)
        actions.grid(row=2, column=2, columnspan=2, sticky='w', padx=8)
        self.button(actions, '刷新设备', self.refresh_devices).pack(side='left')
        self.connection_check = self.button(actions, '连接检查', self.preflight)
        self.connection_check.pack(side='left', padx=6)
        self.appium_check = self.button(actions, '启动 / 检查 Appium', self.start_service)
        self.appium_check.pack(side='left')
        self.connection_check.pack_forget()
        self.appium_check.pack_forget()
        ttk.Label(devices, text='APP 版本号').grid(row=3, column=0, sticky='w', pady=(4, 0))
        version_check = self.register(self.validate_version_input)
        version = ttk.Entry(devices, textvariable=self.app_version, width=16, validate='key', validatecommand=(version_check, '%P'))
        version.grid(row=3, column=1, sticky='w', padx=8, pady=(4, 0))
        version.configure(foreground='#7a8698')
        version.bind('<FocusIn>', lambda event: self.edit_version(version))
        version.bind('<FocusOut>', lambda event: self.restore_version_hint(version))
        self.controls.append((version, 'normal'))
        ttk.Label(devices, text='-Occident-debug').grid(row=3, column=1, sticky='w', padx=(145, 0))
        ttk.Label(devices, text='执行前自动下载安装；Google 登录用例自动使用 release。').grid(row=3, column=2, columnspan=2, sticky='w')
        skip = ttk.Checkbutton(devices, text='配对后跳过引导（验证进入目标眼镜首页）', variable=self.skip_tutorial)
        skip.grid(row=5, column=0, columnspan=4, sticky='w', pady=(5, 0))
        skip.grid_remove()
        self.skip_option = skip
        self.controls.append((skip, 'normal'))
        saved_product = product_key(self.saved_state.get('product', ''))
        self.product.set(product_label(saved_product if saved_product in self.data['products'] else
                         ('G系列' if 'G系列' in self.data['products'] else next(iter(self.data['products'])))))
        self.change_product()
        if self.saved_state.get('model') in self.model_box['values']:
            self.model.set(self.saved_state['model'])
        self.extra_button = self.button(body, '', self.toggle_extra_glasses)
        self.extra_button.pack(anchor='w', pady=(0, 5))
        extras = ttk.LabelFrame(body, text='多台眼镜信息：供绑定／解绑场景使用，不改变当前执行眼镜', padding=6)
        extras.pack(fill='x', pady=(0, 6))
        self.extra_panel = extras
        form = ttk.Frame(extras)
        form.pack(fill='x')
        self.extra_product = tk.StringVar(value=self.product.get())
        self.extra_model = tk.StringVar()
        self.extra_name = tk.StringVar()
        ttk.Label(form, text='产品').pack(side='left')
        self.extra_product_box = ttk.Combobox(form, textvariable=self.extra_product, state='readonly', width=13,
                                              values=[product_label(key) for key in self.data['products']])
        self.extra_product_box.pack(side='left', padx=(5, 10))
        self.extra_product_box.bind('<<ComboboxSelected>>', self.change_extra_product)
        self.controls.append((self.extra_product_box, 'readonly'))
        ttk.Label(form, text='型号').pack(side='left')
        self.extra_model_box = ttk.Combobox(form, textvariable=self.extra_model, state='readonly', width=10)
        self.extra_model_box.pack(side='left', padx=(5, 10))
        self.controls.append((self.extra_model_box, 'readonly'))
        ttk.Label(form, text='蓝牙完整名称').pack(side='left')
        extra_name = ttk.Entry(form, textvariable=self.extra_name, width=28)
        extra_name.pack(side='left', padx=5)
        self.controls.append((extra_name, 'normal'))
        self.change_extra_product()
        self.extra_view = ttk.Treeview(extras, columns=('product', 'model', 'name'), show='headings', height=3)
        for key, label, width in [('product', '产品', 120), ('model', '型号', 90), ('name', '蓝牙完整名称', 270)]:
            self.extra_view.heading(key, text=label)
            self.extra_view.column(key, width=width, stretch=key == 'name')
        self.extra_view.pack(fill='x', pady=(5, 0))
        self.extra_view.bind('<<TreeviewSelect>>', self.select_extra_glasses)
        extra_actions = ttk.Frame(extras)
        extra_actions.pack(anchor='w', pady=(5, 0))
        self.button(extra_actions, '加入／保存', self.save_extra_glasses).pack(side='left')
        self.button(extra_actions, '移除所选', self.remove_extra_glasses).pack(side='left', padx=6)
        self.button(extra_actions, '清空输入', self.clear_extra_input).pack(side='left')
        self.render_extra_glasses()
        extras.pack_forget()
        self.targets_button = self.button(body, '多型号串行与 Sheet 分配 ▾' if self.target_queue else
                                          '多型号串行与 Sheet 分配 ▸', self.toggle_targets)
        self.targets_button.pack(anchor='w', pady=(0, 5))
        targets = ttk.LabelFrame(body, text='多型号串行：逐个加入设备，再给各 Sheet 分配', padding=6)
        targets.pack(fill='x', pady=(0, 6))
        self.targets_panel = targets
        self.queue_view = ttk.Treeview(targets, columns=('order', 'model', 'name', 'usb'), show='headings', height=4)
        for key, label, width in [('order', '顺序', 55), ('model', '型号', 110),
                                  ('name', '眼镜蓝牙名称', 250), ('usb', '眼镜 USB/ADB', 250)]:
            self.queue_view.heading(key, text=label)
            self.queue_view.column(key, width=width, stretch=key in ('name', 'usb'))
        self.queue_view.pack(fill='x')
        queue_actions = ttk.Frame(targets)
        queue_actions.pack(anchor='w', pady=(5, 0))
        for label, action in [('加入型号', self.add_target), ('移除所选', self.remove_target),
                              ('上移', lambda: self.move_target(-1)), ('下移', lambda: self.move_target(1))]:
            self.button(queue_actions, label, action).pack(side='left', padx=(0, 6))
        self.render_targets()
        if not self.target_queue:
            targets.pack_forget()
        modules = ttk.LabelFrame(body, text='3  勾选要执行的 Sheet 模块', padding=6)
        modules.pack(fill='both', expand=True)
        bar = ttk.Frame(modules)
        bar.pack(fill='x', pady=(0, 6))
        self.button(bar, '全选可执行模块', lambda: self.select_all(True)).pack(side='left')
        self.button(bar, '取消全选', lambda: self.select_all(False)).pack(side='left', padx=6)
        self.selection_text = tk.StringVar(value='尚未加载 Excel')
        ttk.Label(bar, textvariable=self.selection_text).pack(side='right')
        assign = ttk.Frame(modules)
        assign.pack(fill='x', pady=(0, 6))
        self.assign_panel = assign
        ttk.Label(assign, text='所选 Sheet 使用设备').pack(side='left')
        self.sheet_target = tk.StringVar()
        self.sheet_target_box = ttk.Combobox(assign, textvariable=self.sheet_target, state='readonly', width=43)
        self.sheet_target_box.pack(side='left', padx=8)
        self.controls.append((self.sheet_target_box, 'readonly'))
        self.button(assign, '分配给所选 Sheet', self.assign_sheet_target).pack(side='left')
        if not self.target_queue:
            assign.pack_forget()
        columns = ('selected', 'module', 'target', 'count', 'ready', 'validation', 'progress')
        self.tree = ttk.Treeview(modules, columns=columns, show='headings', selectmode='browse', height=6)
        for key, label, width in zip(columns, ['选择', '模块', '执行设备', '用例数', '自动化编号数', '检查结果', '本轮结果'], [50, 210, 165, 65, 100, 180, 180]):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=45, stretch=key in ('module', 'validation', 'progress'))
        scroll = ttk.Scrollbar(modules, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<Button-1>', self.toggle)
        self.tree.bind('<<TreeviewSelect>>', self.show_sheet_target)
        self.tree.bind('<Double-1>', self.show_warnings)
        self.tree.tag_configure('invalid', foreground='#a45b00')
        footer = ttk.Frame(body)
        footer.pack(fill='x', pady=(8, 4))
        self.start_button = self.button(footer, '开始执行', self.start, style='Accent.TButton')
        self.start_button.pack(side='left')
        # 屏保/锁屏后按 Enter 唤醒电脑时，按钮可能仍持有焦点。
        self.start_button.bind('<Return>', lambda _event: 'break')
        self.start_button.bind('<KP_Enter>', lambda _event: 'break')
        self.stop_button = ttk.Button(footer, text='停止执行', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=6)
        ttk.Button(footer, text='打开结果目录', command=self.open_results).pack(side='right')
        self.button(footer, '重新导出历史轮次', self.reexport).pack(side='right', padx=6)
        self.progress = ttk.Progressbar(body, mode='determinate')
        self.progress.pack(fill='x', pady=(4, 3))
        ttk.Label(body, textvariable=self.status, wraplength=1120).pack(anchor='w')

    def toggle_advanced(self):
        if self.advanced.winfo_manager():
            self.advanced.grid_remove()
            self.skip_option.grid_remove()
            self.connection_check.pack_forget()
            self.appium_check.pack_forget()
            self.advanced_button.configure(text='高级设置 ▸')
        else:
            self.advanced.grid()
            self.skip_option.grid()
            self.connection_check.pack(side='left', padx=6)
            self.appium_check.pack(side='left')
            self.advanced_button.configure(text='高级设置 ▾')

    def toggle_targets(self):
        if self.targets_panel.winfo_manager():
            self.targets_panel.pack_forget()
            self.assign_panel.pack_forget()
            self.targets_button.configure(text='多型号串行与 Sheet 分配 ▸')
        else:
            self.targets_panel.pack(fill='x', before=self.tree.master, pady=(0, 6))
            self.targets_button.configure(text='多型号串行与 Sheet 分配 ▾')
            if self.target_queue:
                self.assign_panel.pack(fill='x', before=self.tree, pady=(0, 6))

    def toggle_extra_glasses(self):
        if self.extra_panel.winfo_manager():
            self.extra_panel.pack_forget()
        else:
            self.extra_panel.pack(fill='x', before=self.targets_button, pady=(0, 6))
        self.render_extra_glasses()

    def change_extra_product(self, _event=None):
        product = product_key(self.extra_product.get())
        choices = list(self.data['products'][product]['models'])
        self.extra_model_box['values'] = choices
        if self.extra_model.get() not in choices:
            self.extra_model.set(choices[0])
        self.extra_model_box.configure(state='disabled' if product == 'G系列' or self.busy else 'readonly')

    def render_extra_glasses(self):
        self.extra_view.delete(*self.extra_view.get_children())
        for index, item in enumerate(self.extra_glasses):
            self.extra_view.insert('', 'end', iid=str(index), values=(product_label(item['product']),
                item['model'], item['glasses_name']))
        arrow = '▾' if self.extra_panel.winfo_manager() else '▸'
        self.extra_button.configure(text=f'多台眼镜信息（已加入 {len(self.extra_glasses)} 台）{arrow}')

    def select_extra_glasses(self, _event=None):
        selected = self.extra_view.selection()
        if selected:
            item = self.extra_glasses[int(selected[0])]
            self.extra_product.set(product_label(item['product']))
            self.change_extra_product()
            self.extra_model.set(item['model'])
            self.extra_name.set(item['glasses_name'])

    def clear_extra_input(self):
        self.extra_view.selection_remove(*self.extra_view.selection())
        self.extra_name.set('')

    def save_extra_glasses(self):
        try:
            name = self.extra_name.get().strip()
            if not name:
                raise ValueError('请填写眼镜蓝牙完整名称。')
            product = product_key(self.extra_product.get())
            config = resolve_device(self.root_dir, product, self.extra_model.get(), name)
            item = {'product': product, 'model': config['model'], 'glasses_name': name}
            selected = self.extra_view.selection()
            index = int(selected[0]) if selected else None
            if any(other['glasses_name'].casefold() == name.casefold() for pos, other in enumerate(self.extra_glasses)
                   if pos != index):
                raise ValueError('该眼镜已在多台眼镜信息中。')
            if index is None:
                self.extra_glasses.append(item)
            else:
                self.extra_glasses[index] = item
            self.render_extra_glasses()
            self.clear_extra_input()
            self.save_state()
        except ValueError as exc:
            messagebox.showerror('眼镜信息无效', str(exc))

    def remove_extra_glasses(self):
        selected = self.extra_view.selection()
        if selected:
            self.extra_glasses.pop(int(selected[0]))
            self.render_extra_glasses()
            self.clear_extra_input()
            self.save_state()

    def glasses_inventory(self, primary):
        candidates = [primary, *self.target_queue, *self.extra_glasses]
        result, seen = [], set()
        for item in candidates:
            name = item['glasses_name'].strip()
            if name.casefold() not in seen:
                config = resolve_device(self.root_dir, item['product'], item['model'], name)
                result.append({'product': item['product'], 'model': config['model'], 'glasses_name': name})
                seen.add(name.casefold())
        return result

    def show_result_detail(self, _event=None):
        rows = self.result_view.selection()
        if rows:
            detail = self.result_view.set(rows[0], 'detail')
            label = self.result_view.set(rows[0], 'case')
            self.selected_result.set(f'{label}：{detail or "Passed"}')

    def resize_content(self, event=None):
        # Keep the form's requested size so pack never hides the bottom controls.
        self.canvas.itemconfigure(
            self.content_window,
            width=max(self.canvas.winfo_width(), self.content.winfo_reqwidth()),
            height=max(self.canvas.winfo_height(), self.content.winfo_reqheight()),
        )
        self.canvas.configure(scrollregion=self.canvas.bbox(self.content_window))

    def scroll_page(self, event):
        # Let tables, logs and drop-downs retain their own wheel behavior.
        if event.widget.winfo_class() in ('Treeview', 'Text', 'TCombobox'):
            return
        if event.delta:
            steps = -int(event.delta / 120) or (-1 if event.delta > 0 else 1)
            self.canvas.yview_scroll(steps, 'units')
            return 'break'

    def button(self, parent, text, command, **kwargs):
        b = ttk.Button(parent, text=text, command=command, **kwargs)
        self.controls.append((b, 'normal'))
        return b

    def combo(self, parent, label, var, row, col):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky='w', pady=4)
        box = ttk.Combobox(parent, textvariable=var, state='readonly', width=25)
        box.grid(row=row, column=col + 1, sticky='ew', padx=8, pady=4)
        self.controls.append((box, 'readonly'))
        return box

    def set_busy(self, busy):
        if self.running and not busy:
            return
        self.busy = busy
        for widget, state in self.controls:
            widget.configure(state='disabled' if busy else state)
        if not busy:
            self.detect_model()
            self.change_extra_product()

    def background(self, action, fn):
        self.set_busy(True)
        def worker():
            try:
                self.events.put((action, fn()))
            except Exception as exc:
                detail = str(exc).strip() or type(exc).__name__
                self.events.put(('error', detail))
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
        product = product_key(self.product.get())
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

    def watch_devices(self):
        """热插拔后刷新设备列表，不打断正在执行的用例或用户操作。"""
        if not self.busy and not self.running and not self.device_scan_pending:
            self.device_scan_pending = True
            def scan():
                try:
                    self.events.put(('devices_auto', Adb().devices()))
                except Exception:
                    self.device_scan_pending = False
            threading.Thread(target=scan, daemon=True).start()
        self.after(3000, self.watch_devices)

    def show_devices(self, devices, automatic=False):
        old = self.devices_by_label
        selected = [(box, var, old.get(var.get())) for box, var in
                    ((self.phone_box, self.phone), (self.glasses_box, self.glasses))]
        updated = {d.label: d for d in devices}
        changed = set(updated) != set(old)
        self.devices_by_label = updated
        for box, var, previous in selected:
            box['values'] = list(updated) + ([BLUETOOTH_ONLY] if box is self.glasses_box else [])
            if previous:
                match = next((label for label, device in updated.items()
                              if device.serial == previous.serial), '')
                var.set(match)
            elif var.get() not in box['values']:
                var.set('')
        if changed or not automatic:
            self.status.set(f'发现 {len(devices)} 台设备，请分别选择手机与眼镜。')

    def change_product(self, event=None):
        choices = list(self.data['products'][product_key(self.product.get())]['models'])
        self.model_box['values'] = choices
        self.model.set(choices[0])
        self.detect_model()

    def render_targets(self):
        self.queue_view.delete(*self.queue_view.get_children())
        for index, target in enumerate(self.target_queue):
            self.queue_view.insert('', 'end', iid=str(index), values=(index + 1, target['model'],
                target['glasses_name'], target.get('glasses_label') or BLUETOOTH_ONLY))
        if hasattr(self, 'sheet_target_box'):
            self.sheet_target_box['values'] = [self.target_label(target) for target in self.target_queue]
            if self.sheet_target.get() not in self.sheet_target_box['values']:
                self.sheet_target.set('')
        if hasattr(self, 'tree'):
            self.render_selection()
        if hasattr(self, 'assign_panel'):
            if self.target_queue and self.targets_panel.winfo_manager():
                self.assign_panel.pack(fill='x', before=self.tree, pady=(0, 6))
            else:
                self.assign_panel.pack_forget()

    @staticmethod
    def target_key(target):
        return json.dumps([target['product'], target['model'], target['glasses_name']], ensure_ascii=False)

    @staticmethod
    def target_label(target):
        return f'{target["model"]} · {target["glasses_name"]}'

    def target_index(self, sheet):
        key = self.sheet_targets.get(sheet)
        matches = [index for index, target in enumerate(self.target_queue)
                   if self.target_key(target) == key]
        if matches:
            return matches[0]
        return 0 if len(self.target_queue) == 1 and not key else None

    def show_sheet_target(self, _event=None):
        rows = self.tree.selection()
        if rows:
            sheet = self.tree.set(rows[0], 'module')
            index = self.target_index(sheet)
            self.sheet_target.set(self.target_label(self.target_queue[index]) if index is not None else '')

    def assign_sheet_target(self):
        rows = self.tree.selection()
        if not rows:
            messagebox.showerror('未选择 Sheet', '请先点击要分配设备的 Sheet 行。')
            return
        sheet = self.tree.set(rows[0], 'module')
        if sheet not in self.selected:
            messagebox.showerror('Sheet 未勾选', '请先勾选此 Sheet。')
            return
        target = next((target for target in self.target_queue
                       if self.target_label(target) == self.sheet_target.get()), None)
        if target is None:
            messagebox.showerror('未选择设备', '请从本次执行队列选择设备。')
            return
        self.sheet_targets[sheet] = self.target_key(target)
        self.render_selection()
        self.refresh_coverage()
        self.save_state()

    def add_target(self):
        try:
            name = self.glasses_name.get().strip()
            if not name:
                raise ValueError('请先填写该型号的眼镜蓝牙完整名称。')
            product = product_key(self.product.get())
            config = resolve_device(self.root_dir, product, self.model.get(), name)
            label = self.glasses.get() if product == 'Nova' else BLUETOOTH_ONLY
            if product == 'Nova' and label and label != BLUETOOTH_ONLY and label not in self.devices_by_label:
                raise ValueError('Nova 请先选择眼镜 USB/ADB 设备，或选择仅蓝牙连接。')
            serial = self.devices_by_label[label].serial if label and label != BLUETOOTH_ONLY else None
            target = {'product': product, 'model': config['model'], 'glasses_name': name,
                      'glasses_serial': serial, 'glasses_label': label}
            if any((t['product'], t['model'], t['glasses_name']) == (product, config['model'], name)
                   for t in self.target_queue):
                raise ValueError('该眼镜已在执行队列中。')
            self.target_queue.append(target)
            self.render_targets()
            self.refresh_coverage()
            self.save_state()
        except ValueError as exc:
            messagebox.showerror('无法加入型号', str(exc))

    def remove_target(self):
        selected = self.queue_view.selection()
        if selected:
            self.target_queue.pop(int(selected[0]))
            self.render_targets()
            self.refresh_coverage()
            self.save_state()

    def move_target(self, direction):
        selected = self.queue_view.selection()
        if not selected:
            return
        old = int(selected[0]); new = old + direction
        if 0 <= new < len(self.target_queue):
            self.target_queue[old], self.target_queue[new] = self.target_queue[new], self.target_queue[old]
            self.render_targets()
            self.queue_view.selection_set(str(new))
            self.save_state()

    def change_glasses(self, event=None):
        # USB 系统型号不是蓝牙完整名称，保留使用者输入。
        self.status.set('请填写眼镜蓝牙完整名称；G1/G3/G6 组内型号将自动识别。')

    def detect_model(self, *args):
        name = self.glasses_name.get().strip()
        if product_key(self.product.get()) == 'G系列':
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
        for row in self.tree.get_children():
            name = self.tree.set(row, 'module')
            self.tree.set(row, 'ready', automation_count(self.modules[name]))

    def context(self):
        phone = self.devices_by_label.get(self.phone.get())
        glasses = self.devices_by_label.get(self.glasses.get())
        product = product_key(self.product.get())
        if not phone:
            raise ValueError('请选择手机设备。')
        if product == 'Nova' and self.glasses.get() and not glasses and self.glasses.get() != BLUETOOTH_ONLY:
            raise ValueError('所选 Nova 眼镜 USB 设备已断开，请刷新设备。')
        if product != 'Nova':
            glasses = None
        if glasses and phone.serial == glasses.serial:
            raise ValueError('手机和眼镜不能是同一设备。')
        if not self.glasses_name.get().strip():
            raise ValueError('请填写眼镜蓝牙完整名称。')
        config = resolve_device(self.root_dir, product, self.model.get(), self.glasses_name.get())
        config.setdefault('pairing', {})['skip_tutorial'] = self.skip_tutorial.get()
        number = self.app_version.get().strip()
        version = '' if number == self.version_placeholder else f'{number}-Occident-debug'
        return {'phone': phone.serial, 'glasses': glasses.serial if glasses else None, 'glasses_name': self.glasses_name.get().strip(),
                'config': config, 'app_version': version,
                'glasses_inventory': self.glasses_inventory({'product': product, 'model': config['model'],
                                                            'glasses_name': self.glasses_name.get().strip()})}

    def target_context(self, target):
        phone = self.devices_by_label.get(self.phone.get())
        if not phone:
            raise ValueError('请选择手机设备。')
        if target.get('glasses_serial') == phone.serial:
            raise ValueError('手机和 Nova 眼镜 USB 不能是同一设备。')
        config = resolve_device(self.root_dir, target['product'], target['model'], target['glasses_name'])
        config.setdefault('pairing', {})['skip_tutorial'] = self.skip_tutorial.get()
        number = self.app_version.get().strip()
        version = '' if number == self.version_placeholder else f'{number}-Occident-debug'
        return {'phone': phone.serial, 'glasses': target.get('glasses_serial') if target['product'] == 'Nova' else None,
                'glasses_name': target['glasses_name'], 'config': config, 'app_version': version,
                'glasses_inventory': self.glasses_inventory(target)}

    def validate_version_input(self, value):
        return '..' not in value and bool(re.fullmatch(r'\d*(?:\.\d*)*', value))

    def edit_version(self, entry):
        if self.app_version.get() == self.version_placeholder:
            self.app_version.set('')
            entry.configure(foreground='#000000')

    def restore_version_hint(self, entry):
        if not self.app_version.get():
            self.app_version.set(self.version_placeholder)
            entry.configure(foreground='#7a8698')

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
        self.save_state()

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
        self.save_state()

    def show_warnings(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            name = self.tree.set(row, 'module')
            m = self.modules[name]
            messagebox.showinfo(name, '\n'.join(m['warnings']) or m['reason'] or '编号校验通过。自动化编号数量见“自动化编号数”列。')

    def render_selection(self):
        for row in self.tree.get_children():
            name = self.tree.set(row, 'module')
            m = self.modules[name]
            self.tree.set(row, 'selected', '☑' if name in self.selected else '☐' if m['cases'] and not m['warnings'] else '—')
            index = self.target_index(name) if self.target_queue else None
            target = self.target_queue[index] if index is not None else None
            self.tree.set(row, 'target', self.target_label(target) if target else ('待分配' if name in self.selected and self.target_queue else '—'))
        self.selection_text.set(f'已选 {len(self.selected)} 个模块 / {sum(len(self.modules[s]["cases"]) for s in self.selected)} 条用例')

    def refresh_run_stats(self):
        pending = max(0, self.total - self.completed)
        values = [('待执行', pending), ('通过', self.passed), ('失败', self.failed),
                  ('阻塞', self.blocked), ('未实现', self.unimplemented),
                  ('不适用', self.not_applicable), ('跳过', self.skipped), ('中断', self.interrupted)]
        self.run_stats.set('本轮结果：' + ' / '.join(f'{label} {count}' for label, count in values
                                                if count or label in ('待执行', '通过', '失败')))

    def start(self):
        if self.busy or self.running:
            return
        try:
            contexts = ([self.target_context(target) for target in self.target_queue]
                        if self.target_queue else [self.context()])
            mapping = self.mapping()
            entered_version = self.app_version.get().strip()
            if entered_version != self.version_placeholder and not re.fullmatch(r'\d+\.\d+\.\d+', entered_version):
                raise ValueError('版本号格式应为三段数字，例如 1.2.39。')
            if not contexts[0]['app_version']:
                raise ValueError('请填写要测试的版本号，例如 1.2.39。')
            if mapping != self.loaded_mapping:
                raise ValueError('列映射已修改，请先点击“重新读取”。')
            if not self.selected:
                raise ValueError('请勾选至少一个有用例且校验通过的模块。')
            selected = [name for name in self.modules if name in self.selected]
            sheet_targets = ({sheet: self.target_index(sheet) for sheet in selected}
                             if self.target_queue else None)
            if sheet_targets and any(index is None for index in sheet_targets.values()):
                missing = [sheet for sheet, index in sheet_targets.items() if index is None]
                raise ValueError('请为以下 Sheet 选择本次执行设备：' + '、'.join(missing))
            if not any((item := registry(self.root_dir, contexts[sheet_targets[sheet]]['config']['product']
                                        if sheet_targets else contexts[0]['config']['product']).get((sheet, case['id'])))
                       and case_applies(item, contexts[sheet_targets[sheet]]['config'] if sheet_targets else contexts[0]['config'])
                       for sheet in selected for case in self.modules[sheet]['cases']):
                raise ValueError('当前所选型号与模块尚无适用的自动化用例；请先补充该型号的用例实现。')
            for context in contexts:
                context['input_sha256'] = self.loaded_hash
        except Exception as exc:
            messagebox.showerror('无法开始', str(exc))
            return
        # self.selected 是集合，只用于保存勾选状态；执行顺序以表格模块的显示顺序为准。
        source = self.path.get()
        self.completed = self.passed = self.failed = 0
        self.blocked = self.unimplemented = self.not_applicable = self.skipped = self.interrupted = 0
        self.total = 0
        self.refresh_run_stats()
        self.result_view.delete(*self.result_view.get_children())
        self.current_case.set('当前：准备执行')
        self.selected_result.set('点击结果行查看原因')
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.configure(state='disabled')
        self.progress['value'] = 0
        self.stop_event.clear()
        self.stop_button.configure(state='normal')
        self.status.set('执行前检查与保存本轮输入…')
        self.running = True
        self.batch_running = bool(self.target_queue)
        def run():
            emit = lambda kind, value: self.events.put((kind, value))
            if self.batch_running:
                return execute_many(self.root_dir, source, mapping, selected, contexts, self.stop_event, emit,
                                    sheet_targets=sheet_targets)
            return execute(self.root_dir, source, mapping, selected, contexts[0], self.stop_event, emit)
        self.background('done', run)

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
        if int(self.log.index('end-1c').split('.')[0]) > 300:
            self.log.delete('1.0', '51.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def show_case_result(self, value):
        status = value['status']
        model = value.get('model', '')
        name = f'{model} {value["id"]}'.strip()
        reason = brief_detail(value.get('detail', ''), 300)
        row = self.result_view.insert('', 'end', values=(name, 'Passed' if status == 'PASS' else LABELS[status], reason),
                                      tags=(status,))
        self.result_view.selection_set(row)
        self.show_result_detail()
        self.result_view.yview_moveto(1)
        self.current_case.set(f'已完成 {self.completed}/{self.total}：{name} · {"Passed" if status == "PASS" else LABELS[status]}')
        self.write_log(f'{name}  {"Passed" if status == "PASS" else LABELS[status] + "：" + reason}')

    def poll(self):
        try:
            # 限制每轮消息处理量，几千条快速结果也不会饿死窗口事件循环。
            for _ in range(100):
                kind, value = self.events.get_nowait()
                if kind in ('done', 'error'):
                    self.running = False
                if kind == 'devices_auto':
                    self.device_scan_pending = False
                if kind in ('loaded', 'devices', 'done', 'error', 'reexport', 'service'):
                    self.set_busy(False)
                if kind in ('devices', 'devices_auto'):
                    self.show_devices(value, automatic=kind == 'devices_auto')
                elif kind == 'loaded':
                    self.modules, entries, self.loaded_mapping, self.loaded_hash = value
                    self.selected = set(self.saved_state.get('selected', ())) & set(self.modules)
                    self.tree.delete(*self.tree.get_children())
                    for name, m in self.modules.items():
                        ready = automation_count(m)
                        check = f'{len(m["warnings"])} 项问题，双击查看' if m['warnings'] else m['reason'] or (f'忽略 {m["ignored_id_only"]} 行仅编号' if m['ignored_id_only'] else f'编号有效 / 表头第 {m["header"]} 行')
                        self.tree.insert('', 'end', values=('☐', name, '—', len(m['cases']), ready, check, '未执行'),
                                         tags=('invalid',) if m['warnings'] or not m['cases'] else ())
                    self.render_selection()
                    self.save_state()
                    self.status.set(f'已读取全部 {len(self.modules)} 个 Sheet。汇总页、空表及编号异常模块保留显示，禁止执行。')
                    self.refresh_coverage()
                elif kind == 'preflight':
                    self.status.set('连接检查通过；蓝牙眼镜的身份和绑定结果将在用例中验证。')
                    self.write_log(json.dumps(value, ensure_ascii=False))
                elif kind == 'run':
                    self.current_folder = value['folder']
                    self.total = value['total']
                    self.failure_details = {}
                    self.progress['maximum'] = max(1, self.total)
                    self.refresh_run_stats()
                    self.write_log('开始轮次：' + Path(self.current_folder).name)
                elif kind == 'batch_start':
                    self.current_folder = value['folder']
                    self.total = value['total']
                    self.failure_details = {}
                    self.progress['maximum'] = max(1, self.total)
                    self.refresh_run_stats()
                    self.write_log(f'开始串行批次：{value["models"]} 组 Sheet')
                elif kind == 'model_start':
                    self.status.set('正在执行型号：' + value)
                    self.write_log('开始型号：' + value)
                elif kind == 'model_run':
                    self.write_log(f'{value["model"]} 结果目录：{value["folder"]}')
                elif kind == 'model_error':
                    self.status.set(value)
                    self.write_log(value)
                elif kind == 'case_start':
                    self.status.set(f'正在执行：{value.get("model", "")} {value["sheet"]} / {value["id"]}')
                    self.current_case.set(f'正在执行：{value.get("model", "")} {value["sheet"]} / {value["id"]}')
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
                    elif value['status'] == 'INTERRUPTED':
                        self.interrupted += 1
                    self.refresh_run_stats()
                    self.progress['value'] = self.completed
                    self.show_case_result(value)
                    reason = brief_detail(value['detail'])
                    if value['status'] in ('FAIL', 'ERROR', 'BLOCKED'):
                        self.failure_details.setdefault(value['sheet'], f'{value["id"]} · {LABELS[value["status"]]}：{reason}')
                    self.status.set(f'{self.completed}/{self.total}  {value.get("model", "")} {value["sheet"]} / {value["id"]}：{LABELS[value["status"]]} — {reason}')
                    for row in self.tree.get_children():
                        if self.tree.set(row, 'module') == value['sheet']:
                            self.tree.set(row, 'progress', f'{value["id"]} · {LABELS[value["status"]]}：{reason}')
                elif kind == 'exporting':
                    self.stop_button.configure(state='disabled')
                    self.status.set('正在生成独立 Excel 结果文件并校验完整性…')
                elif kind == 'done':
                    self.stop_button.configure(state='disabled')
                    self.current_folder = value['folder']
                    counts = summarize_selected(value['summary'], self.selected)
                    self.total = sum(counts.values())
                    self.completed = self.total - counts['NOT_RUN'] - counts['RUNNING']
                    self.passed = counts['PASS']
                    self.failed = counts['FAIL'] + counts['ERROR']
                    self.blocked = counts['BLOCKED']
                    self.unimplemented = counts['NOT_IMPLEMENTED']
                    self.not_applicable = counts['NOT_APPLICABLE']
                    self.skipped = counts['SKIPPED']
                    self.interrupted = counts['INTERRUPTED']
                    self.refresh_run_stats()
                    for row in self.tree.get_children():
                        name = self.tree.set(row, 'module')
                        progress = ' / '.join(f'{LABELS[k]} {v}' for k, v in value['summary'].get(name, {}).items())
                        if name in self.failure_details:
                            progress += ' · ' + self.failure_details[name]
                        self.tree.set(row, 'progress', progress)
                    m = value['manifest']
                    result = '已停止' if m['state'] == 'INTERRUPTED' else ('执行异常：' + brief_detail(m.get('error', '未知错误')) if m['state'] == 'ERROR' else '本轮结束')
                    if value.get('models'):
                        result += f'；{len(value["models"])} 组 Sheet 已处理，{len(m.get("model_errors", []))} 组启动或准备异常'
                    text = result + '。' + ('Excel 已生成。' if m['export'] == 'SUCCESS' else 'Excel 导出失败，可重新导出：' + m.get('export_error', ''))
                    self.status.set(text)
                    self.current_case.set(text)
                    self.write_log(text + '  ' + self.current_folder)
                elif kind == 'reexport':
                    self.status.set('重新导出完成：' + value)
                elif kind == 'service':
                    self.status.set(value)
                    self.write_log(value)
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


