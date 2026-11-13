import os
import queue
import unittest
from types import SimpleNamespace

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ModeOrientationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_all_modes_share_preview_origin_and_default_negative_x_view(self):
        from control.DataProcessWorker import DataProcessWorker
        from control.DataProcessingProcess import DataProcessingProcess
        from acquisition_sdk._internal.pointcloud.PointCloudFileProcess import prepare_file_preview
        from model.telemetry.UiState import UiState
        from acquisition_sdk._internal.formats.complete_workpiece.BlockDataFormat import BlockData
        from view.qt.pages import RealtimeControlPage
        points = np.array([[100, 10, 0], [200, 20, 100]], dtype=np.float32)
        for origin, same, expected_x in (("right", 1, [900, 800]), ("left", 1, [100, 200]),
                                         ("right", 2, [100, 200])):
            with self.subTest(origin=origin, same_origin=same):
                config = {"translate_data_origin": same, "workpiece_origin_side": origin,
                          "workpiece_origin_reference_x": 1000}
                first = queue.Queue()
                replay = SimpleNamespace(read_data_config=config, viz_queue=first,
                                         _uses_same_origin=lambda: same == 1)
                DataProcessWorker._push_visualization_data(replay, points)
                second = queue.Queue()
                processing = SimpleNamespace(draw_type=2, read_data_config=config, viz_queue=second)
                DataProcessingProcess._push_visualization_data(processing, points, BlockData())
                scenes = (first.get_nowait()["points"], second.get_nowait()["points"],
                          prepare_file_preview(points, config))
                projections = []
                for mode, scene in enumerate(scenes, 1):
                    page = RealtimeControlPage(SimpleNamespace(control_type=mode))
                    view = page.point_cloud_view
                    view.resize(800, 600)
                    page.apply_state(UiState(strategy_name="complete_workpiece", points=scene))
                    np.testing.assert_allclose(view.points[:, 0], expected_x)
                    self.assertLess(view.camera_matrix()[2, 0], 0)
                    original_camera = view.camera_matrix().copy()
                    view.rotation_x, view.rotation_y = 30, 80
                    view.reset_camera()
                    np.testing.assert_allclose(view.camera_matrix(), original_camera)
                    projections.append(view.project_points(view.points))
                np.testing.assert_allclose(projections[0], projections[1])
                np.testing.assert_allclose(projections[0], projections[2])
        np.testing.assert_array_equal(points[:, 0], [100, 200])

    def test_file_preview_converts_only_display_copy_and_keeps_rgb(self):
        from acquisition_sdk._internal.pointcloud.PointCloudFileProcess import prepare_file_preview
        points = np.array([[100, 10, 20, 0.1, 0.2, 0.3]], dtype=np.float32)
        config = {"translate_data_origin": 1, "workpiece_origin_side": "right", "workpiece_origin_reference_x": 1000}
        preview = prepare_file_preview(points, config)
        self.assertEqual(900, preview[0, 0])
        np.testing.assert_allclose(preview[:, 1:], points[:, 1:])
        self.assertEqual(100, points[0, 0])
