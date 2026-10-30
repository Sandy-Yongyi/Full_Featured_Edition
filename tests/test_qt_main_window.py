import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FakeController:
    def __init__(self):
        self.start_calls = 0
        self.stop_calls = 0

    def start(self):
        self.start_calls += 1

    def stop(self):
        self.stop_calls += 1


class IndustrialMainWindowTests(unittest.TestCase):
    def test_startup_error_is_displayed_without_escaping_qt_slot(self):
        from view.qt.main_window import IndustrialMainWindow

        controller = FakeController()
        window = IndustrialMainWindow(controller)
        with patch.object(controller, "start", side_effect=RuntimeError("PLC unavailable")):
            window.realtime_page._start()
        self.assertIn("PLC unavailable", window.realtime_page.chain_status.text())

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_exposes_all_workspace_routes(self):
        from view.qt.main_window import IndustrialMainWindow

        window = IndustrialMainWindow(controller=FakeController())
        self.assertEqual(
            window.route_names(),
            ("realtime", "acquisition", "tasks", "configuration", "logs"),
        )

    def test_running_state_keeps_stop_enabled(self):
        from control.UiState import UiState
        from view.qt.main_window import IndustrialMainWindow

        window = IndustrialMainWindow(controller=FakeController())
        window.apply_state(UiState.empty("complete_workpiece").__class__(
            strategy_name="complete_workpiece", running=True
        ))
        self.assertTrue(window.realtime_page.stop_button.isEnabled())

    def test_workspace_pages_accept_runtime_state_and_expose_inline_configuration(self):
        from control.UiState import TaskState, UiState
        from view.qt.main_window import IndustrialMainWindow

        window = IndustrialMainWindow(controller=FakeController())
        state = UiState(
            strategy_name="complete_workpiece",
            chain_speed=31,
            chain_position=12345,
            task=TaskState("柜体自动喷涂", "xn_side 分枪", 75, 6, 8),
        )
        window.apply_state(state)

        self.assertEqual(31, window.acquisition_page.speed_spin.value())
        self.assertIn("12345", window.acquisition_page.position_value.text())
        self.assertIn("xn_side", window.tasks_page.stage_value.text())
        self.assertEqual(0, window.tasks_page.gun_table.rowCount())
        self.assertIsNotNone(window.configuration_page.tabs)

    def test_header_status_follows_runtime_state(self):
        from control.UiState import UiState
        from view.qt.main_window import IndustrialMainWindow

        window = IndustrialMainWindow(controller=FakeController())
        window.apply_state(UiState(strategy_name="complete_workpiece", running=True, chain_status="运行中"))

        self.assertIn("运行中", window.system_status.text())

    def test_device_badges_keep_device_names_when_feedback_updates(self):
        from control.UiState import DeviceState, UiState
        from view.qt.main_window import IndustrialMainWindow
        window = IndustrialMainWindow(FakeController())
        window.apply_state(UiState(strategy_name="complete_workpiece", devices=(
            DeviceState("PLC", False, "未连接"), DeviceState("激光", False, "未连接"), DeviceState("伺服", False, "待确认"))))
        self.assertIn("PLC", window.realtime_page.plc_badge.text())
        self.assertIn("激光", window.realtime_page.lidar_badge.text())
        self.assertIn("伺服", window.realtime_page.servo_badge.text())

    def test_close_waits_for_safe_stop_and_then_closes(self):
        from control.UiState import UiState
        from PyQt6.QtGui import QCloseEvent
        from view.qt.main_window import IndustrialMainWindow

        controller = FakeController()
        window = IndustrialMainWindow(controller)
        window.apply_state(UiState(strategy_name="complete_workpiece", running=True))
        event = QCloseEvent()
        window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertEqual(1, controller.stop_calls)
        window.closeEvent(QCloseEvent())
        self.assertEqual(1, controller.stop_calls)
        window.apply_state(UiState(strategy_name="complete_workpiece"))
        self.app.processEvents()
        event = QCloseEvent()
        window.closeEvent(event)
        self.assertTrue(event.isAccepted())
