from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import queue
import sys
import time
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets as W
from .camera import MvsCamera, SimCamera, NODE_TYPES
from .display import ImageView, Histogram, ColorBar, render
from .pipeline import Pipeline, SaveRequest
from .processing import ProcessingOptions
from .storage import Settings

PAGES = ('RAW', 'Gray', 'AoLP', 'DoLP')
LABELS = {
    'ExposureAuto': '自动曝光', 'ExposureTime': '曝光时间 (μs)', 'GainAuto': '自动增益',
    'Gain': '增益 (dB)', 'PixelFormat': '像素格式', 'AcquisitionFrameRateEnable': '帧率控制',
    'AcquisitionFrameRate': '目标帧率 (fps)', 'AcquisitionMode': '采集模式', 'TriggerSelector': '触发选择器', 'TriggerMode': '触发模式',
    'TriggerSource': '触发源', 'TriggerActivation': '触发边沿 / 电平', 'TriggerDelay': '触发延时 (μs)',
    'AcquisitionBurstFrameCount': '每次触发帧数', 'TriggerCacheEnable': '触发缓存',
    'LineSelector': '输入线路', 'LineMode': '线路模式', 'LineDebouncerTime': '输入去抖 (μs)',
}


class SettingsDialog(W.QDialog):
    def __init__(self, settings, parent):
        super().__init__(parent)
        self.setWindowTitle('PolaMV · 软件设置')
        self.resize(550, 460)
        self.original = settings
        layout = W.QVBoxLayout(self)
        tabs = W.QTabWidget()
        layout.addWidget(tabs)
        processing, display, saving = W.QWidget(), W.QWidget(), W.QWidget()
        for widget, title in ((processing, '图像处理'), (display, '显示'), (saving, 'TIFF 保存')):
            tabs.addTab(widget, title)
        p = W.QFormLayout(processing)
        p.addRow('低信号阈值', W.QLabel('固定 2%FS · AoLP 和 DoLP 设为 NaN'))
        self.minimum_enabled = W.QCheckBox('启用最低 DoLP 对 AoLP 的有效性筛选')
        self.minimum_enabled.setChecked(settings.minimum_dolp_enabled)
        p.addRow(self.minimum_enabled)
        self.minimum = W.QDoubleSpinBox()
        self.minimum.setRange(0, 100)
        self.minimum.setSuffix(' %')
        self.minimum.setValue(settings.minimum_dolp*100)
        p.addRow('最低 DoLP', self.minimum)
        p.addRow(W.QLabel('不包含偏振标定和过曝报警。'))
        d = W.QFormLayout(display)
        self.aolp = W.QComboBox(); self.aolp.addItems(['HSV', 'Twilight']); self.aolp.setCurrentText(settings.aolp_map)
        self.dolp = W.QComboBox(); self.dolp.addItems(['Viridis', 'Cividis']); self.dolp.setCurrentText(settings.dolp_map)
        d.addRow('AoLP 周期色图', self.aolp); d.addRow('DoLP 连续色图', self.dolp)
        self.nan = W.QPushButton(settings.nan_color)
        self.nan.clicked.connect(self.choose_color)
        d.addRow('NaN 颜色', self.nan)
        self.sync = W.QCheckBox('各页面同步缩放与平移'); self.sync.setChecked(settings.sync_zoom)
        d.addRow(self.sync)
        s = W.QFormLayout(saving)
        folder_row = W.QWidget(); row = W.QHBoxLayout(folder_row); row.setContentsMargins(0, 0, 0, 0)
        self.folder = W.QLineEdit(settings.save_directory); row.addWidget(self.folder)
        browse = W.QPushButton('浏览'); browse.clicked.connect(self.choose_folder); row.addWidget(browse)
        s.addRow('保存目录', folder_row)
        self.prefix = W.QLineEdit(settings.prefix); s.addRow('文件名前缀', self.prefix)
        self.stamp = W.QCheckBox('文件名包含时间戳'); self.stamp.setChecked(settings.timestamp_names); s.addRow(self.stamp)
        self.auto = W.QCheckBox('外部触发自动保存'); self.auto.setChecked(settings.auto_save); s.addRow(self.auto)
        note = W.QLabel('保存接收时所选页面的定量数据。\nAoLP / DoLP 保存 float32 和真实 NaN。\n每个文件内附帧号、时间和相机参数。'); note.setWordWrap(True); s.addRow(note)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.Ok | W.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def choose_color(self):
        color = W.QColorDialog.getColor(QtGui.QColor(self.nan.text()), self, 'NaN 显示颜色')
        if color.isValid(): self.nan.setText(color.name())

    def choose_folder(self):
        path = W.QFileDialog.getExistingDirectory(self, 'TIFF 保存目录', self.folder.text())
        if path: self.folder.setText(path)

    def result_settings(self):
        return replace(self.original, minimum_dolp_enabled=self.minimum_enabled.isChecked(), minimum_dolp=self.minimum.value()/100,
                       save_directory=self.folder.text(), prefix=self.prefix.text(), timestamp_names=self.stamp.isChecked(),
                       auto_save=self.auto.isChecked(), aolp_map=self.aolp.currentText(), dolp_map=self.dolp.currentText(),
                       nan_color=self.nan.text(), sync_zoom=self.sync.isChecked())


