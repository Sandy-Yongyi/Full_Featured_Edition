"""CPU/file simulation only; no radar or PLC commands are issued."""

import multiprocessing as mp
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np

from acquisition_sdk._internal.pointcloud.PointCloudSaveBuffer import PointCloudSaveBuffer
from acquisition_sdk._internal.pointcloud.PointCloudSaveService import PointCloudSaveService, stop_pipeline


def _seal_on_stop(descriptor, tasks, acks, stop_event):
    buffer = PointCloudSaveBuffer(descriptor, acks)
    try:
        buffer.append("combined", np.ones((40, 3)))
        while not stop_event.wait(.01):
            pass
        tasks.put(buffer.seal("stopped", incomplete=True))
    finally:
        buffer.close()


def _acquisition_cleanup_with_backlog(descriptor, tasks, acks, statuses, raw_queue, stop_event, ready):
    from acquisition_sdk._internal.lidar.LidarAcquisitionProcess import LidarAcquisitionProcess
    acquisition = LidarAcquisitionProcess.__new__(LidarAcquisitionProcess)
    acquisition.save_buffer = PointCloudSaveBuffer(descriptor, acks)
    acquisition.save_task_queue = tasks
    acquisition.save_status_queue = statuses
    acquisition.raw_data_queue = raw_queue
    acquisition._save_job_counter = 0
    acquisition.strategy_name = "frame_by_frame"
    acquisition.read_data_config = {"max_pulse": 100, "pulse_to_mm": 1}
    acquisition.save_buffer.append("combined", np.ones((40, 3)))
    raw_queue.put(b"x" * 1024 * 1024)  # Deliberately no PLC consumer after stopping.
    ready.set()
    stop_event.wait(10)
    acquisition._cleanup()


class PipelineStressTests(unittest.TestCase):
    def test_acquisition_cleanup_flushes_save_without_waiting_for_unconsumed_plc_queue(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            service = PointCloudSaveService({"point_cloud_save_block_mb": .01, "point_cloud_save_block_count": 8}, directory)
            context = mp.get_context("spawn")
            raw_queue, ready = context.Queue(), context.Event()
            producer = context.Process(target=_acquisition_cleanup_with_backlog, args=(
                service.pool.descriptor, service.task_queue, service.ack_queue, service.status_queue,
                raw_queue, service.stop_event, ready))
            service.start()
            producer.start()
            try:
                self.assertTrue(ready.wait(15))
                errors = stop_pipeline([producer, service.worker], producer, service, 1, 10)
                self.assertEqual(errors, [])
                self.assertEqual(producer.exitcode, 0)
                files = list(Path(directory).glob("combined_*.txt"))
                self.assertEqual(len(files), 1)
                self.assertEqual(len(np.loadtxt(files[0])), 40)
            finally:
                if producer.is_alive():
                    producer.terminate()
                    producer.join(5)
                service.abort()
                raw_queue.close()
                raw_queue.join_thread()

    def test_stop_waits_for_producer_to_flush_final_job_before_sentinel(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            service = PointCloudSaveService({"point_cloud_save_block_mb": .01, "point_cloud_save_block_count": 8}, directory)
            producer = mp.get_context("spawn").Process(target=_seal_on_stop, args=(service.pool.descriptor, service.task_queue, service.ack_queue, service.stop_event))
            service.start()
            producer.start()
            try:
                errors = stop_pipeline([producer, service.worker], producer, service, 10, 10)
                self.assertEqual(errors, [])
                self.assertEqual(producer.exitcode, 0)
                self.assertEqual(len(np.loadtxt(Path(directory) / "combined_stopped.txt")), 40)
                import json
                self.assertTrue(json.loads((Path(directory) / "stopped.complete.json").read_text())["incomplete"])
            finally:
                if producer.is_alive():
                    producer.terminate()
                    producer.join(5)
                service.abort()

    def test_consecutive_large_workpieces_submit_without_waiting_for_disk(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            service = PointCloudSaveService({"point_cloud_save_block_mb": 2, "point_cloud_save_block_count": 12, "point_cloud_preview_voxel_mm": 0}, directory)
            buffer = PointCloudSaveBuffer(service.pool.descriptor, service.ack_queue)
            service.start()
            samples = []
            try:
                for job_number in range(3):
                    # 3 MB of full-precision XYZ per workpiece; frame-sized appends.
                    for start in range(0, 125000, 1000):
                        n = min(1000, 125000 - start)
                        points = np.column_stack((np.full(n, job_number + .12345), np.arange(start, start + n), np.full(n, start)))
                        buffer.append("combined", points)
                    started = time.perf_counter()
                    service.task_queue.put_nowait(buffer.seal(f"large_{job_number}"))
                    samples.append(time.perf_counter() - started)
                buffer.close()
                errors = service.drain_and_close(30)
                self.assertEqual(errors, [])
                for job_number in range(3):
                    points = np.loadtxt(Path(directory) / f"combined_large_{job_number}.txt")
                    self.assertEqual(len(points), 125000)
                    self.assertEqual(points[0, 0], round(job_number + .12345, 1))
                # Report measured submission times, without making a machine-specific SLA assertion.
                print(f"\nSimulation metadata submit times (s): {samples}")
            finally:
                if not service._closed:
                    buffer.close()
                    service.abort()


if __name__ == "__main__":
    unittest.main()
