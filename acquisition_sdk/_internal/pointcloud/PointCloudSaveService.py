"""Parent-owned saving resources and a bounded, drain-first shutdown."""

import multiprocessing
import queue
import time

from acquisition_sdk._internal.pointcloud.PointCloudSaveProcess import PointCloudSaveProcess
from acquisition_sdk._internal.pointcloud.PointCloudSaveBuffer import SharedPointCloudPool
from model.utils.TomlLoader import TomlLoader


class PointCloudSaveService:
    @classmethod
    def from_config_file(cls, config_path, output_dir, viz_queue=None):
        """Use the existing project loader for every production service startup."""
        config = TomlLoader.load(str(config_path))
        return cls(config, output_dir, viz_queue)

    def __init__(self, config, output_dir, viz_queue=None):
        self.config = dict(config)
        block_bytes = int(float(config.get("point_cloud_save_block_mb", 16)) * 1024 * 1024)
        block_count = int(config.get("point_cloud_save_block_count", 32))
        self.pool = SharedPointCloudPool.create(block_bytes, block_count)
        self.task_queue = multiprocessing.Queue(maxsize=block_count + 1)
        self.ack_queue = multiprocessing.Queue()
        self.status_queue = multiprocessing.Queue()
        self.stop_event = multiprocessing.Event()
        self.heartbeat = multiprocessing.Value('d', time.monotonic(), lock=False)
        self.worker = PointCloudSaveProcess(self.task_queue, self.ack_queue, self.status_queue, self.pool.descriptor, output_dir, viz_queue, self.heartbeat, self.config)
        self._closed = False
        self._errors = []
        self._drained = False

    def start(self, timeout_s: int = 10):
        self.worker.start()
        try:
            status = self.status_queue.get(timeout=timeout_s)
        except queue.Empty as exc:
            raise RuntimeError("Point cloud save process did not become ready") from exc
        if status["type"] != "ready":
            raise RuntimeError(status.get("message", "Point cloud save process startup failed"))

    def poll_status(self):
        messages = []
        while True:
            try:
                message = self.status_queue.get_nowait()
            except queue.Empty:
                break
            messages.append(message)
            if message.get("type") == "error":
                self._errors.append(message.get("message", "Point cloud saving failed"))
            elif message.get("type") == "drained":
                self._drained = True
        return messages

    def _discard_acks_after_producer_exit(self):
        # Once production has ended nobody needs to reuse blocks. Drain the pipe so
        # the writer's queue feeder can exit; do not steal ACKs from a live producer.
        while True:
            try:
                self.ack_queue.get_nowait()
            except queue.Empty:
                return

    def drain_and_close(self, timeout_s: int = 120):
        """Call ONLY after the producer has exited and flushed its task queue."""
        deadline = time.monotonic() + timeout_s
        self.poll_status()
        if self.worker.pid is not None and self.worker.is_alive():
            try:
                self.task_queue.put(None, timeout=min(1, timeout_s))
            except queue.Full:
                self._errors.append("Point cloud save queue full during shutdown; tasks may be incomplete")
            while self.worker.is_alive() and time.monotonic() < deadline:
                self._discard_acks_after_producer_exit()
                self.poll_status()
                self.worker.join(timeout=.05)
            if self.worker.is_alive():
                self._errors.append("Point cloud saving shutdown timed out; pending files may be incomplete")
        self.poll_status()
        if not self._drained and not self._errors:
            self._errors.append("保存进程未确认排空，待保存点云可能不完整")
        errors = list(self._errors)
        self.abort()
        return errors

    def abort(self):
        if self._closed:
            return
        if self.worker.pid is not None:
            if self.worker.is_alive():
                self.worker.terminate()
                self.worker.join(timeout=2)
            if self.worker.is_alive():
                self.worker.kill()
                self.worker.join(timeout=2)
            if self.worker.is_alive():
                raise RuntimeError("Save process still alive; shared memory has not been released")
        self.pool.close()
        for channel in (self.task_queue, self.ack_queue, self.status_queue):
            channel.cancel_join_thread()
            channel.close()
        self._closed = True


def stop_pipeline(processes, acquisition, service, acquisition_timeout_s: int = 15, save_timeout_s: int = 120):
    """Run off the UI thread. Preserve the old controller termination behavior,
    allow acquisition to seal/flush, then drain saving and release parent resources.
    """
    errors = []
    if service is not None:
        service.stop_event.set()
    saver = service.worker if service is not None else None
    for process in processes:
        if process not in (acquisition, saver) and process.is_alive():
            process.terminate()
    if acquisition is not None:
        deadline = time.monotonic() + acquisition_timeout_s
        while acquisition.is_alive() and time.monotonic() < deadline:
            if service is not None:
                service.poll_status()
            acquisition.join(timeout=.05)
        if acquisition.is_alive():
            errors.append("采集停止超时，当前工件可能未完整提交保存")
            acquisition.terminate()
            acquisition.join(timeout=2)
        if acquisition.is_alive():
            acquisition.kill()
            acquisition.join(timeout=2)
        if acquisition.is_alive():
            raise RuntimeError("采集进程未退出，不能释放点云共享内存")
    for process in processes:
        if process not in (acquisition, saver):
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            if process.is_alive():
                errors.append(f"{process.name} 未退出")
    if service is not None:
        errors.extend(service.drain_and_close(save_timeout_s))
    return errors
