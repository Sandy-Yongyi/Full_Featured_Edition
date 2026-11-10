import os
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class SceneUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_repeated_status_snapshots_do_not_upload_same_cloud_again(self):
        from model.telemetry.UiState import UiState
        from view.qt.pages import RealtimeControlPage
        page = RealtimeControlPage(SimpleNamespace())
        state = UiState(strategy_name="complete_workpiece", points=np.ones((10, 3)))
        with patch.object(page.point_cloud_view, "set_points") as upload:
            page.apply_state(state)
            page.apply_state(state)
        self.assertEqual(1, upload.call_count)

    def test_empty_poll_keeps_scene_but_explicit_box_clear_removes_boxes(self):
        from control.ControlCenter import ControlCenter
        from model.telemetry.RuntimeStateCollector import RuntimeStateCollector
        from view.qt.pages import RealtimeControlPage
        frames = queue.Queue()
        collector = RuntimeStateCollector(queue.Queue(), None, preview_voxel_mm=0)
        collector.set_visualization_queue(frames)
        runtime = SimpleNamespace(poll=collector.poll, start_pipeline=lambda: None, stop_pipeline=lambda: [])
        center = ControlCenter(runtime, "complete_workpiece")
        page = RealtimeControlPage(center)
        points = np.ones((10, 3))
        boxes = [{"name": "old workpiece"}]
        frames.put({"points": points, "boxes": boxes})
        center.poll_once()
        page.apply_state(center.build_ui_state())
        center.poll_once()
        self.assertIs(points, center.build_ui_state().points)
        self.assertIs(boxes, center.build_ui_state().boxes)
        frames.put({"boxes": None})
        center.poll_once()
        page.apply_state(center.build_ui_state())
        self.assertIs(points, center.build_ui_state().points)
        self.assertIsNone(page.point_cloud_view.boxes_data)

    def test_completed_stop_clears_displayed_scene(self):
        from control.ControlCenter import ControlCenter
        from view.qt.pages import RealtimeControlPage
        runtime = SimpleNamespace(poll=lambda: {"updated": False}, start_pipeline=lambda: None, stop_pipeline=lambda: [])
        center = ControlCenter(runtime, "complete_workpiece")
        runtime.poll = lambda: {"points": np.ones((10, 3)), "boxes": ["old"]}
        center.start()
        center.poll_once()
        page = RealtimeControlPage(center)
        page.apply_state(center.build_ui_state())
        center.stop()
        page.apply_state(center.build_ui_state())
        self.assertEqual(0, len(page.point_cloud_view.points))
        self.assertIsNone(page.point_cloud_view.boxes_data)
