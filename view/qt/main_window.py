from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from model.telemetry.UiState import UiState
from view.qt.pages import DeviceConfigurationPage, RealtimeControlPage, DeviceControlPage
from view.qt.theme import CYAN, MUTED, build_industrial_stylesheet, ui_px
from view.qt.auth import authorize


class IndustrialMainWindow(QMainWindow):
    ROUTES = ("realtime", "device_control", "configuration")
    ROUTE_LABELS = ("实时控制", "设备控制", "设备配置")

    def __init__(self, controller, bridge=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.bridge = bridge
        self._last_state = UiState.empty(getattr(controller, "strategy_name", "complete_workpiece"))
        self._close_pending = False
        self._close_authorized = False
        self._last_header = None
        self._last_alarm_text = None
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
        layout.setContentsMargins(ui_px(12), ui_px(10), ui_px(12), ui_px(12))
        layout.setSpacing(ui_px(10))

        header = QHBoxLayout()
        brand = QLabel("◆  JOIHEY · 智能喷涂控制中心")
        brand.setStyleSheet(f"font-weight: 700; font-size: {ui_px(17)}px; color: {CYAN};")
        header.addWidget(brand)
        header.addStretch(1)
        self.system_status = QLabel("● 系统待机")
        self.system_status.setStyleSheet(f"color: {MUTED};")
        header.addWidget(self.system_status)
        layout.addLayout(header)
        self.alarm_banner = QLabel()
        self.alarm_banner.setTextFormat(Qt.TextFormat.PlainText)
        self.alarm_banner.setWordWrap(True)
        self.alarm_banner.setStyleSheet(f"background: #3b202b; color: #ffd8da; border: 1px solid #7d3645; border-radius: {ui_px(6)}px; padding: {ui_px(10)}px;")
        self.alarm_banner.hide()
        self.alarm_scroll = QScrollArea()
        self.alarm_scroll.setWidgetResizable(True)
        self.alarm_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.alarm_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.alarm_scroll.setMaximumHeight(ui_px(120))
        self.alarm_scroll.setWidget(self.alarm_banner)
        self.alarm_scroll.hide()
        layout.addWidget(self.alarm_scroll)

        content = QHBoxLayout()
        self.navigation = QListWidget()
        self.navigation.setFixedWidth(ui_px(190))
        for label in self.ROUTE_LABELS:
            self.navigation.addItem(QListWidgetItem(label))
        self.navigation.currentRowChanged.connect(self._change_page)
        content.addWidget(self.navigation)

        self.workspace = QStackedWidget()
        self.realtime_page = RealtimeControlPage(self.controller)
        self.device_control_page = DeviceControlPage(self.controller)
        self.configuration_page = DeviceConfigurationPage(self.controller)
        for page in (self.realtime_page, self.device_control_page, self.configuration_page):
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
        header = (("● 系统停止中", "#ffb351") if state.stopping else (f"● {state.chain_status}", "#2bd49d") if state.running else ("● 系统待机", MUTED))
        if header != self._last_header:
            self.system_status.setText(header[0])
            self.system_status.setStyleSheet(f"color: {header[1]};")
            self._last_header = header
        self.realtime_page.apply_state(state)
        self.device_control_page.apply_state(state)
        self.configuration_page.apply_state(state)
        if self._close_pending and not state.running and not state.stopping:
            QTimer.singleShot(0, self.close)

    def _set_alarm_text(self, text: str) -> None:
        if text == self._last_alarm_text:
            return
        self._last_alarm_text = text
        self.alarm_banner.setText(text)
        self.alarm_banner.setVisible(bool(text))
        self.alarm_scroll.setVisible(bool(text))

    def _show_bridge_error(self, title: str, detail: str) -> None:
        lines = tuple(self._last_state.alarms) + (f"{title}：{detail}",)
        self._set_alarm_text("\n".join(dict.fromkeys(lines)))

    def closeEvent(self, a0) -> None:
        event = a0
        if event is None:
            return
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
