"""Exercise Qt close/preview routing without commanding hardware."""

import os
import queue
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from control.ControlCenter import ControlCenter
from model.telemetry.RuntimeStateCollector import RuntimeStateCollector
from view.qt.main_window import IndustrialMainWindow


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FullEditionUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_close_keeps_password_gate(self):
        from PyQt6.QtGui import QCloseEvent
        window = IndustrialMainWindow(SimpleNamespace())
        event = QCloseEvent()
        with patch("view.qt.main_window.authorize", return_value=False):
            window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertFalse(window._close_pending)

    def test_authorized_close_waits_for_saving_before_destroy(self):
        from PyQt6.QtGui import QCloseEvent
        from model.telemetry.UiState import UiState
        stopped = []
        window = IndustrialMainWindow(SimpleNamespace(stop=lambda: stopped.append(True)))
        window.apply_state(UiState(strategy_name="complete_workpiece", running=True))
        event = QCloseEvent()
        with patch("view.qt.main_window.authorize", return_value=True):
            window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertTrue(window._close_pending)
        self.assertEqual(stopped, [True])

    def test_saved_preview_is_not_downsampled_twice_and_preserves_boxes(self):
        cloud = np.zeros((210001, 3))
        boxes = object()
        messages = queue.Queue()
        messages.put({"points": cloud, "boxes": boxes, "preview_processed": True})
        collector = RuntimeStateCollector(queue.Queue(), SimpleNamespace(voxelReductionFilter=lambda *args, **kwargs: self.fail("preview processed twice")))
        collector.set_visualization_queue(messages)
        center = ControlCenter(SimpleNamespace(poll=collector.poll, start_pipeline=lambda: None, stop_pipeline=lambda: []), "complete_workpiece")
        center.poll_once()
        window = IndustrialMainWindow(center)
        window.apply_state(center.build_ui_state())
        self.assertIs(center.build_ui_state().points, cloud)
        self.assertEqual(len(window.realtime_page.point_cloud_view.points), 210001)
        self.assertIs(window.realtime_page.point_cloud_view.boxes_data, boxes)


if __name__ == "__main__":
    unittest.main()
