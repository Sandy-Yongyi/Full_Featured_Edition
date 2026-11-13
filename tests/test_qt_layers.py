import os
import unittest
from types import SimpleNamespace

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class LayerTests(unittest.TestCase):
    def test_region_controls_only_show_for_complete_workpiece_strategy(self):
        from model.telemetry.UiState import UiState
        from view.qt.pages import RealtimeControlPage
        page = RealtimeControlPage(SimpleNamespace(strategy_name="frame_by_frame"))
        self.assertFalse(page.layer_controls["points"].isHidden())
        self.assertTrue(all(page.layer_controls[key].isHidden() for key in ("outside", "inside", "jig")))
        for strategy in ("complete_workpiece", "frame_by_frame", "continuous_bidirectional", "complete_workpiece"):
            page.apply_state(UiState.empty(strategy))
            for key in ("outside", "inside", "jig"):
                self.assertEqual(strategy != "complete_workpiece", page.layer_controls[key].isHidden())

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def block(self):
        from acquisition_sdk._internal.formats.complete_workpiece.BlockDataFormat import BlockData, OutsideData, InsideData, SubInsideData, JigData
        return BlockData(outside_data=[OutsideData(0, 10, 0, 20, 0, 30)],
                         inside_data=[InsideData(1, [SubInsideData(1, 1, 9, 2, 18, 3, 27)])],
                         jig_data=[JigData(1, 5, 6, 7, 8)])

    def test_region_colors_are_green_red_and_bright_yellow(self):
        from view.qt.box_geometry import box_geometry
        for layer, color in (("outside", (0, 1, 0)), ("inside", (1, 0, 0)), ("jig", (1, 1, 0))):
            with self.subTest(layer=layer):
                vertices, colors = box_geometry(self.block(), {layer})
                self.assertEqual(24, len(vertices))
                np.testing.assert_allclose(colors, np.tile(color, (24, 1)))

    def test_region_toggles_filter_geometry_without_discarding_source(self):
        from view.qt.point_cloud_view import QtPointCloudView
        view = QtPointCloudView()
        block = self.block()
        view.set_boxes(block)
        view.set_layer_visible("jig", False)
        self.assertEqual(48, len(view.box_vertices))
        view.set_layer_visible("inside", False)
        self.assertEqual(24, len(view.box_vertices))
        view.set_layer_visible("outside", False)
        self.assertEqual(0, len(view.box_vertices))
        self.assertIs(block, view.boxes_data)
        view.set_layer_visible("inside", True)
        self.assertEqual(24, len(view.box_vertices))

    def test_layer_choice_survives_new_frame_and_page_shows_point_count(self):
        from model.telemetry.UiState import UiState
        from view.qt.pages import RealtimeControlPage
        page = RealtimeControlPage(SimpleNamespace())
        points = np.ones((123, 3))
        page.apply_state(UiState(strategy_name="complete_workpiece", points=points, boxes=self.block()))
        self.assertIn("123", page.point_count.text())
        page.layer_controls["points"].setChecked(False)
        page.layer_controls["outside"].setChecked(False)
        page.apply_state(UiState(strategy_name="complete_workpiece", points=points + 1, boxes=self.block()))
        self.assertFalse(page.point_cloud_view.layer_visible["points"])
        self.assertEqual(48, len(page.point_cloud_view.box_vertices))
        self.assertEqual(123, len(page.point_cloud_view.points))
        from PyQt6.QtWidgets import QCheckBox
        self.assertEqual({"点云", "外框", "内框", "挂具"}, {box.text() for box in page.findChildren(QCheckBox)})
