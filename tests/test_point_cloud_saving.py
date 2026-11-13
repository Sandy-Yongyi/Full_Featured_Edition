import importlib.util
import multiprocessing as mp
import unittest
import tempfile
from pathlib import Path

import numpy as np


class BufferTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("acquisition_sdk._internal.pointcloud.PointCloudSaveBuffer"), "shared point cloud buffer is not implemented")
        from acquisition_sdk._internal.pointcloud.PointCloudSaveBuffer import SharedPointCloudPool, PointCloudSaveBuffer
        self.pool = SharedPointCloudPool.create(block_bytes=72, block_count=4)
        self.acks = mp.get_context("spawn").Queue()
        self.buffer = PointCloudSaveBuffer(self.pool.descriptor, self.acks)

    def tearDown(self):
        if hasattr(self, "buffer"):
            self.buffer.close()
            self.pool.close()
            self.acks.close()
            self.acks.join_thread()

    def test_pending_workpieces_never_share_blocks(self):
        a = np.arange(12, dtype=np.float64).reshape(-1, 3)
        self.buffer.append("left", a)
        first = self.buffer.seal("a")
        self.buffer.append("left", a + 100)
        second = self.buffer.seal("b")
        self.assertTrue(set(b["slot_id"] for b in first["channels"]["left"]).isdisjoint(b["slot_id"] for b in second["channels"]["left"]))
        from acquisition_sdk._internal.pointcloud.PointCloudSaveBuffer import read_blocks
        actual = np.concatenate(list(read_blocks(self.pool.descriptor, first["channels"]["left"])))
        np.testing.assert_array_equal(actual, a)

    def test_full_pool_does_not_overwrite_and_ack_releases_only_matching_job(self):
        from acquisition_sdk._internal.pointcloud.PointCloudSaveBuffer import SaveBufferFull, read_blocks
        data = np.arange(36, dtype=np.float64).reshape(-1, 3)
        self.buffer.append("combined", data)
        job = self.buffer.seal("a")
        with self.assertRaises(SaveBufferFull):
            self.buffer.append("combined", data[:1])
        self.assertFalse(self.buffer.acknowledge({"job_id": "wrong", "blocks": job["channels"]["combined"]}))
        np.testing.assert_array_equal(np.concatenate(list(read_blocks(self.pool.descriptor, job["channels"]["combined"]))), data)
        ack = {"job_id": "a", "blocks": job["channels"]["combined"]}
        self.assertTrue(self.buffer.acknowledge(ack))
        self.buffer.append("left", data[:1])
        self.assertFalse(self.buffer.acknowledge(ack))

    def test_append_is_atomic_when_not_enough_space(self):
        from acquisition_sdk._internal.pointcloud.PointCloudSaveBuffer import SaveBufferFull
        self.buffer.append("left", np.ones((2, 3)))
        with self.assertRaises(SaveBufferFull):
            self.buffer.append("left", np.ones((20, 3)))
        job = self.buffer.seal("partial")
        self.assertEqual(sum(b["count"] for b in job["channels"]["left"]), 2)

    def test_discard_releases_only_unsubmitted_workpiece(self):
        self.buffer.append("left", np.ones((3, 3)))
        job = self.buffer.seal("pending")
        self.buffer.append("left", np.ones((3, 3)))
        self.buffer.release_unsaved()
        self.assertEqual(self.buffer.free_blocks, 3)
        self.assertTrue(self.buffer.acknowledge({"job_id": "pending", "blocks": job["channels"]["left"]}))
        self.assertEqual(self.buffer.free_blocks, 4)


