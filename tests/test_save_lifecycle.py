import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np


class SaveServiceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("acquisition_sdk._internal.pointcloud.PointCloudSaveService"), "saving lifecycle is not implemented")
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)

    def tearDown(self):
        if hasattr(self, "directory"):
            self.directory.cleanup()

    def test_sibling_service_waits_for_ready_and_drains_multiple_workpieces(self):
        from acquisition_sdk._internal.pointcloud.PointCloudSaveService import PointCloudSaveService
        from acquisition_sdk._internal.pointcloud.PointCloudSaveBuffer import PointCloudSaveBuffer
        service = PointCloudSaveService({"point_cloud_save_block_mb": .01, "point_cloud_save_block_count": 8}, self.directory.name)
        buffer = None
        try:
            service.start()
            buffer = PointCloudSaveBuffer(service.pool.descriptor, service.ack_queue)
            for i in range(2):
                buffer.append("left", np.full((100, 3), float(i)))
                service.task_queue.put(buffer.seal(f"job_{i}"))
            buffer.close()
            buffer = None
            errors = service.drain_and_close(timeout_s=10)
            self.assertEqual(errors, [])
            self.assertEqual(service.worker.exitcode, 0)
            for i in range(2):
                points = np.loadtxt(Path(self.directory.name) / f"left_job_{i}.txt")
                self.assertEqual(len(points), 100)
                self.assertEqual(points[0, 0], i)
        finally:
            if buffer is not None:
                buffer.close()
            service.abort()

    def test_bad_configuration_fails_before_acquisition_start(self):
        from acquisition_sdk._internal.pointcloud.PointCloudSaveService import PointCloudSaveService
        service = PointCloudSaveService({"point_cloud_save_block_mb": .01, "point_cloud_save_block_count": 4, "point_cloud_save_format": "bad"}, self.directory.name)
        try:
            with self.assertRaisesRegex(RuntimeError, "txt or npy"):
                service.start()
        finally:
            service.abort()

    def test_crashed_writer_cannot_be_reported_as_successfully_drained(self):
        from acquisition_sdk._internal.pointcloud.PointCloudSaveService import PointCloudSaveService
        service = PointCloudSaveService({"point_cloud_save_block_mb": .01, "point_cloud_save_block_count": 4}, self.directory.name)
        try:
            service.start()
            service.worker.terminate()
            service.worker.join(5)
            errors = service.drain_and_close(timeout_s=1)
            self.assertTrue(errors, "writer never acknowledged draining but shutdown reported success")
        finally:
            service.abort()

    def test_real_disk_error_is_reported_and_no_completion_manifest_is_written(self):
        from acquisition_sdk._internal.pointcloud.PointCloudSaveService import PointCloudSaveService
        from acquisition_sdk._internal.pointcloud.PointCloudSaveBuffer import PointCloudSaveBuffer
        service = PointCloudSaveService({"point_cloud_save_block_mb": .01, "point_cloud_save_block_count": 4}, self.directory.name)
        buffer = None
        try:
            service.start()
            (Path(self.directory.name) / "left_fail.txt").mkdir()
            buffer = PointCloudSaveBuffer(service.pool.descriptor, service.ack_queue)
            buffer.append("left", np.ones((2, 3)))
            service.task_queue.put(buffer.seal("fail"))
            buffer.close()
            buffer = None
            errors = service.drain_and_close(timeout_s=10)
            self.assertTrue(errors)
            self.assertFalse((Path(self.directory.name) / "fail.complete.json").exists())
        finally:
            if buffer is not None:
                buffer.close()
            service.abort()


if __name__ == "__main__":
    unittest.main()
