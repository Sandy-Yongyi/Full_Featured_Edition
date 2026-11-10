"""Queue polling shared by the legacy and PyQt control surfaces."""

from __future__ import annotations

import queue
from datetime import datetime
from typing import Any
from model.telemetry.UiState import LogEvent


class RuntimeStateCollector:
    """Convert worker queues into a UI-neutral snapshot.

    This object deliberately does not import wx or PyQt.  A view can decide
    when and how to render the returned points, boxes, and log messages.
    """

    def __init__(self, log_queue: Any, point_filter: Any, preview_voxel_mm: float = 10):
        self._log_queue = log_queue
        self._point_filter = point_filter
        self._preview_voxel_mm = float(preview_voxel_mm)
        self._visualization_queue: Any | None = None

    def set_visualization_queue(self, visualization_queue: Any | None) -> None:
        self._visualization_queue = visualization_queue

    def poll(self) -> dict[str, Any]:
        snapshot = self.poll_visualization()
        snapshot["logs"] = [
            LogEvent("ERROR" if source == "stderr" else "INFO", str(output), source, datetime.now())
            for source, output in self._drain_log_records()
        ]
        return snapshot

    def poll_logs(self) -> list[str]:
        return [f"[stderr] {output}" if source == "stderr" else str(output)
                for source, output in self._drain_log_records()]

    def poll_visualization(self) -> dict[str, Any]:
        snapshot: dict[str, Any] = {"points": None, "boxes": None, "updated": False, "points_updated": False}
        if self._visualization_queue is None:
            return snapshot
        preview_processed = False
        # Bound queue work per UI tick, even when producers keep publishing.
        # Coalesce first: superseded clouds must not consume voxel-filter time.
        for _ in range(8):
            try:
                data = self._visualization_queue.get_nowait()
            except queue.Empty:
                break
            snapshot["updated"] = True
            if "points" in data:
                snapshot["points_updated"] = True
                snapshot["points"] = data["points"]
                preview_processed = data.get("preview_processed", False)
            snapshot["boxes"] = data.get("boxes")
        points = snapshot["points"]
        if points is not None and not preview_processed and self._preview_voxel_mm > 0:
            snapshot["points"] = self._point_filter.voxelReductionFilter(points, voxel_size=self._preview_voxel_mm)
        return snapshot

    def _drain_log_records(self, limit: int = 20) -> list[tuple[str, str]]:
        messages: list[tuple[str, str]] = []
        while len(messages) < limit:
            try:
                source, output = self._log_queue.get_nowait()
            except queue.Empty:
                break
            messages.append((str(source), str(output)))
        return messages
