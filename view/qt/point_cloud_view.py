"""Qt OpenGL point-cloud view with the data API used by the controller."""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from view.qt.box_geometry import box_geometry
from view.qt.gl_buffers import PointBuffers


class QtPointCloudView(QOpenGLWidget):
    """Interactive preview that accepts the existing point and box payloads."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = np.empty((0, 3), dtype=np.float32)
        self.colors: np.ndarray | None = None
        self.boxes_data = None
        self.layer_visible: dict[str, bool] = dict.fromkeys(("points", "outside", "inside", "jig"), True)
        self._box_layers = {}
        self.box_vertices, self.box_colors = box_geometry(None)
        self.scene_center = np.zeros(3, dtype=np.float32)
        self.scene_radius = 1000.0
        self.rotation_x = 15.0
        self.rotation_y = 0.0
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._last_mouse: QPoint | None = None
        self._point_buffers = None
        self._buffer_context = None
        self._repaint_pending = False
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setSingleShot(True)
        self._repaint_timer.timeout.connect(self._flush_repaint)
        self.setMinimumHeight(360)

    def set_points(self, points: np.ndarray | None) -> None:
        if points is None or np.asarray(points).size == 0:
            self.clear()
            return
        values = np.asarray(points, dtype=np.float32)
        if values.ndim != 2 or values.shape[1] < 3:
            raise ValueError("points must be a 2D array with at least three columns")
        first_frame = not len(self.points)
        values = values[np.isfinite(values).all(axis=1)]
        self.points = np.ascontiguousarray(values[:, :3])
        self.colors = np.ascontiguousarray(self._resolve_colors(values))
        if first_frame:
            self.reset_camera()
        self._request_repaint()

    def set_boxes(self, boxes_data: object | None) -> None:
        self.boxes_data = boxes_data
        self._box_layers = {layer: box_geometry(boxes_data, {layer}) for layer in ("outside", "inside", "jig")}
        self._refresh_visible_boxes()
        self._request_repaint()

    def set_layer_visible(self, layer: str, visible: bool) -> None:
        if layer not in self.layer_visible:
            raise ValueError(f"Unknown scene layer: {layer}")
        self.layer_visible[layer] = bool(visible)
        if layer != "points":
            self._refresh_visible_boxes()
        self._request_repaint()

    def _refresh_visible_boxes(self) -> None:
        layers = [arrays for layer, arrays in self._box_layers.items() if self.layer_visible[layer] and len(arrays[0])]
        if layers:
            self.box_vertices = np.ascontiguousarray(np.vstack([arrays[0] for arrays in layers]))
            self.box_colors = np.ascontiguousarray(np.vstack([arrays[1] for arrays in layers]))
        else:
            self.box_vertices, self.box_colors = box_geometry(None)

    def clear(self) -> None:
        self.points = np.empty((0, 3), dtype=np.float32)
        self.colors = None
        self.boxes_data = None
        self._box_layers = {}
        self.box_vertices, self.box_colors = box_geometry(None)
        self.reset_camera()
        self._request_repaint()

    def reset_camera(self) -> None:
        if len(self.points):
            low, high = self.points.min(axis=0), self.points.max(axis=0)
            self.scene_center = (low + high) / 2
            self.scene_radius = max(float(np.linalg.norm(high - low)) * 0.6, 1.0)
        else:
            self.scene_center = np.zeros(3, dtype=np.float32)
            self.scene_radius = 1000.0
        self.rotation_x = 15.0
        self.rotation_y = 0.0
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._request_repaint()

    def camera_matrix(self) -> np.ndarray:
        pitch, yaw = np.radians([self.rotation_x, self.rotation_y])
        cp, sp, cy, sy = np.cos(pitch), np.sin(pitch), np.cos(yaw), np.sin(yaw)
        rotate_x = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
        rotate_y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        # Look from negative X: Y stays up, Z horizontal, positive X away from us.
        # The small initial pitch exposes the X-Z ground grid instead of its edge.
        # This is a camera rotation, leaving point/box and PLC coordinates intact.
        base = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]])
        matrix = np.eye(4, dtype=np.float32)
        matrix[:3, :3] = rotate_x @ rotate_y @ base
        matrix[:3, 3] = -(matrix[:3, :3] @ self.scene_center)
        matrix[0, 3] += self.pan_x * self.scene_radius
        matrix[1, 3] += self.pan_y * self.scene_radius
        return matrix

    def _projection_size(self) -> tuple[float, float]:
        aspect = max(self.width(), 1) / max(self.height(), 1)
        half_height = self.scene_radius / self.zoom / min(aspect, 1.0)
        return aspect, half_height

    def project_points(self, points: np.ndarray) -> np.ndarray:
        """Project world coordinates to logical widget pixels for picking."""
        matrix = self.camera_matrix()
        camera = np.asarray(points)[:, :3] @ matrix[:3, :3].T + matrix[:3, 3]
        aspect, half_height = self._projection_size()
        return np.column_stack(((camera[:, 0] / (half_height * aspect) + 1) * self.width() / 2, (1 - camera[:, 1] / half_height) * self.height() / 2))

    def pick_orbit_center(self, position, radius_px: float = 12.0) -> bool:
        if not self.layer_visible["points"] or not len(self.points):
            return False
        best_distance = radius_px ** 2
        best_depth = float("-inf")
        selected = None
        matrix = self.camera_matrix()
        target = np.array([position.x(), position.y()])
        # Bound temporary memory even for multi-million-point workpieces.
        for start in range(0, len(self.points), 65536):
            chunk = self.points[start:start + 65536]
            pixels = self.project_points(chunk)
            distance = np.sum((pixels - target) ** 2, axis=1)
            depths = chunk @ matrix[2, :3] + matrix[2, 3]
            candidates = np.flatnonzero((distance <= best_distance + 0.0001) & (distance <= radius_px ** 2) & (np.abs(depths) <= self.scene_radius * 20))
            if not len(candidates):
                continue
            minimum = float(distance[candidates].min())
            nearest = candidates[np.abs(distance[candidates] - minimum) < 0.0001]
            index = nearest[np.argmax(depths[nearest])]
            if minimum < best_distance - 0.0001 or float(depths[index]) > best_depth:
                selected = chunk[index].copy()
                best_distance = minimum
                best_depth = float(depths[index])
        if selected is None:
            return False
        offset = matrix[:3, :3] @ (selected - self.scene_center)
        self.pan_x += float(offset[0]) / self.scene_radius
        self.pan_y += float(offset[1]) / self.scene_radius
        self.scene_center = selected
        self._request_repaint()
        return True

    def grid_vertices(self) -> np.ndarray:
        cx, _, cz = self.scene_center
        floor = float(self.points[:, 1].min()) if len(self.points) else 0.0
        radius = self.scene_radius
        vertices = []
        for offset in np.linspace(-radius, radius, 21):
            vertices.extend(((cx + offset, floor, cz - radius), (cx + offset, floor, cz + radius), (cx - radius, floor, cz + offset), (cx + radius, floor, cz + offset)))
        return np.ascontiguousarray(vertices, dtype=np.float32)

    @staticmethod
    def _resolve_colors(values: np.ndarray) -> np.ndarray:
        if len(values) == 0:
            return np.empty((0, 3), dtype=np.float32)
        x = values[:, 0]
        span = float(x.max() - x.min()) if len(x) else 0.0
        normalized = (x - x.min()) / span if span else np.full_like(x, 0.5)
        # A display palette only: retain the file's XYZ/RGB in the source data.
        # X min -> vivid blue, middle -> cyan, X max -> mint green.
        # Keep a broad hue range so depth remains visible on the dark background.
        stops = np.array([[0.18, 0.40, 1.0], [0.12, 0.86, 1.0], [0.20, 0.95, 0.55]])
        return np.column_stack([np.interp(normalized, (0.0, 0.5, 1.0), stops[:, channel]) for channel in range(3)]).astype(np.float32)

    def _request_repaint(self) -> None:
        if not self._repaint_pending:
            self._repaint_pending = True
            self._repaint_timer.start(33)

    def _flush_repaint(self) -> None:
        self._repaint_pending = False
        self.update()

    def initializeGL(self) -> None:  # pragma: no cover - requires a desktop GL context
        from OpenGL import GL

        GL.glClearColor(0.027, 0.071, 0.125, 1.0)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glPointSize(2.0)
        self._point_buffers = PointBuffers(GL)
        context = self.context()
        if context is not None and context is not self._buffer_context:
            context.aboutToBeDestroyed.connect(self.release_gl_resources)
        self._buffer_context = context

    def release_gl_resources(self) -> None:
        buffers = self._point_buffers
        self._point_buffers = None
        self._repaint_timer.stop()
        self._repaint_pending = False
        if buffers is None:
            return
        context = self.context()
        if context is None or not context.isValid() or context is not self._buffer_context:
            buffers.abandon()
            return
        from PyQt6.QtGui import QOpenGLContext
        self.makeCurrent()
        try:
            if QOpenGLContext.currentContext() is context:
                buffers.release()
            else:
                buffers.abandon()
        finally:
            self.doneCurrent()

    def closeEvent(self, a0) -> None:
        event = a0
        if event is None:
            return
        self.release_gl_resources()
        super().closeEvent(event)

    def paintGL(self) -> None:  # pragma: no cover - requires a desktop GL context
        from OpenGL import GL

        GL.glClear(int(GL.GL_COLOR_BUFFER_BIT) | int(GL.GL_DEPTH_BUFFER_BIT))
        GL.glEnable(GL.GL_DEPTH_TEST)
        pixel_ratio = self.devicePixelRatioF()
        GL.glViewport(0, 0, int(self.width() * pixel_ratio), int(self.height() * pixel_ratio))
        aspect, half_height = self._projection_size()
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        depth = self.scene_radius * 20
        GL.glOrtho(-half_height * aspect, half_height * aspect, -half_height, half_height, -depth, depth)
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadMatrixf(np.ascontiguousarray(self.camera_matrix().T))
        GL.glEnableClientState(GL.GL_VERTEX_ARRAY)
        try:
            grid = self.grid_vertices()
            GL.glColor3f(0.07, 0.17, 0.25)
            GL.glVertexPointer(3, GL.GL_FLOAT, 0, grid)
            GL.glDrawArrays(GL.GL_LINES, 0, len(grid))
            if self.layer_visible["points"] and len(self.points) and self.colors is not None:
                GL.glEnableClientState(GL.GL_COLOR_ARRAY)
                try:
                    buffers = self._point_buffers
                    drawn = buffers is not None and buffers.upload(self.points, self.colors) and buffers.draw()
                    if not drawn:
                        GL.glVertexPointer(3, GL.GL_FLOAT, 0, self.points)
                        GL.glColorPointer(3, GL.GL_FLOAT, 0, self.colors)
                        GL.glDrawArrays(GL.GL_POINTS, 0, len(self.points))
                finally:
                    GL.glDisableClientState(GL.GL_COLOR_ARRAY)
            if len(self.box_vertices):
                GL.glEnableClientState(GL.GL_COLOR_ARRAY)
                try:
                    GL.glVertexPointer(3, GL.GL_FLOAT, 0, self.box_vertices)
                    GL.glColorPointer(3, GL.GL_FLOAT, 0, self.box_colors)
                    GL.glDrawArrays(GL.GL_LINES, 0, len(self.box_vertices))
                finally:
                    GL.glDisableClientState(GL.GL_COLOR_ARRAY)
        finally:
            GL.glDisableClientState(GL.GL_VERTEX_ARRAY)
        self._paint_coordinate_axes()

    def _paint_coordinate_axes(self) -> None:  # pragma: no cover - desktop drawing
        from PyQt6.QtCore import QPointF
        from PyQt6.QtGui import QColor, QPainter, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        origin = QPointF(58, self.height() - 55)
        rotation = self.camera_matrix()[:3, :3]
        for index, (label, color) in enumerate((("X", "#f56b70"), ("Y", "#2bd49d"), ("Z", "#24d5e6"))):
            direction = rotation[:, index]
            end = origin + QPointF(float(direction[0]) * 38, -float(direction[1]) * 38)
            painter.setPen(QPen(QColor(color), 2))
            if abs(float(direction[0])) + abs(float(direction[1])) < 0.05:
                painter.drawEllipse(origin, 4, 4)
                if direction[2] < 0:
                    painter.drawLine(origin + QPointF(-2, -2), origin + QPointF(2, 2))
                    painter.drawLine(origin + QPointF(-2, 2), origin + QPointF(2, -2))
                else:
                    painter.drawPoint(origin)
                painter.drawText(origin + QPointF(7, 14), label)
                continue
            painter.drawLine(origin, end)
            painter.drawText(end + QPointF(4, -3), label)
        if not len(self.points):
            painter.setPen(QColor("#7f9fbe"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "等待点云数据")
        painter.end()

    def mousePressEvent(self, a0) -> None:
        event = a0
        if event is None:
            return
        self._last_mouse = event.position().toPoint()

    def mouseDoubleClickEvent(self, a0) -> None:
        event = a0
        if event is None:
            return
        self._last_mouse = None
        if event.button() == Qt.MouseButton.LeftButton and self.pick_orbit_center(event.position()):
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, a0) -> None:
        self._last_mouse = None

    def mouseMoveEvent(self, a0) -> None:
        event = a0
        if event is None:
            return
        if self._last_mouse is None:
            return
        current = event.position().toPoint()
        delta = current - self._last_mouse
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.rotation_y += delta.x() * 0.5
            self.rotation_x = max(-90.0, min(90.0, self.rotation_x + delta.y() * 0.5))
        elif event.buttons() & Qt.MouseButton.RightButton:
            self.pan_x += delta.x() * 0.003 / self.zoom
            self.pan_y -= delta.y() * 0.003 / self.zoom
        self._last_mouse = current
        self._request_repaint()

    def wheelEvent(self, a0) -> None:
        event = a0
        if event is None:
            return
        factor = 1.0 + event.angleDelta().y() * 0.001
        self.zoom = max(0.1, min(10.0, self.zoom * factor))
        self._request_repaint()
