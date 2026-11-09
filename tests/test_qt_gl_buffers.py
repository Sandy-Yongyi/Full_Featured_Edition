import unittest
from unittest.mock import Mock

import numpy as np


class PointBufferTests(unittest.TestCase):
    def make_gl(self):
        gl = Mock()
        gl.GL_ARRAY_BUFFER = 1
        gl.GL_DYNAMIC_DRAW = 2
        gl.GL_FLOAT = 3
        gl.GL_POINTS = 4
        gl.glGenBuffers.side_effect = [31, 32]
        return gl

    def test_upload_reuses_buffers_and_release_is_idempotent(self):
        from view.qt.gl_buffers import PointBuffers
        gl = self.make_gl()
        buffers = PointBuffers(gl)
        points = np.ones((3, 3), dtype=np.float32)
        colors = np.zeros((3, 3), dtype=np.float32)
        self.assertTrue(buffers.upload(points, colors))
        self.assertTrue(buffers.upload(points, colors))
        self.assertEqual(2, gl.glBufferData.call_count)
        self.assertTrue(buffers.draw())
        gl.glDrawArrays.assert_called_once_with(gl.GL_POINTS, 0, 3)
        buffers.release()
        buffers.release()
        self.assertEqual(2, gl.glDeleteBuffers.call_count)
        self.assertFalse(buffers.draw())

    def test_partial_upload_failure_releases_both_buffers_and_enables_fallback(self):
        from view.qt.gl_buffers import PointBuffers
        gl = self.make_gl()
        gl.glBufferData.side_effect = [None, RuntimeError("GPU allocation failed")]
        buffers = PointBuffers(gl)
        points = np.ones((3, 3), dtype=np.float32)
        self.assertFalse(buffers.upload(points, points.copy()))
        self.assertEqual(2, gl.glDeleteBuffers.call_count)
        self.assertFalse(buffers.draw())
        self.assertFalse(buffers.upload(points, points.copy()))
        self.assertEqual(2, gl.glGenBuffers.call_count)

    def test_draw_failure_releases_buffers_and_unbinds_them(self):
        from view.qt.gl_buffers import PointBuffers
        gl = self.make_gl()
        buffers = PointBuffers(gl)
        points = np.ones((3, 3), dtype=np.float32)
        self.assertTrue(buffers.upload(points, points.copy()))
        gl.glDrawArrays.side_effect = RuntimeError("driver draw failure")
        self.assertFalse(buffers.draw())
        self.assertEqual(2, gl.glDeleteBuffers.call_count)
        gl.glBindBuffer.assert_called_with(gl.GL_ARRAY_BUFFER, 0)


class ViewResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_cleanup_makes_own_context_current_before_deleting_buffers(self):
        from unittest.mock import patch
        from view.qt.point_cloud_view import QtPointCloudView
        view = QtPointCloudView()
        context = Mock()
        context.isValid.return_value = True
        buffers = Mock()
        view._point_buffers = buffers
        view._buffer_context = context
        with patch.object(view, "context", return_value=context), \
                patch.object(view, "makeCurrent") as current, patch.object(view, "doneCurrent") as done, \
                patch("PyQt6.QtGui.QOpenGLContext.currentContext", return_value=context):
            view.release_gl_resources()
            view.release_gl_resources()
        current.assert_called_once()
        buffers.release.assert_called_once()
        done.assert_called_once()

    def test_cleanup_without_context_does_not_call_opengl_delete(self):
        from unittest.mock import patch
        from view.qt.point_cloud_view import QtPointCloudView
        view = QtPointCloudView()
        buffers = Mock()
        view._point_buffers = buffers
        with patch.object(view, "context", return_value=None):
            view.release_gl_resources()
        buffers.abandon.assert_called_once()
        buffers.release.assert_not_called()
