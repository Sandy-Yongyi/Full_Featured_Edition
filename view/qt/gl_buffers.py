"""Context-local point VBOs with a client-array fallback on GL failure."""

from ctypes import c_void_p


class PointBuffers:
    def __init__(self, gl):
        self.gl = gl
        self.vertex_buffer = 0
        self.color_buffer = 0
        self.count = 0
        self.disabled = False
        self._points = None
        self._colors = None

    def upload(self, points, colors) -> bool:
        if self.disabled or not len(points):
            return False
        if self._points is points and self._colors is colors:
            return True
        gl = self.gl
        try:
            if not self.vertex_buffer:
                self.vertex_buffer = int(gl.glGenBuffers(1))
            if not self.color_buffer:
                self.color_buffer = int(gl.glGenBuffers(1))
            if not self.vertex_buffer or not self.color_buffer:
                raise RuntimeError("OpenGL returned an invalid buffer handle")
            for handle, values in ((self.vertex_buffer, points), (self.color_buffer, colors)):
                gl.glBindBuffer(gl.GL_ARRAY_BUFFER, handle)
                gl.glBufferData(gl.GL_ARRAY_BUFFER, values.nbytes, values, gl.GL_DYNAMIC_DRAW)
            self._points, self._colors = points, colors
            self.count = len(points)
            return True
        except Exception:
            self.disabled = True
            self.release()
            return False
        finally:
            try:
                gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
            except Exception:
                pass

    def draw(self) -> bool:
        if self.disabled or not self.vertex_buffer or not self.color_buffer or not self.count:
            return False
        gl = self.gl
        try:
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vertex_buffer)
            gl.glVertexPointer(3, gl.GL_FLOAT, 0, c_void_p(0))
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.color_buffer)
            gl.glColorPointer(3, gl.GL_FLOAT, 0, c_void_p(0))
            gl.glDrawArrays(gl.GL_POINTS, 0, self.count)
            return True
        except Exception:
            self.disabled = True
            self.release()
            return False
        finally:
            try:
                gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
            except Exception:
                pass

    def abandon(self) -> None:
        """Forget handles after the owning GL context has already disappeared."""
        self.vertex_buffer = self.color_buffer = self.count = 0
        self._points = self._colors = None

    def release(self) -> None:
        """Call only with the owning GL context current."""
        handles = (self.vertex_buffer, self.color_buffer)
        self.abandon()
        for handle in handles:
            if handle:
                try:
                    self.gl.glDeleteBuffers(1, [handle])
                except Exception:
                    pass
