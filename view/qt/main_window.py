from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from control.UiState import UiState
from view.qt.pages import AcquisitionPage, DeviceConfigurationPage, RealtimeControlPage, RuntimeLogPage, TaskPage
from view.qt.theme import CYAN, MUTED, build_industrial_stylesheet
from view.qt.auth import authorize


class IndustrialMainWindow(QMainWindow):
    ROUTES = ("realtime", "acquisition", "tasks", "configuration", "logs")
    ROUTE_LABELS = ("实时控制", "点云采集", "喷涂任务", "设备配置", "运行记录")

    def __init__(self, controller, bridge=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.bridge = bridge
        self._last_state = UiState.empty(getattr(controller, "strategy_name", "complete_workpiece"))
        self._close_pending = False
        self._close_authorized = False
        self.setWindowTitle("JOIHEY · 智能喷涂控制中心")
        control_type = getattr(controller, "control_type", 2)
        if control_type in (1, 3):
            self.setWindowTitle(self.windowTitle() + (" · 开发调试：TXT 联调 PLC" if control_type == 1 else " · 开发调试：只画图"))
        self.setMinimumSize(1200, 760)
        self.setStyleSheet(build_industrial_stylesheet())
        self._build_ui()
        if bridge is not None and hasattr(bridge, "state_changed"):
            bridge.state_changed.connect(self.apply_state)
        if bridge is not None and hasattr(bridge, "error_raised"):
            bridge.error_raised.connect(self._show_bridge_error)

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        brand = QLabel("◆  JOIHEY · 智能喷涂控制中心")
        brand.setStyleSheet(f"font-weight: 700; font-size: 17px; color: {CYAN};")
        header.addWidget(brand)
        header.addStretch(1)
        self.system_status = QLabel("● 系统待机")
        self.system_status.setStyleSheet(f"color: {MUTED};")
        header.addWidget(self.system_status)
        layout.addLayout(header)
        self.alarm_banner = QLabel()
        self.alarm_banner.setTextFormat(Qt.TextFormat.PlainText)
        self.alarm_banner.setWordWrap(True)
        self.alarm_banner.setStyleSheet("background: #3b202b; color: #ffd8da; border: 1px solid #7d3645; border-radius: 6px; padding: 10px;")
        self.alarm_banner.hide()
        self.alarm_scroll = QScrollArea()
        self.alarm_scroll.setWidgetResizable(True)
        self.alarm_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.alarm_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.alarm_scroll.setMaximumHeight(120)
        self.alarm_scroll.setWidget(self.alarm_banner)
        self.alarm_scroll.hide()
        layout.addWidget(self.alarm_scroll)

        content = QHBoxLayout()
        self.navigation = QListWidget()
        self.navigation.setFixedWidth(190)
        for label in self.ROUTE_LABELS:
            self.navigation.addItem(QListWidgetItem(label))
        self.navigation.currentRowChanged.connect(self._change_page)
        content.addWidget(self.navigation)

        self.workspace = QStackedWidget()
        self.realtime_page = RealtimeControlPage(self.controller)
        self.acquisition_page = AcquisitionPage(self.controller)
        self.tasks_page = TaskPage()
        self.configuration_page = DeviceConfigurationPage(self.controller)
        self.logs_page = RuntimeLogPage()
        for page in (self.realtime_page, self.acquisition_page, self.tasks_page, self.configuration_page, self.logs_page):
            self.workspace.addWidget(page)
        content.addWidget(self.workspace, 1)
        layout.addLayout(content, 1)
        self.navigation.setCurrentRow(0)

    def route_names(self) -> tuple[str, ...]:
        return self.ROUTES

    def _change_page(self, index: int) -> None:
        if index >= 0:
            self.workspace.setCurrentIndex(index)

    def apply_state(self, state: UiState) -> None:
        self._last_state = state
        self._set_alarm_text("\n".join(dict.fromkeys(state.alarms)))
        if state.stopping:
            self.system_status.setText("● 系统停止中")
            self.system_status.setStyleSheet("color: #ffb351;")
        elif state.running:
            self.system_status.setText(f"● {state.chain_status}")
            self.system_status.setStyleSheet("color: #2bd49d;")
        else:
            self.system_status.setText("● 系统待机")
            self.system_status.setStyleSheet(f"color: {MUTED};")
        self.realtime_page.apply_state(state)
        self.acquisition_page.apply_state(state)
        self.tasks_page.apply_state(state)
        self.configuration_page.apply_state(state)
        self.logs_page.apply_state(state)
        if self._close_pending and not state.running and not state.stopping:
            QTimer.singleShot(0, self.close)

    def _set_alarm_text(self, text: str) -> None:
        self.alarm_banner.setText(text)
        self.alarm_banner.setVisible(bool(text))
        self.alarm_scroll.setVisible(bool(text))

    def _show_bridge_error(self, title: str, detail: str) -> None:
        lines = tuple(self._last_state.alarms) + (f"{title}：{detail}",)
        self._set_alarm_text("\n".join(dict.fromkeys(lines)))

    def closeEvent(self, event) -> None:
        if not self._close_authorized:
            if not authorize(self, self.controller):
                event.ignore()
                return
            self._close_authorized = True
        state = self._last_state
        if state.running or state.stopping:
            event.ignore()
            if not self._close_pending:
                self._close_pending = True
                self.system_status.setText("● 正在安全停止，完成后关闭窗口")
                if state.running:
                    try:
                        self.controller.stop()
                    except Exception as exc:
                        self._close_pending = False
                        self._close_authorized = False
                        self.system_status.setText(f"● 停止失败：{exc}")
            return
        if self.bridge is not None:
            self.bridge.stop()
        self.realtime_page.point_cloud_view.release_gl_resources()
        event.accept()
