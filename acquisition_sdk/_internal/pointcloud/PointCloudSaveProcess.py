"""A sibling process owns normalization and file I/O, independent of PLC frame delivery."""

from functools import partial
import json
import multiprocessing
from multiprocessing import shared_memory
from pathlib import Path
import queue
import re
import time

import numpy as np

from acquisition_sdk._internal.pointcloud.PointCloudSaveBuffer import block_view
from model.utils.ProcessHeartbeat import ProcessHeartbeat
from model.utils.WorkpieceOriginUtil import transform_points_for_origin


def make_preview(points, voxel_size_mm: float = 0.0):
    if voxel_size_mm <= 0 or not len(points):
        return points
    cells = np.floor(points / voxel_size_mm)
    _, indices = np.unique(cells, axis=0, return_index=True)
    return points[np.sort(indices)]


def _normalized_chunks(memory, descriptor, blocks, threshold, heartbeat):
    offset = 0.0
    previous_z = None
    for block in blocks:
        view = block_view(memory, descriptor, block)
        for start in range(0, len(view), 32768):
            heartbeat.touch()
            data = view[start:start + 32768].copy()
            z = data[:, 2].copy()
            preceding = np.empty_like(z)
            preceding[0] = z[0] if previous_z is None else previous_z
            preceding[1:] = z[:-1]
            resets = (z < preceding) & (preceding >= threshold * .9)
            # Match the legacy per-point offset accumulation, including block boundaries.
            reset_indices = np.flatnonzero(resets)
            offsets = np.full(len(z), offset)
            for position, index in enumerate(reset_indices):
                offset += threshold
                end = reset_indices[position + 1] if position + 1 < len(reset_indices) else len(z)
                offsets[index:end] = offset
            data[:, 2] = z + offsets
            offset = float(offsets[-1])
            previous_z = float(z[-1])
            yield data


def _absolute_chunks(points, heartbeat):
    for start in range(0, len(points), 32768):
        heartbeat.touch()
        yield points[start:start + 32768].copy()


def _prepare_channel(memory, descriptor, blocks, threshold, normalization, heartbeat):
    if normalization == "absolute_sorted":
        points = np.concatenate([block_view(memory, descriptor, block) for block in blocks])
        points = points[np.lexsort((points[:, 0], points[:, 1], points[:, 2]))]
        return partial(_absolute_chunks, points, heartbeat), 0.0, len(points)
    chunks = partial(_normalized_chunks, memory, descriptor, blocks, threshold, heartbeat)
    minimum, total = float("inf"), 0
    for data in chunks():
        minimum = float(np.minimum(minimum, np.min(data[:, 2])))
        total += len(data)
    return chunks, minimum, total


def save_job(job, pool_descriptor, output_dir, file_format="txt", heartbeat=None, preview_voxel_size_mm: float = 0.0):
    if file_format not in ("txt", "npy"):
        raise ValueError("point_cloud_save_format must be txt or npy")
    heartbeat = heartbeat or ProcessHeartbeat()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = job.get("filename_suffix", job["job_id"])
    for token in (suffix, job["job_id"], *job["channels"]):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ValueError("Invalid point cloud output name")
    threshold = float(job.get("z_reset_threshold", 160000))
    normalization = job.get("normalization", "absolute_sorted" if job.get("strategy") == "continuous_bidirectional" else "relative_z")
    if normalization not in ("relative_z", "absolute_sorted"):
        raise ValueError("Unknown point cloud normalization mode")
    preview_enabled = bool(job.get("preview_enabled", True))
    preview_parts = []
    files = []
    memory = shared_memory.SharedMemory(name=pool_descriptor["name"])
    try:
        for channel, blocks in job["channels"].items():
            if not blocks:
                continue
            chunks, minimum, total = _prepare_channel(memory, pool_descriptor, blocks, threshold, normalization, heartbeat)
            filename = output_dir / f"{channel}_{suffix}.{file_format}"
            partial = filename.with_name(filename.name + ".part")
            if filename.exists():
                raise FileExistsError(f"Refusing to overwrite point cloud: {filename}")
            if file_format == "txt":
                with partial.open("w", encoding="utf-8") as stream:
                    for data in chunks():
                        data[:, 2] -= minimum
                        np.savetxt(stream, data, fmt="%.1f")
                        if channel == "combined" and preview_enabled:
                            preview_parts.append(make_preview(data, preview_voxel_size_mm))
            else:
                mapped = np.lib.format.open_memmap(partial, mode="w+", dtype=np.float64, shape=(total, 3))
                try:
                    cursor = 0
                    for data in chunks():
                        data[:, 2] -= minimum
                        mapped[cursor:cursor + len(data)] = data
                        cursor += len(data)
                        if channel == "combined" and preview_enabled:
                            preview_parts.append(make_preview(data, preview_voxel_size_mm))
                    mapped.flush()
                finally:
                    # Windows must close the mapping before renaming the file.
                    del mapped
            partial.replace(filename)
            files.append({"name": filename.name, "points": total})
            heartbeat.touch()
        manifest = output_dir / f"{job['job_id']}.complete.json"
        partial_manifest = manifest.with_name(manifest.name + ".part")
        partial_manifest.write_text(json.dumps({"job_id": job["job_id"], "files": files, "incomplete": bool(job.get("incomplete", False))}, ensure_ascii=False), encoding="utf-8")
        partial_manifest.replace(manifest)
    finally:
        memory.close()
    if not preview_enabled:
        return None
    preview = np.concatenate(preview_parts) if preview_parts else np.empty((0, 3))
    if job.get("preview_origin_config"):
        preview = transform_points_for_origin(preview, job["preview_origin_config"])
    heartbeat.touch()
    return make_preview(preview, preview_voxel_size_mm)


