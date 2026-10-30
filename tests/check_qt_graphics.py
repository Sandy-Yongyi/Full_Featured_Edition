"""Opt-in Windows driver checks, excluded from normal offscreen discovery.

Run in a fresh process: python -m unittest tests.check_qt_graphics -v
No production controller, visible widget, device, or output file is created.
"""

import os
import sys
import time
import unittest

import numpy as np


@unittest.skipUnless(sys.platform == "win32", "Windows OpenGL driver check")
class RealGraphicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "windows")
        from PyQt6.QtGui import QGuiApplication, QOpenGLContext, QOffscreenSurface
        from OpenGL import GL
        cls.app = QGuiApplication.instance() or QGuiApplication(["qt-graphics-check"])
        cls.context = QOpenGLContext()
        if not cls.context.create():
            raise RuntimeError("Cannot create an OpenGL context")
        cls.surface = QOffscreenSurface()
        cls.surface.setFormat(cls.context.format())
        cls.surface.create()
        if not cls.surface.isValid() or not cls.context.makeCurrent(cls.surface):
            cls.surface.destroy()
            raise RuntimeError("Cannot make the offscreen OpenGL context current")
        cls.gl = GL
        print("\nGL version:", GL.glGetString(GL.GL_VERSION).decode())
        print("GL renderer:", GL.glGetString(GL.GL_RENDERER).decode())

    @classmethod
    def tearDownClass(cls):
        cls.context.doneCurrent()
        cls.surface.destroy()

    def setUp(self):
        from PyQt6.QtOpenGL import QOpenGLFramebufferObject
        from view.qt.gl_buffers import PointBuffers
        gl = self.gl
        self.fbo = QOpenGLFramebufferObject(64, 64)
        self.assertTrue(self.fbo.isValid() and self.fbo.bind())
        self.addCleanup(self._release_framebuffer)
        self.buffers = PointBuffers(gl)
        self.addCleanup(self.buffers.release)
        gl.glViewport(0, 0, 64, 64)
        gl.glClearColor(0, 0, 0, 1)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()
        gl.glPointSize(7)
        gl.glEnableClientState(gl.GL_VERTEX_ARRAY)
        gl.glEnableClientState(gl.GL_COLOR_ARRAY)

    def _release_framebuffer(self):
        gl = self.gl
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glDisableClientState(gl.GL_COLOR_ARRAY)
        gl.glDisableClientState(gl.GL_VERTEX_ARRAY)
        self.fbo.release()
        # Destroy GL objects while the owning context is still current.
        self.fbo = None

    def pixel(self, x=32, y=32):
        gl = self.gl
        return tuple(np.frombuffer(gl.glReadPixels(x, y, 1, 1, gl.GL_RGB, gl.GL_UNSIGNED_BYTE),
                                   dtype=np.uint8).tolist())

    def test_vbo_renders_reuses_updates_and_releases_real_handles(self):
        gl = self.gl
        points = np.array([[0, 0, 0]], dtype=np.float32)
        red = np.array([[1, 0, 0]], dtype=np.float32)
        self.assertTrue(self.buffers.upload(points, red))
        handles = (self.buffers.vertex_buffer, self.buffers.color_buffer)
        self.assertTrue(self.buffers.draw())
        self.assertEqual((255, 0, 0), self.pixel())
        self.assertTrue(self.buffers.upload(points, red))
        self.assertEqual(handles, (self.buffers.vertex_buffer, self.buffers.color_buffer))

        moved = np.array([[0.5, 0, 0]], dtype=np.float32)
        blue = np.array([[0, 0, 1]], dtype=np.float32)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        self.assertTrue(self.buffers.upload(moved, blue))
        self.assertTrue(self.buffers.draw())
        self.assertEqual((0, 0, 255), self.pixel(48, 32))
        self.assertEqual((0, 0, 0), self.pixel())
        self.buffers.release()
        self.buffers.release()
        self.assertTrue(all(not gl.glIsBuffer(handle) for handle in handles))
        self.assertEqual(gl.GL_NO_ERROR, gl.glGetError())

    def test_client_array_fallback_renders_without_vbos(self):
        gl = self.gl
        points = np.array([[0, 0, 0]], dtype=np.float32)
        colors = np.array([[0, 1, 0]], dtype=np.float32)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glVertexPointer(3, gl.GL_FLOAT, 0, points)
        gl.glColorPointer(3, gl.GL_FLOAT, 0, colors)
        gl.glDrawArrays(gl.GL_POINTS, 0, 1)
        self.assertEqual((0, 255, 0), self.pixel())
        self.assertEqual(gl.GL_NO_ERROR, gl.glGetError())

    def test_bulk_cloud_upload_and_draw_complete_without_gl_errors(self):
        gl = self.gl
        points = np.random.default_rng(0).uniform(-0.9, 0.9, (200_000, 3)).astype(np.float32)
        colors = np.empty_like(points)
        colors[:] = (0, 1, 1)
        started = time.perf_counter()
        self.assertTrue(self.buffers.upload(points, colors))
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.buffers.vertex_buffer)
        self.assertEqual(2_400_000, int(gl.glGetBufferParameteriv(gl.GL_ARRAY_BUFFER, gl.GL_BUFFER_SIZE)))
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        self.assertTrue(self.buffers.draw())
        gl.glFinish()
        elapsed = time.perf_counter() - started
        print(f"200,000 synthetic points upload + draw + finish: {elapsed * 1000:.3f} ms")
        self.assertEqual(gl.GL_NO_ERROR, gl.glGetError())


if __name__ == "__main__":
    unittest.main()
