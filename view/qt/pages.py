from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QScrollArea, QSizePolicy, QTabWidget, QVBoxLayout, QWidget

from model.telemetry.UiState import UiState
from model.motionplan.motionutil.DeviceEnableHelper import validate_enable_transition
from view.qt.point_cloud_view import QtPointCloudView
from view.qt import theme
from view.qt.widgets import ControlButton, Panel, StatusBadge, RuntimeLogView
from view.qt.auth import authorize


def apply_task_progress(progress_bar: QProgressBar, progress: int | None) -> None:
    progress_bar.setRange(0, 100)
    progress_bar.setValue(0 if progress is None else max(0, min(100, progress)))
    progress_bar.setFormat("进度待反馈" if progress is None else "%p%")


class RealtimeControlPage(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._last_scene_points = object()
        self._last_scene_boxes = object()
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.ui_px(10))

        center = QVBoxLayout()
        self.point_cloud_view = QtPointCloudView()
        view_tools = QHBoxLayout()
        fit_button = ControlButton("适配视图")
        fit_button.clicked.connect(self.point_cloud_view.reset_camera)
        view_tools.addWidget(QLabel("三维工作区  ·  左键旋转 / 右键平移 / 滚轮缩放"))
        self.point_cloud_view.setToolTip("默认从 X 负方向观察，Z 轴水平、Y 轴竖直，网格位于 X–Z 地面。左键拖动旋转，右键拖动平移，滚轮缩放；双击点云设置旋转中心，适配视图恢复整体视角。")
        view_tools.addStretch(1)
        view_tools.addWidget(fit_button)
        center.addLayout(view_tools)
        layers = QHBoxLayout()
        self.layer_controls = {}
        for key, label in (("points", "点云"), ("outside", "外框"), ("inside", "内框"), ("jig", "挂具")):
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            checkbox.toggled.connect(lambda checked, layer=key: self.point_cloud_view.set_layer_visible(layer, checked))
            self.layer_controls[key] = checkbox
            layers.addWidget(checkbox)
        self._layer_strategy = None
        self._update_layer_controls(getattr(controller, "strategy_name", "frame_by_frame"))
        layers.addStretch(1)
        self.point_count = QLabel("0 点")
        layers.addWidget(self.point_count)
        center.addLayout(layers)
        center.addWidget(self.point_cloud_view, 1)
        task_panel = Panel("当前任务")
        self.task_name = QLabel("等待任务")
        self.task_progress = QProgressBar()
        self.task_stage = QLabel("待机")
        task_panel.content_layout.addWidget(self.task_name)
        task_panel.content_layout.addWidget(self.task_progress)
        task_panel.content_layout.addWidget(self.task_stage)
        bottom = QHBoxLayout()
        bottom.addWidget(task_panel, 1)
        event_panel = Panel("最近事件")
        self.recent_events = RuntimeLogView()
        self.recent_events.setMaximumHeight(theme.ui_px(110))
        event_panel.content_layout.addWidget(self.recent_events)
        bottom.addWidget(event_panel, 2)
        center.addLayout(bottom)
        root.addLayout(center, 1)

        side = QVBoxLayout()
        chain_panel = Panel("生产控制")
        chain_panel.setMinimumWidth(theme.ui_px(230))
        self.chain_position = QLabel("当前位置  0 pulse")
        self.chain_status = QLabel("待机")
        self.scan_speed = QLabel("链条运动速度  待反馈")
        self.start_button = ControlButton("▶  启动自动喷涂", "primary")
        self.stop_button = ControlButton("■  安全停止", "danger")
        if getattr(controller, "control_type", 2) == 3:
            self.start_button.setText("▶  导入 TXT 点云")
            self.stop_button.setText("■  停止查看")
        self.start_button.clicked.connect(self._start)
        self.stop_button.clicked.connect(self._stop)
        for widget in (self.chain_position, self.chain_status, self.scan_speed, self.start_button, self.stop_button):
            chain_panel.content_layout.addWidget(widget)
        side.addWidget(chain_panel)

        device_panel = Panel("设备联锁")
        self.plc_badge = StatusBadge("PLC 未连接")
        self.lidar_badge = StatusBadge("激光未就绪")
        self.servo_badge = StatusBadge("伺服未就绪")
        for widget in (self.plc_badge, self.lidar_badge, self.servo_badge):
            device_panel.content_layout.addWidget(widget)
        side.addWidget(device_panel)
        side.addStretch(1)
        root.addLayout(side)

    def _start(self) -> None:
        try:
            if authorize(self, self.controller) and hasattr(self.controller, "start"):
                self.controller.start()
        except Exception as exc:
            self.chain_status.setText(f"启动失败：{exc}")

    def _stop(self) -> None:
        try:
            if authorize(self, self.controller) and hasattr(self.controller, "stop"):
                self.controller.stop()
        except Exception as exc:
            self.chain_status.setText(f"停止失败：{exc}")

    def _update_layer_controls(self, strategy_name: str) -> None:
        if strategy_name == self._layer_strategy:
            return
        self._layer_strategy = strategy_name
        for key in ("outside", "inside", "jig"):
            self.layer_controls[key].setVisible(strategy_name == "complete_workpiece")

    def apply_state(self, state: UiState) -> None:
        self._update_layer_controls(state.strategy_name)
        self.chain_position.setText(f"当前位置  {state.chain_position} pulse")
        self.chain_status.setText(state.chain_status)
        speed = "待反馈" if state.chain_speed_mm_s is None else f"{state.chain_speed_mm_s * 0.06:.2f} m/min"
        self.scan_speed.setText(f"链条运动速度  {speed}")
        self.start_button.setEnabled(not state.running and not state.stopping)
        self.stop_button.setEnabled(state.running and not state.stopping)
        self.task_name.setText(state.task.name)
        self.task_stage.setText(state.task.stage)
        self.recent_events.apply_events(tuple(event for event in state.logs if event.source == "stdout")[-5:])
        apply_task_progress(self.task_progress, state.task.progress)
        if state.points is not self._last_scene_points:
            self.point_cloud_view.set_points(state.points)
            self.point_count.setText(f"{len(self.point_cloud_view.points):,} 点")
            self._last_scene_points = state.points
            if state.points is None:
                self._last_scene_boxes = object()
        if state.boxes is not self._last_scene_boxes:
            self.point_cloud_view.set_boxes(state.boxes)
            self._last_scene_boxes = state.boxes
        devices = {device.name: device for device in state.devices}
        for name, badge in (("PLC", self.plc_badge), ("激光", self.lidar_badge), ("伺服", self.servo_badge)):
            device = devices.get(name)
            detail = device.detail if device else "未连接"
            badge.set_status(f"{name} · {detail}" if detail else name, bool(device and device.online))