class PointCloudSaveProcess(multiprocessing.Process):
    def __init__(self, task_queue, ack_queue, status_queue, pool_descriptor, output_dir, viz_queue=None, heartbeat=None, config=None):
        super().__init__(name="PointCloudSaveProcess", daemon=False)
        self.task_queue = task_queue
        self.ack_queue = ack_queue
        self.status_queue = status_queue
        self.pool_descriptor = pool_descriptor
        self.output_dir = str(output_dir)
        self.viz_queue = viz_queue
        self.heartbeat_value = heartbeat
        self.config = config or {}

    def run(self):
        from model.utils.LoggerUtil import logger, check_and_rotate_log
        from acquisition_sdk._internal.pointcloud.PointsFileUtil import manage_points_files

        heartbeat = ProcessHeartbeat(self.heartbeat_value, self.config.get("process_heartbeat_interval_s", 1))
        heartbeat.touch(force=True)
        if self.viz_queue is not None:
            # Preview delivery must never hold shutdown waiting for a stopped UI consumer.
            self.viz_queue.cancel_join_thread()
        current_job = None
        try:
            file_format = self.config.get("point_cloud_save_format", "txt")
            if file_format not in ("txt", "npy"):
                raise ValueError("point_cloud_save_format must be txt or npy")
            voxel_size = float(self.config.get("point_cloud_preview_voxel_mm", 10))
            if voxel_size < 0:
                raise ValueError("point_cloud_preview_voxel_mm must be nonnegative")
            self.status_queue.put({"type": "ready"})
            while True:
                heartbeat.touch()
                try:
                    current_job = self.task_queue.get(timeout=.2)
                except queue.Empty:
                    continue
                if current_job is None:
                    self.status_queue.put({"type": "drained"})
                    return
                started = time.perf_counter()
                preview = save_job(current_job, self.pool_descriptor, self.output_dir, file_format, heartbeat, voxel_size)
                blocks = [block for channel in current_job["channels"].values() for block in channel]
                self.ack_queue.put({"job_id": current_job["job_id"], "blocks": blocks})
                elapsed = time.perf_counter() - started
                logger.info(f"Point cloud job {current_job['job_id']} saved in {elapsed:.3f}s")
                self.status_queue.put({"type": "saved", "job_id": current_job["job_id"], "elapsed_s": elapsed})
                if self.viz_queue is not None and preview is not None:
                    try:
                        self.viz_queue.put_nowait({"points": preview, "boxes": None, "preview_processed": True})
                    except queue.Full:
                        logger.info("Preview queue busy; saved point cloud is unaffected")
                manage_points_files(directory=self.output_dir)
                check_and_rotate_log()
        except Exception as exc:
            job_id = current_job.get("job_id") if isinstance(current_job, dict) else None
            logger.exception(f"Point cloud saving failed, job={job_id}")
            self.status_queue.put({"type": "error", "job_id": job_id, "message": str(exc)})
