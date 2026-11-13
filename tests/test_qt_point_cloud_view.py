import os
import unittest
from unittest.mock import Mock, patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class QtPointCloudViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_default_and_reset_view_put_z_horizontal_y_vertical_and_x_reversed(self):
        from view.qt.point_cloud_view import QtPointCloudView
        view = QtPointCloudView()
        view.resize(800, 600)
        points = np.array([[10, 20, 30], [40, 50, 60]], dtype=np.float32)
        view.set_points(points)
        for reset in (False, True):
            if reset:
                view.rotation_x, view.rotation_y = 35, 60
                view.reset_camera()
            origin, x, y, z = view.project_points(np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10]]))
            self.assertAlmostEqual(x[0], origin[0], places=3)
            self.assertLess(x[1], origin[1])
            self.assertGreater(abs(z[0] - origin[0]), 0)
            self.assertAlmostEqual(z[1], origin[1], places=3)
            self.assertLess(y[1], origin[1])
            self.assertAlmostEqual(y[0], origin[0], places=3)
            self.assertLess((view.camera_matrix()[:3, :3] @ np.array([10, 0, 0]))[2], 0)
            self.assertAlmostEqual(np.linalg.det(view.camera_matrix()[:3, :3]), 1, places=5)
        np.testing.assert_array_equal(points, view.points)

    def test_reference_grid_uses_visible_xz_ground_plane(self):
        from view.qt.point_cloud_view import QtPointCloudView
        view = QtPointCloudView()
        view.set_points(np.array([[10, 20, 30], [40, 50, 60]], dtype=np.float32))
        vertices = view.grid_vertices()
        np.testing.assert_allclose(vertices[:, 1], 20)
        self.assertGreater(np.ptp(vertices[:, 0]), 0)
        self.assertGreater(np.ptp(vertices[:, 2]), 0)
        pixels = view.project_points(vertices)
        self.assertGreater(np.ptp(pixels[:, 0]), 0)
        self.assertGreater(np.ptp(pixels[:, 1]), 0)

    def test_display_uses_visible_cool_colors_even_when_txt_contains_warm_rgb(self):
        from view.qt.point_cloud_view import QtPointCloudView

        view = QtPointCloudView()
        view.set_points(np.array([[0, 0, 0, 255, 0, 0], [100, 20, 30, 255, 128, 0]], dtype=np.float32))

        self.assertEqual(view.points.shape, (2, 3))
        self.assertTrue(np.all(view.colors >= 0))
        self.assertTrue(np.all(view.colors <= 1))
        self.assertTrue(np.all(view.colors.max(axis=1) >= 0.8))
        self.assertTrue(np.all(view.colors[:, 0] < 0.35))

    def test_x_gradient_has_clear_depth_contrast_and_is_independent_of_yz(self):
        from view.qt.point_cloud_view import QtPointCloudView
        points = np.array([[-100, 0, 0], [-100, 1000, -1000], [0, 0, 0], [100, 0, 0]], dtype=np.float32)
        colors = QtPointCloudView._resolve_colors(points)
        np.testing.assert_allclose(colors[0], colors[1])
        self.assertGreater(np.linalg.norm(colors[-1] - colors[0]), 0.6)
        self.assertGreater(colors[0, 2], colors[0, 1])
        self.assertGreater(colors[-1, 1], colors[-1, 2])
        self.assertGreater(colors[2, 1], 0.8)
        constant = QtPointCloudView._resolve_colors(np.array([[20, 0, 0], [20, 100, 100]], dtype=np.float32))
        self.assertTrue(np.isfinite(constant).all())
        np.testing.assert_allclose(constant[0], constant[1])

    def test_clear_removes_scene_arrays(self):
        from view.qt.point_cloud_view import QtPointCloudView

        view = QtPointCloudView()
        view.set_points(np.array([[1, 2, 3]], dtype=np.float32))
        view.clear()

        self.assertEqual(view.points.shape, (0, 3))
        self.assertIsNone(view.colors)

    def test_block_data_boxes_generate_all_three_region_types(self):
        from acquisition_sdk._internal.formats.complete_workpiece.BlockDataFormat import BlockData, OutsideData, InsideData, SubInsideData, JigData
        from view.qt.point_cloud_view import QtPointCloudView
        block = BlockData(
            outside_data=[OutsideData(0, 10, 0, 20, 0, 30)],
            inside_data=[InsideData(1, [SubInsideData(1, 1, 9, 2, 18, 3, 27)])],
            jig_data=[JigData(1, 5, 6, 7, 8)],
        )
        view = QtPointCloudView()
        view.set_boxes(block)
        self.assertEqual((72, 3), view.box_vertices.shape)
        self.assertEqual(view.box_vertices.shape, view.box_colors.shape)
        self.assertTrue(np.isfinite(view.box_vertices).all())
        view.set_boxes(None)
        self.assertEqual((0, 3), view.box_vertices.shape)

    def test_dictionary_box_format_remains_supported(self):
        from view.qt.point_cloud_view import QtPointCloudView
        view = QtPointCloudView()
        view.set_boxes({"outside_data": {"x_min": 0, "x_max": 10, "y_min": 0, "y_max": 20, "z_min": 0, "z_max": 30}})
        self.assertEqual((24, 3), view.box_vertices.shape)

    def test_new_frame_preserves_user_camera_and_fit_contains_large_coordinates(self):
        from view.qt.point_cloud_view import QtPointCloudView
        view = QtPointCloudView()
        points = np.array([[12000, 20000, 30000], [14000, 22000, 34000]], dtype=np.float32)
        view.set_points(points)
        transformed = np.column_stack((points, np.ones(2))) @ view.camera_matrix().T
        self.assertTrue(np.all(np.abs(transformed[:, :3]) < view.scene_radius * 1.1))
        view.rotation_x = 20
        view.zoom = 2.5
        view.pan_x = 0.3
        view.set_points(points + 1)
        self.assertEqual(20, view.rotation_x)
        self.assertEqual(2.5, view.zoom)
        self.assertEqual(0.3, view.pan_x)

    def test_empty_scene_has_grid_and_fit_view_requests_repaint(self):
        from view.qt.point_cloud_view import QtPointCloudView
        view = QtPointCloudView()
        self.assertGreater(len(view.grid_vertices()), 0)
        self.assertTrue(np.isfinite(view.camera_matrix()).all())
        view.reset_camera()
        self.assertTrue(view._repaint_timer.isActive())

    def test_pick_changes_rotation_center_without_moving_projected_cloud(self):
        from PyQt6.QtCore import QPointF
        from view.qt.point_cloud_view import QtPointCloudView
        view = QtPointCloudView()
        view.resize(800, 600)
        view.set_points(np.array([[0, 0, -100], [0, 0, 100]], dtype=np.float32))
        before = view.project_points(view.points)
        self.assertTrue(view.pick_orbit_center(QPointF(*map(float, before[1]))))
        np.testing.assert_allclose(view.scene_center, view.points[1])
        np.testing.assert_allclose(view.project_points(view.points), before, atol=0.001)
        view.reset_camera()
        np.testing.assert_allclose(view.scene_center, [0, 0, 0])

    def test_pick_ignores_empty_space_and_hidden_cloud(self):
        from PyQt6.QtCore import QPointF
        from view.qt.point_cloud_view import QtPointCloudView
        view = QtPointCloudView()
        view.resize(800, 600)
        view.set_points(np.array([[0, 0, 0]], dtype=np.float32))
        self.assertFalse(view.pick_orbit_center(QPointF(0, 0)))
        view.set_layer_visible("points", False)
        self.assertFalse(view.pick_orbit_center(QPointF(400, 300)))

    def test_pick_selects_front_point_when_projected_positions_overlap(self):
        from PyQt6.QtCore import QPointF
        from view.qt.point_cloud_view import QtPointCloudView
        view = QtPointCloudView()
        view.resize(800, 600)
        view.set_points(np.array([[-10, 0, 0], [10, 0, 0]], dtype=np.float32))
        view.rotation_x = view.rotation_y = 0
        self.assertTrue(view.pick_orbit_center(QPointF(400, 300)))
        np.testing.assert_allclose(view.scene_center, [-10, 0, 0])

    def test_double_click_can_pick_point_after_first_processing_chunk(self):
        from types import SimpleNamespace
        from PyQt6.QtCore import QPointF, Qt
        from view.qt.point_cloud_view import QtPointCloudView
        view = QtPointCloudView()
        view.resize(800, 600)
        points = np.zeros((65537, 3), dtype=np.float32)
        points[-1] = [0, 0, 100]
        view.set_points(points)
        position = QPointF(*map(float, view.project_points(points[-1:])[0]))
        accepted = []
        event = SimpleNamespace(button=lambda: Qt.MouseButton.LeftButton, position=lambda: position,
                                accept=lambda: accepted.append(True), ignore=lambda: accepted.append(False))
        view.mouseDoubleClickEvent(event)
        self.assertEqual([True], accepted)
        np.testing.assert_allclose(view.scene_center, points[-1])

    def test_paint_submits_grid_and_points_with_camera_projection(self):
        from view.qt.point_cloud_view import QtPointCloudView
        from OpenGL import GL
        view = QtPointCloudView()
        view.set_points(np.array([[100, 200, 300], [400, 500, 600]], dtype=np.float32))
        fake_gl = Mock()
        for name in ("GL_COLOR_BUFFER_BIT", "GL_DEPTH_BUFFER_BIT", "GL_DEPTH_TEST", "GL_PROJECTION",
                     "GL_MODELVIEW", "GL_VERTEX_ARRAY", "GL_COLOR_ARRAY", "GL_FLOAT", "GL_LINES", "GL_POINTS"):
            setattr(fake_gl, name, getattr(GL, name))
        with patch("OpenGL.GL", fake_gl), patch.object(view, "_paint_coordinate_axes"):
            view.paintGL()
        fake_gl.glOrtho.assert_called_once()
        np.testing.assert_allclose(fake_gl.glLoadMatrixf.call_args.args[0], view.camera_matrix().T)
        fake_gl.glDrawArrays.assert_any_call(GL.GL_LINES, 0, len(view.grid_vertices()))
        fake_gl.glDrawArrays.assert_any_call(GL.GL_POINTS, 0, 2)
        view.set_layer_visible("points", False)
        fake_gl.reset_mock()
        with patch("OpenGL.GL", fake_gl), patch.object(view, "_paint_coordinate_axes"):
            view.paintGL()
        self.assertFalse(any(call.args[0] == GL.GL_POINTS for call in fake_gl.glDrawArrays.call_args_list))
        fake_gl.glDrawArrays.assert_any_call(GL.GL_LINES, 0, len(view.grid_vertices()))
