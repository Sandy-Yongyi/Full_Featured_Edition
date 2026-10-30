from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QHeaderView, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QScrollArea, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from control.UiState import UiState
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
        root.setSpacing(10)

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
        layers.addStretch(1)
        self.point_count = QLabel("0 点")
        layers.addWidget(self.point_count)
        center.addLayout(layers)
        center.addWidget(self.point_cloud_view, 1)
        task_panel = Panel("当前任务")
        self.task_name = QLabel("等待任务")
        self.task_progress = QProgressBar()
        self.task_stage = QLabel("待机")
        task_panel.layout.addWidget(self.task_name)
        task_panel.layout.addWidget(self.task_progress)
        task_panel.layout.addWidget(self.task_stage)
        bottom = QHBoxLayout()
        bottom.addWidget(task_panel, 1)
        event_panel = Panel("最近事件")
        self.recent_events = RuntimeLogView()
        self.recent_events.setMaximumHeight(110)
        event_panel.layout.addWidget(self.recent_events)
        bottom.addWidget(event_panel, 2)
        center.addLayout(bottom)
        root.addLayout(center, 1)

        side = QVBoxLayout()
        chain_panel = Panel("生产控制")
        chain_panel.setMinimumWidth(230)
        self.chain_position = QLabel("当前位置  0 pulse")
        self.chain_status = QLabel("待机")
        self.scan_speed = QLabel("扫描速度  25 mm/s")
        self.start_button = ControlButton("▶  启动自动喷涂", "primary")
        self.stop_button = ControlButton("■  安全停止", "danger")
        if getattr(controller, "control_type", 2) == 3:
            self.start_button.setText("▶  导入 TXT 点云")
            self.stop_button.setText("■  停止查看")
        self.start_button.clicked.connect(self._start)
        self.stop_button.clicked.connect(self._stop)
        for widget in (self.chain_position, self.chain_status, self.scan_speed, self.start_button, self.stop_button):
            chain_panel.layout.addWidget(widget)
        side.addWidget(chain_panel)

        device_panel = Panel("设备联锁")
        self.plc_badge = StatusBadge("PLC 未连接")
        self.lidar_badge = StatusBadge("激光未就绪")
        self.servo_badge = StatusBadge("伺服未就绪")
        for widget in (self.plc_badge, self.lidar_badge, self.servo_badge):
            device_panel.layout.addWidget(widget)
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

    def apply_state(self, state: UiState) -> None:
        self.chain_position.setText(f"当前位置  {state.chain_position} pulse")
        self.chain_status.setText(state.chain_status)
        self.scan_speed.setText(f"扫描速度  {state.chain_speed} mm/s")
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
            badge.set_status(f"{name} · {device.detail if device else '未连接'}", bool(device and device.online))


