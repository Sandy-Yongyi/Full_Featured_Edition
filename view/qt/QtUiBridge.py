"""Thread-safe Qt polling bridge for an existing control controller."""

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from model.telemetry.UiState import UiState


class QtUiBridge(QObject):
    state_changed = pyqtSignal(object)
    error_raised = pyqtSignal(str, str)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.poll_once)

    def start(self, interval_ms: int = 1000) -> None:
        self._timer.start(interval_ms)

    def stop(self) -> None:
        self._timer.stop()

    def poll_once(self) -> None:
        try:
            poll_runtime = getattr(self.controller, "poll_once", None)
            if callable(poll_runtime):
                poll_runtime()
            state = self.controller.build_ui_state()
            if not isinstance(state, UiState):
                raise TypeError("build_ui_state must return UiState")
            self.state_changed.emit(state)
        except Exception as exc:
            self.error_raised.emit("界面状态更新失败", str(exc))