class WriterTests(BufferTests):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec("acquisition_sdk._internal.pointcloud.PointCloudSaveProcess"), "point cloud writer is not implemented")
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)

    def tearDown(self):
        if hasattr(self, "directory"):
            self.directory.cleanup()
        super().tearDown()

    def make_job(self):
        points = np.array([[1.23, 2.34, 95], [3, 4, 98], [5, 6, 2], [7, 8, 5]])
        self.buffer.append("combined", points)
        return points, self.buffer.seal("20261012_120000_000001", z_reset_threshold=100, filename_suffix="20261012_120000_000001", incomplete=False)

    def test_txt_matches_legacy_normalization_across_blocks(self):
        from acquisition_sdk._internal.pointcloud.PointCloudSaveProcess import save_job
        points, job = self.make_job()
        save_job(job, self.pool.descriptor, self.directory.name, file_format="txt")
        expected = points.copy()
        expected[:, 2] = [0, 3, 7, 10]
        path = Path(self.directory.name) / f"combined_{job['filename_suffix']}.txt"
        reference = Path(self.directory.name) / "reference.txt"
        np.savetxt(reference, expected, fmt="%.1f")
        self.assertEqual(path.read_bytes(), reference.read_bytes())
        self.assertTrue((Path(self.directory.name) / f"{job['job_id']}.complete.json").exists())

    def test_continuous_reverse_keeps_absolute_z_and_sorts_entire_channel(self):
        from acquisition_sdk._internal.pointcloud.PointCloudSaveProcess import save_job
        points = np.array([[3., 20., 98.], [2., 10., 98.], [1., 20., 95.], [9., 2., 50.]])
        self.buffer.append("combined", points)
        job = self.buffer.seal("reverse", strategy="continuous_bidirectional", normalization="absolute_sorted", preview_enabled=True)
        preview = save_job(job, self.pool.descriptor, self.directory.name, file_format="npy")
        expected = points[np.lexsort((points[:, 0], points[:, 1], points[:, 2]))]
        np.testing.assert_array_equal(np.load(Path(self.directory.name) / "combined_reverse.npy"), expected)
        np.testing.assert_array_equal(preview, expected)
        self.assertEqual(preview[0, 2], 50.)

    def test_right_origin_transforms_preview_only_and_block_mode_suppresses_preview(self):
        from acquisition_sdk._internal.pointcloud.PointCloudSaveProcess import save_job
        _, job = self.make_job()
        job["preview_origin_config"] = {"workpiece_origin_side": "right", "workpiece_origin_reference_x": 1540}
        preview = save_job(job, self.pool.descriptor, self.directory.name, file_format="npy")
        saved = np.load(Path(self.directory.name) / f"combined_{job['filename_suffix']}.npy")
        np.testing.assert_array_equal(preview[:, 0], 1540 - saved[:, 0])
        job = {**job, "job_id": "blocks", "filename_suffix": "blocks", "preview_enabled": False}
        preview = save_job(job, self.pool.descriptor, self.directory.name, file_format="npy")
        self.assertIsNone(preview)

    def test_many_fractional_wraps_match_original_algorithm_exactly(self):
        from acquisition_sdk._internal.pointcloud.PointCloudSaveProcess import save_job
        from acquisition_sdk._internal.dataprocess.DataSplitting import DataSplitting
        threshold = 160000 / 5.3
        points = np.column_stack((np.zeros(12), np.zeros(12), np.tile([threshold * .95, 1], 6)))
        self.buffer.append("left", points)
        job = self.buffer.seal("wraps", z_reset_threshold=threshold)
        save_job(job, self.pool.descriptor, self.directory.name, file_format="npy")
        result = np.load(Path(self.directory.name) / "left_wraps.npy")
        np.testing.assert_array_equal(result, DataSplitting().normalize_xyz_points(points, threshold))

    def test_npy_preserves_precision_and_preview_has_no_fixed_point_limit(self):
        from acquisition_sdk._internal.pointcloud.PointCloudSaveProcess import save_job, make_preview
        points, job = self.make_job()
        preview = save_job(job, self.pool.descriptor, self.directory.name, file_format="npy")
        loaded = np.load(Path(self.directory.name) / f"combined_{job['filename_suffix']}.npy")
        self.assertEqual(loaded.dtype, np.float64)
        self.assertEqual(loaded[0, 0], points[0, 0])
        np.testing.assert_array_equal(preview, loaded)
        many = np.column_stack((np.arange(210001), np.zeros(210001), np.zeros(210001)))
        self.assertEqual(len(make_preview(many, 0)), 210001)
        reduced = make_preview(np.array([[0, 0, 0], [.5, .5, .5], [3, 0, 0]]), 1)
        self.assertEqual(len(reduced), 2)

    def test_spawn_worker_drains_jobs_and_acknowledges(self):
        from acquisition_sdk._internal.pointcloud.PointCloudSaveProcess import PointCloudSaveProcess
        context = mp.get_context("spawn")
        tasks, statuses = context.Queue(), context.Queue()
        points, job = self.make_job()
        worker = PointCloudSaveProcess(tasks, self.acks, statuses, self.pool.descriptor, self.directory.name)
        worker.start()
        try:
            self.assertEqual(statuses.get(timeout=10)["type"], "ready")
            tasks.put(job)
            tasks.put(None)
            ack = self.acks.get(timeout=10)
            self.assertTrue(self.buffer.acknowledge(ack))
            worker.join(10)
            self.assertEqual(worker.exitcode, 0)
            self.assertEqual(len(np.loadtxt(Path(self.directory.name) / f"combined_{job['filename_suffix']}.txt")), len(points))
        finally:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
            for channel in (tasks, statuses):
                channel.close()
                channel.join_thread()

    def test_spawn_write_error_reports_failure_without_ack(self):
        from acquisition_sdk._internal.pointcloud.PointCloudSaveProcess import PointCloudSaveProcess
        context = mp.get_context("spawn")
        tasks, statuses = context.Queue(), context.Queue()
        _, job = self.make_job()
        worker = PointCloudSaveProcess(tasks, self.acks, statuses, self.pool.descriptor, self.directory.name, config={"point_cloud_save_format": "invalid"})
        worker.start()
        try:
            message = statuses.get(timeout=10)
            self.assertEqual(message["type"], "error")
            worker.join(10)
            self.assertEqual(self.buffer.free_blocks, 2)
        finally:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
            for channel in (tasks, statuses):
                channel.close()
                channel.join_thread()


if __name__ == "__main__":
    unittest.main()