class MainWindow(W.QMainWindow):
    def __init__(self, config_path=None):
        super().__init__()
        # Offscreen Windows sessions may not enumerate system fonts automatically.
        if 'Microsoft YaHei UI' not in QtGui.QFontDatabase.families():
            font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
            if font.exists(): QtGui.QFontDatabase.addApplicationFont(str(font))
        self.setWindowTitle('PolaMV Studio · 偏振相机采集与分析')
        self.resize(1460, 930)
        self.config_path = config_path or Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PolaMV/settings.json'
        load_error = None
        try:
            self.settings = Settings.load(self.config_path)
        except Exception as exc:
            self.settings = Settings(); load_error = f'设置文件无法读取，已使用默认值：{exc}'
        self.pipeline = Pipeline()
        self.camera = self.frame = None
        self.devices = []
        self.editors = {}
        self.building = False
        self.displayed = 0
        self.last_rates = (time.monotonic(), 0, 0, 0)
        self.fps_text = '接收 0.0 · 处理 0.0 · 显示 0.0 fps'
        self.zoom_states = {}
        self.previous_page = 'RAW'
        self._build()
        self.configure_pipeline()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick); self.timer.start(16)
        if load_error: self.log(load_error, True)
        self.log('就绪。请搜索并打开相机，或选择模拟相机。')
        self.update_controls()

    def button(self, text, action):
        button = W.QPushButton(text); button.clicked.connect(action); return button

    def _build(self):
        self.setStyleSheet('''
            QMainWindow,QDialog,QWidget { background:#142132; color:#dae4ef; font-family:"Microsoft YaHei UI"; font-size:12px; }
            QGroupBox { border:1px solid #304155; border-radius:6px; margin-top:12px; padding-top:14px; }
            QGroupBox::title { subcontrol-origin:margin; left:12px; color:#8ee5d2; }
            QPushButton { background:#273c52; border:1px solid #3b536b; padding:7px 12px; border-radius:4px; }
            QPushButton:hover { background:#35536e; } QPushButton:disabled { color:#65788a; background:#1c2c3e; }
            QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox { background:#0f1b29; padding:5px; border:1px solid #3b4d63; border-radius:3px; }
            QTabBar::tab { padding:9px 18px; background:#1c2e43; } QTabBar::tab:selected { background:#286366; color:white; }
            QPlainTextEdit { background:#0e1927; border:1px solid #304155; }
            QScrollArea { border:0; } QStatusBar { background:#0d1825; }
        ''')
        center = W.QWidget(); layout = W.QVBoxLayout(center); self.setCentralWidget(center)
        title_row = W.QHBoxLayout()
        title = W.QLabel('PolaMV  <span style="color:#74d7c8">STUDIO</span>'); title.setStyleSheet('font-size:24px; font-weight:600')
        title_row.addWidget(title); title_row.addStretch()
        self.mode_label = W.QLabel('未连接'); title_row.addWidget(self.mode_label)
        title_row.addWidget(self.button('软件设置', self.open_settings)); layout.addLayout(title_row)
        splitter = W.QSplitter(); layout.addWidget(splitter, 1)
        left_scroll = W.QScrollArea(); left_scroll.setWidgetResizable(True); left_scroll.setMinimumWidth(340)
        left_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        left = W.QWidget(); controls = W.QVBoxLayout(left); left_scroll.setWidget(left); splitter.addWidget(left_scroll)
        box = W.QGroupBox('设备连接'); b = W.QVBoxLayout(box); controls.addWidget(box)
        self.device_combo = W.QComboBox(); self.device_combo.addItem('模拟相机 · 无硬件演示', None); b.addWidget(self.device_combo)
        row = W.QHBoxLayout(); self.search_button = self.button('搜索相机', self.search); self.open_button = self.button('打开', self.toggle_open)
        row.addWidget(self.search_button); row.addWidget(self.open_button); b.addLayout(row)
        row = W.QHBoxLayout(); self.start_button = self.button('开始采集', self.toggle_capture); self.trigger_button = self.button('软件触发', self.trigger)
        row.addWidget(self.start_button); row.addWidget(self.trigger_button); b.addLayout(row)
        self.sim_trigger = self.button('模拟一次外部信号', self.trigger); b.addWidget(self.sim_trigger)
        self.device_info = W.QLabel('MV-CH050-10UP / USB 3.0'); self.device_info.setWordWrap(True); b.addWidget(self.device_info)
        self.node_tabs = W.QTabWidget(); controls.addWidget(self.node_tabs)
        self.camera_form = W.QFormLayout(); self.trigger_form = W.QFormLayout()
        for form, label in ((self.camera_form, '相机参数'), (self.trigger_form, '触发 / I/O')):
            panel = W.QWidget(); panel.setLayout(form); self.node_tabs.addTab(panel, label)
        self.refresh_button = self.button('刷新参数与可用范围', self.refresh_nodes); controls.addWidget(self.refresh_button)
        tips = W.QLabel('参数由相机实际能力决定。\n采集中修改参数会自动停止并恢复采集。\n默认不主动限制相机采集帧率。'); tips.setWordWrap(True); tips.setStyleSheet('color:#8fa1b6'); controls.addWidget(tips)
        controls.addStretch()
        viewer = W.QWidget(); v = W.QVBoxLayout(viewer); v.setContentsMargins(0, 0, 0, 0); splitter.addWidget(viewer)
        toolbar = W.QHBoxLayout(); self.tabs = W.QTabBar(); self.tabs.addTab('RAW'); self.tabs.addTab('Gray'); self.tabs.addTab('AoLP'); self.tabs.addTab('DoLP')
        self.tabs.currentChanged.connect(self.change_page); toolbar.addWidget(self.tabs); toolbar.addStretch()
        self.zoom_label = W.QLabel('100%'); toolbar.addWidget(self.zoom_label)
        toolbar.addWidget(self.button('适应', lambda: self.view.fit())); toolbar.addWidget(self.button('1:1', lambda: self.view.actual()))
        v.addLayout(toolbar)
        self.view = ImageView(); v.addWidget(self.view, 1)
        self.view.pixel.connect(self.query_pixel); self.view.zoom_changed.connect(lambda z: self.zoom_label.setText(f'{z*100:.1f}%'))
        self.colorbar = ColorBar(); self.colorbar.settings = self.settings; v.addWidget(self.colorbar)
        save_row = W.QHBoxLayout(); self.save_button = self.button('保存当前显示帧 · TIFF', self.save_current); save_row.addWidget(self.save_button)
        self.auto_box = W.QCheckBox('外触发自动保存'); self.auto_box.setChecked(self.settings.auto_save); self.auto_box.toggled.connect(self.toggle_auto); save_row.addWidget(self.auto_box); save_row.addStretch(); v.addLayout(save_row)
        self.frame_label = W.QLabel('等待第一帧'); v.addWidget(self.frame_label)
        right = W.QWidget(); r = W.QVBoxLayout(right); r.setContentsMargins(0, 0, 0, 0); splitter.addWidget(right)
        self.hist_title = self.button('直方图：总体 · 点击切换', self.toggle_histogram); r.addWidget(self.hist_title)
        self.histogram = Histogram(); self.histogram.toggled.connect(self.toggle_histogram); r.addWidget(self.histogram)
        self.pixel_label = W.QLabel('移动鼠标查看像素数据'); self.pixel_label.setMinimumHeight(105); self.pixel_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse); r.addWidget(self.pixel_label)
        self.details = W.QGroupBox('四方向与 Stokes 数据'); self.details.setCheckable(True); self.details.setChecked(False)
        d = W.QVBoxLayout(self.details); self.detail_label = W.QLabel('—'); self.detail_label.setVisible(False); self.details.toggled.connect(self.detail_label.setVisible); d.addWidget(self.detail_label); r.addWidget(self.details)
        self.log_view = W.QPlainTextEdit(); self.log_view.setReadOnly(True); self.log_view.setMaximumBlockCount(150); r.addWidget(self.log_view, 1)
        splitter.setSizes([360, 780, 300]); splitter.setStretchFactor(1, 1)
        self.status = W.QLabel(); self.statusBar().addWidget(self.status, 1)
        self.update_histogram_title()

    @property
    def page(self): return PAGES[self.tabs.currentIndex()]

    def log(self, message, error=False):
        self.log_view.appendPlainText(f'{time.strftime("%H:%M:%S")}  {"错误：" if error else ""}{message}')
        (logging.error if error else logging.info)(message)
        if error: self.statusBar().showMessage(message, 15000)

    def guard(self, action):
        try: return action()
        except Exception as exc:
            logging.exception('Operation failed')
            self.log(str(exc), True)
            return None

    def search(self):
        try:
            self.devices = MvsCamera.enumerate()
            self.device_combo.clear()
            for label, info in self.devices: self.device_combo.addItem(label, info)
            self.device_combo.addItem('模拟相机 · 无硬件演示', None)
            self.log(f'找到 {len(self.devices)} 台真实相机。')
        except Exception as exc: self.log(str(exc), True)

    def toggle_open(self):
        self.guard(self._toggle_open)
        self.update_controls()

    def _toggle_open(self):
        if self.camera:
            self.guard(self.pipeline.stop); self.remember_camera()
            self.guard(self.camera.close); self.camera = None
            self.clear_forms(); self.mode_label.setText('未连接'); self.log('相机已关闭。'); return
        info = self.device_combo.currentData()
        camera = SimCamera() if info is None else MvsCamera()
        try:
            camera.open(info)
            self.camera = camera
            self.restore_camera()
            self.refresh_nodes()
            self.frame = None
            self.mode_label.setText('模拟模式 · 非真实相机' if isinstance(camera, SimCamera) else '真实相机已连接')
            self.device_info.setText(f'{camera.metadata().get("model")}\nS/N {camera.metadata().get("serial")}')
            self.log('连接成功。真实相机偏振阵列方向仍需按验收步骤核对。')
        except Exception:
            camera.close(); self.camera = None; raise

    def clear_forms(self):
        for form in (self.camera_form, self.trigger_form):
            while form.rowCount(): form.removeRow(0)
        self.editors = {}

    def refresh_nodes(self):
        if not self.camera: return
        self.building = True
        try:
            nodes = self.camera.refresh()
            self.clear_forms()
            for key, node in nodes.items():
                if node.kind == 'enum':
                    editor = W.QComboBox()
                    for label, value in node.choices: editor.addItem(label, value)
                    editor.setCurrentIndex(editor.findData(node.value))
                    editor.activated.connect(lambda _, k=key, e=editor: self.apply_node(k, e.currentData()))
                elif node.kind == 'bool':
                    editor = W.QCheckBox(); editor.setChecked(node.value)
                    editor.clicked.connect(lambda value, k=key: self.apply_node(k, value))
                else:
                    editor = W.QDoubleSpinBox(); editor.setDecimals(0 if node.kind == 'int' else 3)
                    editor.setRange(node.minimum, node.maximum); editor.setValue(node.value)
                    editor.setKeyboardTracking(False)
                    editor.setSingleStep(node.increment or 1)
                    editor.setToolTip(f'最小 {node.minimum:g} / 最大 {node.maximum:g}\n步进：{node.increment if node.increment else "SDK 未提供固定步进"}')
                    editor.editingFinished.connect(lambda k=key, e=editor, kind=node.kind: self.apply_node(k, int(e.value()) if kind == 'int' else e.value()))
                editor.setEnabled(node.writable)
                form = self.trigger_form if key.startswith(('Trigger', 'Line')) or key == 'AcquisitionBurstFrameCount' else self.camera_form
                form.addRow(LABELS.get(key, key), editor)
                self.editors[key] = editor
        finally: self.building = False
        self.update_controls()

    def apply_node(self, key, value):
        if self.building or not self.camera or self.camera.nodes[key].value == value: return
        running = self.pipeline.running.is_set()
        try:
            if running: self.pipeline.stop()
            self.camera.set(key, value)
            self.remember_camera()
        except Exception as exc: self.log(str(exc), True)
        finally:
            self.refresh_nodes()
            if running: self.guard(lambda: self.pipeline.start(self.camera))
            self.update_controls()

    def remember_camera(self):
        if not self.camera: return
        identity = self.camera.metadata().get('serial', 'unknown')
        self.settings.camera_values[identity] = {k: n.value for k, n in self.camera.nodes.items()}

    def restore_camera(self):
        identity = self.camera.metadata().get('serial', 'unknown')
        saved = self.settings.camera_values.get(identity, {})
        for key in NODE_TYPES:
            if key not in saved: continue
            node = self.camera.refresh().get(key)
            if node is None or not node.writable: continue
            value = saved[key]
            if node.kind == 'enum' and value not in [v for _, v in node.choices]: continue
            if node.kind in ('int', 'float'):
                value = min(max(value, node.minimum), node.maximum)
                if node.kind == 'int' and node.increment:
                    value = int(node.minimum + round((value-node.minimum)/node.increment)*node.increment)
            try: self.camera.set(key, value)
            except Exception as exc: self.log(f'未恢复 {key}，保留相机当前值：{exc}')

    def toggle_capture(self):
        self.guard(lambda: self.pipeline.stop() if self.pipeline.running.is_set() else self.pipeline.start(self.camera))
        self.update_controls()

    def trigger(self):
        if self.camera: self.guard(self.camera.trigger)

    def update_controls(self):
        opened = self.camera is not None
        running = self.pipeline.running.is_set()
        self.open_button.setText('关闭' if opened else '打开')
        self.search_button.setEnabled(not opened); self.device_combo.setEnabled(not opened)
        self.start_button.setEnabled(opened); self.start_button.setText('停止采集' if running else '开始采集')
        meta = self.camera.metadata() if opened else {}
        self.trigger_button.setEnabled(running and meta.get('TriggerMode') == 'On' and meta.get('TriggerSource') == 'Software')
        self.sim_trigger.setVisible(isinstance(self.camera, SimCamera))
        self.sim_trigger.setEnabled(running and meta.get('TriggerMode') == 'On' and meta.get('TriggerSource') != 'Software')
        self.refresh_button.setEnabled(opened)
        self.save_button.setEnabled(self.frame is not None)

    def configure_pipeline(self):
        self.pipeline.configure(ProcessingOptions(self.settings.minimum_dolp_enabled, self.settings.minimum_dolp),
                                SaveRequest(self.page, self.settings.save_directory, self.settings.prefix, self.settings.timestamp_names), self.settings.auto_save)

    def toggle_auto(self, checked):
        self.settings.auto_save = checked; self.configure_pipeline()

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == W.QDialog.Accepted:
            self.settings = dialog.result_settings()
            self.auto_box.setChecked(self.settings.auto_save)
            self.configure_pipeline(); self.draw_frame(); self.guard(lambda: self.settings.save(self.config_path))

    def change_page(self):
        if hasattr(self, 'view'):
            self.zoom_states[self.previous_page] = (self.view.transform(), self.view.mapToScene(self.view.viewport().rect().center()), self.view.fit_mode)
            self.draw_frame()
            if not self.settings.sync_zoom:
                state = self.zoom_states.get(self.page)
                if state:
                    self.view.setTransform(state[0]); self.view.centerOn(state[1]); self.view.fit_mode = state[2]
                    self.view.zoom_changed.emit(state[0].m11())
                else: self.view.fit()
        self.previous_page = self.page
        self.configure_pipeline()

    def draw_frame(self):
        self.colorbar.page, self.colorbar.settings = self.page, self.settings; self.colorbar.update()
        if self.frame is not None:
            self.view.set_image(render(self.frame, self.page, self.settings))
            self.histogram.frame = self.frame; self.histogram.update()
            f = self.frame.source
            self.frame_label.setText(f'Frame {f.frame_id}  ·  {f.raw.shape[1]} × {f.raw.shape[0]}  ·  {f.bits} bit  ·  {f.timestamp}')

    def query_pixel(self, x, y):
        f = self.frame
        if f is None or x < 0 or y < 0 or y >= f.gray.shape[0] or x >= f.gray.shape[1]:
            self.pixel_label.setText('移动鼠标查看像素数据'); self.detail_label.setText('—'); return
        a, d = f.aolp[y, x], f.dolp[y, x]
        angle = 'NaN' if not np.isfinite(a) else f'{a:.2f}°'
        degree = 'NaN' if not np.isfinite(d) else f'{d*100:.2f}%'
        self.pixel_label.setText(f'X {x}   Y {y}\nRAW {f.source.raw[y,x]} DN\nGray {f.gray[y,x]:.2f} DN\nAoLP {angle}   ·   DoLP {degree}')
        i0, i45, i90, i135 = f.channels[:, y, x]
        self.detail_label.setText(f'I0  {i0:.2f}\nI45  {i45:.2f}\nI90  {i90:.2f}\nI135  {i135:.2f}\nS0  {2*f.gray[y,x]:.2f}\nS1  {i0-i90:.2f}\nS2  {i45-i135:.2f}')

    def update_histogram_title(self):
        self.histogram.four = self.settings.histogram_four
        self.hist_title.setText('直方图：四方向原始采样' if self.settings.histogram_four else '直方图：总体 Gray')
        self.histogram.update()

    def toggle_histogram(self):
        self.settings.histogram_four = not self.settings.histogram_four; self.update_histogram_title()

    def save_current(self):
        # Retain the displayed immutable frame, never ask the camera for a new one.
        if self.frame:
            request = SaveRequest(self.page, self.settings.save_directory, self.settings.prefix, self.settings.timestamp_names)
            self.guard(lambda: self.pipeline.enqueue_save(self.frame, request))

    def tick(self):
        frame = self.pipeline.take_latest()
        if frame is not None:
            self.frame = frame; self.displayed += 1; self.draw_frame(); self.save_button.setEnabled(True)
        for _ in range(20):
            try: kind, message = self.pipeline.events.get_nowait()
            except queue.Empty: break
            self.log(f'已保存 {message}' if kind == 'saved' else message, kind == 'error')
        now = time.monotonic()
        if now-self.last_rates[0] >= 1:
            last, received, processed, displayed = self.last_rates
            dt = now-last
            self.fps_text = f'接收 {(self.pipeline.received-received)/dt:.1f} · 处理 {(self.pipeline.processed-processed)/dt:.1f} · 显示 {(self.displayed-displayed)/dt:.1f} fps'
            self.last_rates = (now, self.pipeline.received, self.pipeline.processed, self.displayed)
            self.update_controls()
        meta = self.camera.metadata() if self.camera else {}
        state = '未连接' if not self.camera else '已连接 / 停止'
        if self.pipeline.running.is_set():
            triggered = meta.get('TriggerMode') == 'On'
            state = ('等待触发 / WAITING FOR TRIGGER' if now-self.pipeline.last_received > .5 else '已收到图像') if triggered else '连续采集'
        elif self.camera and self.camera.grabbing and self.pipeline.capture_done.is_set():
            self.guard(self.pipeline.stop)
        self.status.setText(f'{state} · {meta.get("TriggerSource", "")} · 延时 {meta.get("TriggerDelay", 0):g} μs  |  {self.fps_text}  |  接收 {self.pipeline.received} / 预览跳过 {self.pipeline.skipped} / 帧号缺口 {self.pipeline.transport_gaps} / 已保存 {self.pipeline.saved}')

    def closeEvent(self, event):
        self.timer.stop()
        self.guard(self.pipeline.close)
        self.remember_camera()
        if self.camera: self.guard(self.camera.close)
        self.guard(lambda: self.settings.save(self.config_path))
        event.accept()


def main():
    root = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PolaMV'
    root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('NUMBA_CACHE_DIR', str(root / 'numba-cache'))
    logging.basicConfig(filename=root/'polamv.log', encoding='utf-8', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    app = W.QApplication(sys.argv)
    app.setApplicationName('PolaMV Studio'); app.setOrganizationName('PolaMV')
    window = MainWindow(); window.show()
    if '--demo' in sys.argv:
        window.toggle_open(); window.toggle_capture()
    elif '--camera' in sys.argv:
        def connect_requested_camera():
            serial = sys.argv[sys.argv.index('--camera')+1]
            window.search()
            matches = [i for i in range(window.device_combo.count())
                       if serial in window.device_combo.itemText(i)]
            if len(matches) != 1:
                raise ValueError('未找到唯一匹配的真实相机：' + serial)
            window.device_combo.setCurrentIndex(matches[0])
            window.toggle_open()
            if window.camera:
                window.toggle_capture()
        window.guard(connect_requested_camera)
    return app.exec()
