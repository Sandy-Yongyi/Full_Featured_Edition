"""Preview the PyQt6 industrial UI with an empty scene and no hardware workers."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from model.telemetry.UiState import DeviceState, LogEvent, TaskState, UiState
from view.qt.QtUiBridge import QtUiBridge
from view.qt.main_window import IndustrialMainWindow
from model.runtime.app_bootstrap import prepare_environment


class PreviewController:
    def __init__(self):
        self._running = False
        self.preview_mode = True

    def start(self) -> bool:
        self._running = True
        return True

    def stop(self) -> bool:
        self._running = False
        return True

    def build_ui_state(self) -> UiState:
        return UiState(
            strategy_name="complete_workpiece",
            running=self._running,
            chain_position=0,
            chain_speed=25,
            chain_status="预览运行中" if self._running else "待机",
            devices=(
                DeviceState("PLC", False, "预览模式 · 未连接"),
                DeviceState("激光", False, "预览模式 · 未连接"),
                DeviceState("伺服", False, "预览模式 · 未连接"),
            ),
            task=TaskState(),
            logs=(LogEvent("INFO", "预览模式：未连接任何生产设备", "preview"),),
        )


def main() -> int:
    prepare_environment()
    app = QApplication.instance() or QApplication(sys.argv)
    controller = PreviewController()
    bridge = QtUiBridge(controller)
    window = IndustrialMainWindow(controller, bridge)
    window.apply_state(controller.build_ui_state())
    window.showMaximized()
    bridge.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
