import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FakeController:
    def __init__(self):
        self.calls = 0
        self.polls = 0

    def poll_once(self):
        self.polls += 1

    def build_ui_state(self):
        from control.UiState import UiState

        self.calls += 1
        return UiState.empty("complete_workpiece")


class QtUiBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_poll_once_emits_controller_snapshot(self):
        from control.QtUiBridge import QtUiBridge

        controller = FakeController()
        bridge = QtUiBridge(controller)
        received = []
        bridge.state_changed.connect(received.append)

        bridge.poll_once()

        self.assertEqual(controller.polls, 1)
        self.assertEqual(controller.calls, 1)
        self.assertEqual(received[-1].strategy_name, "complete_workpiece")