class DeviceControlPage(QWidget):
    DEVICE_NAMES = ("左侧内外顶", "左侧内外底", "左侧二维", "右侧内外顶", "右侧内外底", "右侧二维")

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._available = False
        self._last_mask = None
        self._pc_auto_mode = None
        self._all_safe = False
        layout = QVBoxLayout(self)
        panel = Panel("设备控制")
        title_item = panel.content_layout.itemAt(0)
        title_label = title_item.widget() if title_item is not None else None
        if isinstance(title_label, QLabel):
            title_label.setStyleSheet(f"font-weight: 700; color: {theme.CYAN};")
        self.enable_button = ControlButton("设备总使能")
        self.enable_button.setCheckable(True)
        self.enable_button.clicked.connect(self._send)
        self.device_grid = QGridLayout()
        self.device_grid.setHorizontalSpacing(theme.ui_px(20))
        self.device_grid.setVerticalSpacing(theme.ui_px(10))
        self.device_grid.addWidget(self.enable_button, 0, 0)
        self.enable_hint = QLabel("等待 PLC 通讯")
        self.enable_hint.setWordWrap(True)
        self.enable_hint.setStyleSheet("color: #ffffff;")
        self.device_grid.addWidget(self.enable_hint, 0, 1)
        for column, title in enumerate(("左侧设备", "右侧设备")):
            label = QLabel(title)
            label.setStyleSheet(f"font-weight: 700; color: {theme.CYAN};")
            self.device_grid.addWidget(label, 1, column)
            self.device_grid.setColumnStretch(column, 1)
        self.device_buttons = []
        for index, name in enumerate(self.DEVICE_NAMES):
            button = ControlButton(name)
            button.setCheckable(True)
            button.clicked.connect(self._send)
            self.device_buttons.append(button)
            self.device_grid.addWidget(button, index % 3 + 2, index // 3)
        panel.content_layout.addLayout(self.device_grid)
        layout.addWidget(panel)
        layout.addStretch(1)
        self._sync()

    def _sync(self):
        signature = (self._available, self._pc_auto_mode, self._all_safe, self.enable_button.isChecked(), tuple(b.isChecked() for b in self.device_buttons))
        if signature == getattr(self, "_last_sync_signature", None):
            return
        enabled = self.enable_button.isChecked()
        can_close = self._all_safe and not any(b.isChecked() for b in self.device_buttons)
        self.enable_button.setEnabled(self._available and (can_close if enabled else self._pc_auto_mode is True))
        hint = "等待 PLC 通讯" if not self._available else "等待PC自动模式反馈，无法使能"
        if self._available:
            if enabled:
                hint = "设备已全部关闭并安全回位，可关闭使能" if can_close else "设备未全部关闭并安全回位，无法关闭使能"
            elif self._pc_auto_mode is not None:
                hint = "PC自动模式可开启使能" if self._pc_auto_mode else "PLC点动模式无法使能"
        self.enable_hint.setText(hint)
        for button in self.device_buttons:
            if not enabled:
                button.setChecked(False)
            button.setEnabled(self._available and enabled)
        for button in (self.enable_button, *self.device_buttons):
            button.setStyleSheet(f"background: #12613f; border-color: {theme.GREEN}; color: #ffffff;" if button.isChecked() else "")
        self._last_sync_signature = (self._available, self._pc_auto_mode, self._all_safe, self.enable_button.isChecked(), tuple(b.isChecked() for b in self.device_buttons))

    def _send(self):
        try:
            if not self._available:
                raise RuntimeError("PLC 未连接或正在停止")
            if not authorize(self, self.controller):
                self._set_mask(self._last_mask or 0)
                return
            mask = 0
            if self.enable_button.isChecked():
                mask = 1 | sum(1 << i for i, b in enumerate(self.device_buttons, 1) if b.isChecked())
            validate_enable_transition(self._last_mask or 0, mask, self._pc_auto_mode, self._all_safe)
            self.controller.set_device_enable_mask(mask)
            self._last_mask = mask
            self._sync()
        except Exception as exc:
            self._set_mask(self._last_mask or 0)
            self.enable_hint.setText(str(exc))

    def _set_mask(self, mask):
        self.enable_button.setChecked(bool(mask & 1))
        for i, button in enumerate(self.device_buttons, 1):
            button.setChecked(bool(mask & (1 << i)))
        self._sync()

    def apply_state(self, state):
        self._pc_auto_mode = state.pc_auto_mode
        self._all_safe = state.all_devices_safe
        self._available = state.running and not state.stopping and any(d.name == "PLC" and d.online for d in state.devices)
        mask = state.device_enable_mask if self._available else 0
        if mask != self._last_mask or not self._available:
            self._last_mask = mask
            self._set_mask(mask)
        self._sync()


class DeviceConfigurationPage(QWidget):
    """Inline editor backed by the same persistence service as the wx dialog."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.strategy_name = getattr(controller, "strategy_name", "complete_workpiece")
        self.fields: dict[str, QLineEdit] = {}
        self.flat_fields: dict[str, QLineEdit] = {}
        self._loaded_sn = None
        self._loaded_strategy = None
        self._config_loaded = False
        self._stopping = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.ui_px(16))
        self.selected_device_sn = None
        self.device_buttons = {}
        self.device_sidebar = QWidget()
        self.device_sidebar.setFixedWidth(theme.ui_px(190))
        sidebar_layout = QVBoxLayout(self.device_sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        self.device_grid = QGridLayout()
        self.device_grid.setVerticalSpacing(theme.ui_px(8))
        sidebar_layout.addLayout(self.device_grid)
        sidebar_layout.addStretch(1)
        layout.addWidget(self.device_sidebar)
        editor = QVBoxLayout()
        layout.addLayout(editor, 1)
        self.parameter_title = QLabel("设备参数")
        self.parameter_title.setStyleSheet(f"font-weight: 700; font-size: {theme.ui_px(16)}px; color: {theme.CYAN};")
        editor.addWidget(self.parameter_title)
        self.tabs = QTabWidget()
        editor.addWidget(self.tabs, 1)
        footer = QHBoxLayout()
        self.save_result = QLabel("参数可直接修改，点击保存才生效")
        self.save_result.setStyleSheet("color: #ffffff;")
        self.save_result.setWordWrap(True)
        self.save_button = ControlButton("保存设备参数", "primary")
        self.save_button.clicked.connect(self._save_device)
        if getattr(self.controller, "preview_mode", False):
            self.save_button.setEnabled(False)
            self.save_result.setText("预览模式：设备参数只读，不会写入生产配置。")
        footer.addWidget(self.save_result, 1)
        footer.addWidget(self.save_button)
        editor.addLayout(footer)
        self._reload_devices()

    def _reload_devices(self) -> None:
        from model.utils.MachineConfiguration import list_machine_devices

        previous_sn = self.selected_device_sn
        self.selected_device_sn = None
        self.parameter_title.setText("设备参数")
        self.device_buttons = {}
        while self.device_grid.count():
            item = self.device_grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self._config_loaded = False
        self.tabs.clear()
        self.fields = {}
        self.flat_fields = {}
        self._sync_edit_controls()
        try:
            devices = list_machine_devices(self.strategy_name)
            for index, (sn, machine_type) in enumerate(devices):
                standard = self.strategy_name == "frame_by_frame" and 0 <= sn < 6
                name = DeviceControlPage.DEVICE_NAMES[sn] if standard else f"SN {sn} · {machine_type}"
                button = ControlButton(name)
                button.setCheckable(True)
                button.clicked.connect(lambda checked=False, device_sn=sn: self._select_device(device_sn))
                self.device_buttons[sn] = button
                self.device_grid.addWidget(button, index, 0)
        except Exception as exc:
            self.save_result.setText(f"读取设备列表失败：{exc}")
        if self.device_buttons:
            self._select_device(previous_sn if previous_sn in self.device_buttons else next(iter(self.device_buttons)))

    def _select_device(self, sn):
        self.selected_device_sn = sn
        for device_sn, button in self.device_buttons.items():
            selected = device_sn == sn
            button.setChecked(selected)
            button.setStyleSheet(f"QPushButton {{ border: 2px solid {theme.CYAN}; background: #0d6174; color: #ffffff; font-weight: 700; }}" if selected else "")
        self.parameter_title.setText(f"{self.device_buttons[sn].text()}设备参数")
        self._load_device()

    def _load_device(self) -> None:
        from model.utils.MachineConfiguration import load_machine_config_for_ui
        from view.qt.MachineConfigSchema import PARAM_LABELS, parameter_order

        self.tabs.clear()
        self.fields = {}
        self.flat_fields = {}
        self._config_loaded = False
        self._sync_edit_controls()
        sn = self.selected_device_sn
        if sn is None:
            return
        try:
            config = load_machine_config_for_ui(sn, self.strategy_name)
            if not config.get("type"):
                raise ValueError(f"SN {sn} 缺少设备类型")
        except Exception as exc:
            self.save_result.setText(f"读取配置失败：{exc}")
            return
        order = parameter_order(sn, config, self.strategy_name)
        self._add_config_tab("参数", config, self.fields, order)
        if self.strategy_name == "complete_workpiece" and config.get("type") == "xn_side":
            flat = {**config, **(config.get("flat") or {})}
            flat.setdefault("z_spray_position", 500)
            self._add_config_tab("平板参数", flat, self.flat_fields, order + [("z_spray_position", PARAM_LABELS["z_spray_position"])])
        self._loaded_sn = sn
        self._loaded_strategy = self.strategy_name
        self._config_loaded = bool(self.fields)
        preview = getattr(self.controller, "preview_mode", False)
        self._sync_edit_controls()
        self.save_result.setStyleSheet("color: #ffffff;")
        self.save_result.setText("预览模式：设备参数只读，不会写入生产配置。" if preview else "参数可直接修改，点击保存才生效")

    def _sync_edit_controls(self) -> None:
        preview = getattr(self.controller, "preview_mode", False)
        editable = self._config_loaded and not preview and not self._stopping
        for field in (*self.fields.values(), *self.flat_fields.values()):
            field.setReadOnly(not editable)
        self.save_button.setEnabled(editable)

    def _add_config_tab(self, title: str, config: dict, target: dict[str, QLineEdit], order: list[tuple[str, str]]) -> None:
        content = QWidget()
        form = QGridLayout(content)
        form.setHorizontalSpacing(theme.ui_px(12))
        form.setVerticalSpacing(theme.ui_px(4))
        rows = len(order)
        for index, (key, label) in enumerate(order):
            field = QLineEdit(str(config.get(key, 100 if key == "x_status_offset" else "")))
            field.setStyleSheet(f"padding: {theme.ui_px(4)}px;")
            field.setMinimumWidth(0)
            field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row = index
            caption = QLabel(label)
            caption.setWordWrap(False)
            caption.setMinimumWidth(caption.sizeHint().width())
            form.addWidget(caption, row, 0)
            form.addWidget(field, row, 1)
            form.setColumnStretch(1, 1)
            target[key] = field
        form.setRowStretch(rows, 1)
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroller.setWidget(content)
        self.tabs.addTab(scroller, title)

    def _save_device(self) -> None:
        from model.utils.MachineConfiguration import save_machine_config_from_ui
        try:
            if getattr(self.controller, "preview_mode", False) or not self._config_loaded or self._stopping:
                return
            target = (self._loaded_sn, self._loaded_strategy, tuple(self.fields.values()), tuple(self.flat_fields.values()))
            if self._loaded_sn != self.selected_device_sn or self._loaded_strategy != self.strategy_name:
                raise ValueError("设备或策略已改变，请重新选择设备")
            if not authorize(self, self.controller):
                self.save_result.setText("未获得保存授权，修改尚未保存。")
                return
            current = (self._loaded_sn, self._loaded_strategy, tuple(self.fields.values()), tuple(self.flat_fields.values()))
            if self._stopping or target != current or self._loaded_sn != self.selected_device_sn or self._loaded_strategy != self.strategy_name:
                raise ValueError("运行或设备状态已改变，请重新选择设备后保存")
            if self._loaded_sn is None:
                raise ValueError("尚未选择设备")
            values: dict[str, int | dict[str, int]] = {key: int(field.text().strip()) for key, field in self.fields.items()}
            if self.flat_fields:
                values["flat"] = {key: int(field.text().strip()) for key, field in self.flat_fields.items()}
            control_queue = getattr(self.controller, "control_queue", None)
            save_machine_config_from_ui(self._loaded_sn, values, control_queue=control_queue, strategy_name=self.strategy_name)
            self.save_result.setText("设备参数已保存，更新已加入控制队列。" if control_queue is not None else "设备参数已保存，将在下次启动时加载。")
            self.save_result.setStyleSheet(f"color: {theme.GREEN};")
        except Exception as exc:
            self.save_result.setText(f"保存失败：{exc}")
            self.save_result.setStyleSheet(f"color: {theme.RED};")

    def apply_state(self, state: UiState) -> None:
        if self._stopping != state.stopping:
            self._stopping = state.stopping
            self._sync_edit_controls()
        if self.strategy_name != state.strategy_name:
            self.strategy_name = state.strategy_name
            self._reload_devices()
