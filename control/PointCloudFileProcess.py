"""Developer-only TXT import into the existing Qt visualization queue."""

import multiprocessing
from pathlib import Path

import numpy as np

from model.utils.ProcessHeartbeat import ProcessHeartbeat
from model.utils.UiTelemetry import UiStatusPublisher
from model.utils.WorkpieceOriginUtil import transform_points_for_origin


def resolve_txt_files(data_path, data_name=None) -> tuple[str, ...]:
    if not data_path:
        raise ValueError("TXT 调试需要指定 --data-path 文件或目录")
    path = Path(data_path).expanduser().resolve()
    if path.is_file():
        files = [path] if path.suffix.casefold() == ".txt" else []
    elif path.is_dir():
        files = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.casefold() == ".txt")
        if data_name:
            name = Path(data_name).name.casefold()
            for prefix in ("combined_", "left_upper_", "right_upper_", "left_", "right_"):
                if name.startswith(prefix):
                    name = name[len(prefix):]
                    break
            if not name.endswith(".txt"):
                name += ".txt"
            names = {name} | {prefix + name for prefix in ("combined_", "left_", "right_", "left_upper_", "right_upper_")}
            files = [p for p in files if p.name.casefold() in names]
    else:
        raise FileNotFoundError(f"点云路径不存在：{path}")
    if not files:
        raise ValueError(f"未找到 TXT 点云文件：{path}")
    return tuple(str(p) for p in files)


def load_txt_cloud(files) -> np.ndarray:
    arrays = []
    for path in files:
        values = np.loadtxt(path, ndmin=2)
        if values.shape[1] < 3:
            raise ValueError(f"TXT 点云至少需要 XYZ 三列：{Path(path).name}")
        values = values[:, :6] if values.shape[1] >= 6 else values[:, :3]
        values = values[np.isfinite(values).all(axis=1)]
        if not len(values):
            raise ValueError(f"TXT 点云没有有效点：{Path(path).name}")
        arrays.append(values)
    if not arrays:
        raise ValueError("未提供点云文件")
    if any(values.shape[1] >= 6 for values in arrays):
        colored = []
        for values in arrays:
            if values.shape[1] >= 6:
                rgb = values[:, 3:6].copy()
                if rgb.max() > 1:
                    rgb /= 255.0
                rgb = np.clip(rgb, 0, 1)
            else:
                rgb = np.tile((0.14, 0.84, 0.9), (len(values), 1))
            colored.append(np.column_stack((values[:, :3], rgb)))
        arrays = colored
    return np.ascontiguousarray(np.vstack(arrays), dtype=np.float32)


def prepare_file_preview(points, read_data_config) -> np.ndarray:
    """Match live/replay preview coordinates while keeping loaded TXT data intact."""
    config = read_data_config or {}
    if int(config.get("translate_data_origin", 1) or 1) == 1:
        points = transform_points_for_origin(points, config)
    return np.ascontiguousarray(points, dtype=np.float32)


class PointCloudFileProcess(multiprocessing.Process):
    def __init__(self, files, viz_queue, status_queue, heartbeat, heartbeat_interval_s: float = 1.0, read_data_config=None):
        super().__init__(name="PointCloudFileProcess", daemon=True)
        self.files = files
        self.read_data_config = dict(read_data_config or {})
        self.viz_queue = viz_queue
        self.ui_status = UiStatusPublisher(status_queue, "files")
        self._heartbeat = ProcessHeartbeat(heartbeat, heartbeat_interval_s)

    def run(self):
        self.viz_queue.cancel_join_thread()
        self._heartbeat.touch(force=True)
        self.ui_status.publish(force=True, state="loading", detail="正在导入 TXT 点云")
        try:
            with self._heartbeat.keep_alive(max_duration_s=30):
                points = prepare_file_preview(load_txt_cloud(self.files), self.read_data_config)
            self.viz_queue.put({"points": points, "boxes": None, "preview_processed": True})
            self.ui_status.publish(force=True, state="loaded", detail=f"已导入 {len(self.files)} 个文件，{len(points):,} 点")
        except Exception as exc:
            self.ui_status.publish(force=True, state="error", detail=f"TXT 导入失败：{exc}")
        # Keep the imported scene available until the developer stops/reloads.
        # A completed one-shot load must not look like a crashed worker.
        while True:
            self._heartbeat.sleep(1)