class PlaceholderPage(QWidget):
    def __init__(self, title: str, description: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        panel = Panel(title)
        text = QLabel(description)
        text.setWordWrap(True)
        text.setStyleSheet(f"color: {theme.MUTED}; font-size: 14px;")
        panel.layout.addWidget(text)
        panel.layout.addStretch(1)
        layout.addWidget(panel, 1)


class AcquisitionPage(QWidget):
    """Inline scan status and speed settings, without a separate wx dialog."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._last_speed = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        summary = Panel("点云采集")
        self.position_value = QLabel("链条位置  0 pulse")
        self.status_value = QLabel("等待采集")
        self.preview_value = QLabel("预览数据将在采集后显示")
        for widget in (self.position_value, self.status_value, self.preview_value):
            summary.layout.addWidget(widget)
        summary.layout.addStretch(1)
        layout.addWidget(summary, 2)

        settings = Panel("采集参数")
        form = QFormLayout()
        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(1, 50)
        self.speed_spin.setSuffix(" mm/s")
        self.save_speed_button = ControlButton("保存扫描速度", "primary")
        self.save_speed_button.clicked.connect(self._save_speed)
        self.save_result = QLabel("")
        if getattr(controller, "preview_mode", False):
            self.speed_spin.setReadOnly(True)
            self.save_speed_button.setEnabled(False)
            self.save_result.setText("预览模式：扫描参数只读。")
        form.addRow("激光扫描与回零速度", self.speed_spin)
        settings.layout.addLayout(form)
        settings.layout.addWidget(self.save_speed_button)
        settings.layout.addWidget(self.save_result)
        settings.layout.addStretch(1)
        layout.addWidget(settings, 1)

    def _save_speed(self) -> None:
        try:
            if getattr(self.controller, "preview_mode", False):
                return
            if not authorize(self, self.controller):
                return
            setter = getattr(self.controller, "set_chain_speed", None)
            if not callable(setter):
                raise RuntimeError("当前控制器尚未接入扫描速度设置")
            setter(self.speed_spin.value())
            self.save_result.setText("扫描速度已保存")
            self.save_result.setStyleSheet(f"color: {theme.GREEN};")
        except Exception as exc:
            self.save_result.setText(f"保存失败：{exc}")
            self.save_result.setStyleSheet(f"color: {theme.RED};")

    def apply_state(self, state: UiState) -> None:
        if self._last_speed != state.chain_speed:
            self.speed_spin.setValue(state.chain_speed)
            self._last_speed = state.chain_speed
        self.position_value.setText(f"链条位置  {state.chain_position} pulse")
        self.status_value.setText(f"采集状态  {state.chain_status}")
        self.preview_value.setText(f"当前点数  {len(state.points):,} 点" if state.points is not None else "等待点云数据")


class TaskPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        summary = Panel("喷涂任务")
        self.task_value = QLabel("等待任务")
        self.stage_value = QLabel("待机")
        self.stage_value.setWordWrap(True)
        self.progress = QProgressBar()
        for widget in (self.task_value, self.stage_value, self.progress):
            summary.layout.addWidget(widget)
        layout.addWidget(summary)
        self.feedback_panel = Panel("运行明细")
        self.feedback_table = QTableWidget(0, 3)
        self.feedback_table.setHorizontalHeaderLabels(("反馈项目", "当前状态", "数据说明"))
        self.feedback_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.feedback_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.feedback_table.verticalHeader().setVisible(False)
        self.feedback_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.feedback_panel.layout.addWidget(self.feedback_table)
        self.feedback_panel.hide()
        layout.addWidget(self.feedback_panel, 1)
        self.gun_panel = gun_panel = Panel("xn_side 分枪计划")
        gun_panel.layout.addWidget(QLabel("显示当前工件的分枪计划；实际开枪状态等待设备反馈。"))
        self._last_task = None
        self.gun_table = QTableWidget(0, 5)
        self.gun_table.setHorizontalHeaderLabels(("设备 / 喷枪", "分枪计划", "喷涂分组", "Y 范围 / 角度", "工艺阶段"))
        self.gun_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.gun_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.gun_table.verticalHeader().setVisible(False)
        self.gun_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        gun_panel.layout.addWidget(self.gun_table)
        layout.addWidget(gun_panel, 1)

    def apply_state(self, state: UiState) -> None:
        task = state.task
        if task == self._last_task:
            return
        self._last_task = task
        self.task_value.setText(task.name)
        self.stage_value.setText(task.stage)
        apply_task_progress(self.progress, task.progress)
        self.feedback_panel.setVisible(bool(task.details))
        self.gun_panel.setVisible(state.strategy_name == "complete_workpiece" or bool(task.gun_plans))
        self.feedback_table.setRowCount(len(task.details))
        for row, detail in enumerate(task.details):
            for column, value in enumerate((detail.name, detail.status, detail.detail)):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.feedback_table.setItem(row, column, item)
        self.gun_table.setRowCount(len(task.gun_plans))
        groups = {"outside": "外框", "inside": "内框", "up": "顶面", "down": "底面"}
        for row, plan in enumerate(task.gun_plans):
            value_text = lambda value: "待反馈" if value is None else str(value)
            values = (
                f"SN {plan.machine_id} / 喷枪 {plan.gun_id}",
                "已选通（计划）" if plan.selected else "未选通（计划）",
                f"{groups.get(plan.group, plan.group)} · {value_text(plan.group_id)}",
                f"{value_text(plan.y_lower)}–{value_text(plan.y_upper)} mm / {value_text(plan.angle)}°", plan.stage,
            )
            for column, value in enumerate(values):
                self.gun_table.setItem(row, column, QTableWidgetItem(value))


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
        self._edit_unlocked = False
        self._password_required = True
        self._stopping = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(QLabel("设备"))
        self.device_selector = QComboBox()
        self.device_selector.currentIndexChanged.connect(self._load_device)
        self.reload_button = ControlButton("重新读取")
        self.reload_button.clicked.connect(self._reload_devices)
        header.addWidget(self.device_selector)
        header.addWidget(self.reload_button)
        self.edit_button = ControlButton("解锁编辑")
        self.edit_button.clicked.connect(self._toggle_edit)
        header.addWidget(self.edit_button)
        header.addStretch(1)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        footer = QHBoxLayout()
        self.save_result = QLabel("参数修改将在保存后写入当前策略配置。")
        self.save_button = ControlButton("保存设备参数", "primary")
        self.save_button.clicked.connect(self._save_device)
        if getattr(self.controller, "preview_mode", False):
            self.save_button.setEnabled(False)
            self.save_result.setText("预览模式：设备参数只读，不会写入生产配置。")
        footer.addWidget(self.save_result, 1)
        footer.addWidget(self.save_button)
        layout.addLayout(footer)
        self._reload_devices()

    def _reload_devices(self) -> None:
        from control.MachineConfigFrameControl import list_machine_devices

        self.device_selector.blockSignals(True)
        self.device_selector.clear()
        self._config_loaded = False
        self.tabs.clear()
        self._edit_unlocked = False
        self._sync_edit_controls()
        try:
            for sn, machine_type in list_machine_devices(self.strategy_name):
                self.device_selector.addItem(f"SN {sn} · {machine_type}", sn)
        except Exception as exc:
            self.save_result.setText(f"读取设备列表失败：{exc}")
        finally:
            self.device_selector.blockSignals(False)
        if self.device_selector.count():
            self._load_device()

    def _load_device(self) -> None:
        from control.MachineConfigFrameControl import load_machine_config_for_ui
        from control.MachineConfigSchema import PARAM_LABELS, parameter_order

        self.tabs.clear()
        self.fields = {}
        self.flat_fields = {}
        self._config_loaded = False
        self._edit_unlocked = False
        self._sync_edit_controls()
        sn = self.device_selector.currentData()
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
        self._add_config_tab("柜体参数", config, self.fields, order)
        if self.strategy_name == "complete_workpiece" and config.get("type") == "xn_side":
            flat = {**config, **(config.get("flat") or {})}
            flat.setdefault("z_spray_position", 500)
            self._add_config_tab("平板参数", flat, self.flat_fields, order + [("z_spray_position", PARAM_LABELS["z_spray_position"])])
        self._loaded_sn = sn
        self._loaded_strategy = self.strategy_name
        self._config_loaded = bool(self.fields)
        self._password_required = bool(getattr(self.controller, "is_password_required", lambda: False)())
        self._edit_unlocked = not self._password_required
        preview = getattr(self.controller, "preview_mode", False)
        self._sync_edit_controls()
        self.save_result.setText("预览模式：设备参数只读，不会写入生产配置。" if preview else
                                "参数已读取，解锁编辑后可修改。" if self._password_required else "参数已读取，保存时沿用原有范围校验。")

    def _sync_edit_controls(self) -> None:
        preview = getattr(self.controller, "preview_mode", False)
        editable = self._config_loaded and self._edit_unlocked and not preview and not self._stopping
        for field in (*self.fields.values(), *self.flat_fields.values()):
            field.setReadOnly(not editable)
        self.save_button.setEnabled(editable)
        self.edit_button.setEnabled(self._config_loaded and self._password_required and not preview and not self._stopping)
        self.edit_button.setText("只读预览" if preview else "无需密码" if not self._password_required else
                                 "锁定参数" if self._edit_unlocked else "解锁编辑")

    def _toggle_edit(self) -> None:
        if not self._config_loaded or getattr(self.controller, "preview_mode", False) or self._stopping:
            return
        if self._edit_unlocked:
            self._edit_unlocked = False
        else:
            target = (self._loaded_sn, self._loaded_strategy)
            allowed = authorize(self, self.controller)
            self._edit_unlocked = bool(allowed and not self._stopping and self._config_loaded and
                                       target == (self._loaded_sn, self._loaded_strategy))
        self._sync_edit_controls()
        self.save_result.setText("编辑已解锁，保存后生效。" if self._edit_unlocked else "参数保持只读，解锁编辑后可修改。")

    def _add_config_tab(self, title: str, config: dict, target: dict[str, QLineEdit], order: list[tuple[str, str]]) -> None:
        content = QWidget()
        form = QFormLayout(content)
        for key, label in order:
            field = QLineEdit(str(config.get(key, 100 if key == "x_status_offset" else "")))
            form.addRow(label, field)
            target[key] = field
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setWidget(content)
        self.tabs.addTab(scroller, title)

    def _save_device(self) -> None:
        from control.MachineConfigFrameControl import save_machine_config_from_ui

        try:
            if getattr(self.controller, "preview_mode", False) or not self._config_loaded or not self._edit_unlocked or self._stopping:
                return
            if self._loaded_sn != self.device_selector.currentData() or self._loaded_strategy != self.strategy_name:
                raise ValueError("设备或策略已改变，请重新读取参数")
            if not authorize(self, self.controller):
                self._edit_unlocked = False
                self._sync_edit_controls()
                self.save_result.setText("未获得保存授权，参数保持只读。")
                return
            if self._stopping or not self._edit_unlocked or self._loaded_sn != self.device_selector.currentData() or self._loaded_strategy != self.strategy_name:
                raise ValueError("运行或设备状态已改变，请重新读取并解锁参数")
            values = {key: int(field.text().strip()) for key, field in self.fields.items()}
            if self.flat_fields:
                values["flat"] = {key: int(field.text().strip()) for key, field in self.flat_fields.items()}
            control_queue = getattr(self.controller, "control_queue", None)
            save_machine_config_from_ui(
                self._loaded_sn, values,
                control_queue=control_queue,
                strategy_name=self.strategy_name,
            )
            self.save_result.setText("设备参数已保存，更新已加入控制队列。" if control_queue is not None else "设备参数已保存，将在下次启动时加载。")
            self.save_result.setStyleSheet(f"color: {theme.GREEN};")
            if self._password_required:
                self._edit_unlocked = False
                self._sync_edit_controls()
        except Exception as exc:
            self.save_result.setText(f"保存失败：{exc}")
            self.save_result.setStyleSheet(f"color: {theme.RED};")

    def apply_state(self, state: UiState) -> None:
        if self._stopping != state.stopping:
            self._stopping = state.stopping
            if state.stopping:
                self._edit_unlocked = False
            elif not self._password_required:
                self._edit_unlocked = True
            self._sync_edit_controls()
        if self.strategy_name != state.strategy_name:
            self.strategy_name = state.strategy_name
            self._reload_devices()


class RuntimeLogPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.level_filter = QComboBox()
        for label, levels in (("全部级别", ()), ("错误 / 严重", ("ERROR", "CRITICAL")),
                              ("警告", ("WARNING", "WARN")), ("信息", ("INFO",)), ("调试", ("DEBUG",))):
            self.level_filter.addItem(label, levels)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索日志内容或来源")
        self.match_count = QLabel("0 / 0 条")
        toolbar.addWidget(self.level_filter)
        toolbar.addWidget(self.search_input, 1)
        toolbar.addWidget(self.match_count)
        layout.addLayout(toolbar)
        self.log_view = RuntimeLogView()
        self._all_logs = ()
        self.level_filter.currentIndexChanged.connect(self._apply_filters)
        self.search_input.textChanged.connect(self._apply_filters)
        layout.addWidget(self.log_view)

    def apply_state(self, state: UiState) -> None:
        if state.logs == self._all_logs:
            return
        self._all_logs = state.logs
        self._apply_filters()

    def _apply_filters(self) -> None:
        levels = self.level_filter.currentData()
        query = self.search_input.text().strip().casefold()
        entries = tuple(event for event in self._all_logs
                        if (not levels or event.level.upper() in levels)
                        and (not query or query in event.message.casefold() or query in event.source.casefold()))
        self.log_view.apply_events(entries)
        self.match_count.setText(f"{len(entries)} / {len(self._all_logs)} 条")
