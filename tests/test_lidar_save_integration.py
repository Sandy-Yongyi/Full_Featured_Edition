import multiprocessing as mp
import queue
from types import SimpleNamespace
import unittest

import numpy as np

from acquisition_sdk._internal.lidar.LidarAcquisitionProcess import LidarAcquisitionProcess
from acquisition_sdk._internal.dataprocess.DataSplitting import DataSplitting
from acquisition_sdk._internal.pointcloud.PointCloudSaveBuffer import PointCloudSaveBuffer, SharedPointCloudPool, read_blocks


class AcquisitionSavingTests(unittest.TestCase):
    def test_missing_buffer_is_reported_before_capturing(self):
        self.process.save_buffer = None
        with self.assertRaisesRegex(RuntimeError, "save buffer is not initialized"):
            self.process._save_valid_data_core(0)

    def test_missing_task_queue_does_not_seal_or_lose_buffer(self):
        self.buffer.append("combined", np.ones((2, 3)))
        self.process.save_task_queue = None
        with self.assertRaisesRegex(RuntimeError, "task queue is not initialized"):
            self.process._save_workpiece_data()
        self.assertTrue(self.buffer.has_data)
        self.assertEqual(0, self.buffer.pending_jobs)

    def setUp(self):
        self.pool = SharedPointCloudPool.create(2400, 12)
        self.acks = mp.get_context("spawn").Queue()
        self.buffer = PointCloudSaveBuffer(self.pool.descriptor, self.acks)
        self.process = LidarAcquisitionProcess.__new__(LidarAcquisitionProcess)
        self.process.save_buffer = self.buffer
        self.process.save_task_queue = queue.Queue()
        self.process.save_status_queue = queue.Queue()
        self.process.stop_event = mp.get_context("spawn").Event()
        self.process.shutdown_flag = False
        self.process.plc_connection_generation = 7
        self.process.strategy_name = "frame_by_frame"
        self.process.read_data_config = {"translate_data_origin": 0, "y_threshold": 10,
                                         "max_pulse": 100, "pulse_to_mm": 1}
        self.process.data_split = DataSplitting()
        self.process.all_xyz_data = np.empty((0, 3))
        self.process.viz_queue = queue.Queue()
        self.process._save_job_counter = 0
        self.process.draw_type = 2
        self.process._processing_chunks = {}
        self.process.direction_states = {"left": SimpleNamespace(
            scanning_started=True, has_scanned=True, xyz_data=np.empty((0, 3)),
            last_same_origin_filtered=np.array([[10., 20.], [30., 40.]]),
            last_diff_origin_filtered=np.array([[100., 200.], [300., 400.]]))}

    def tearDown(self):
        self.buffer.close()
        self.pool.close()
        self.acks.close()
        self.acks.join_thread()

    def test_frame_by_frame_saves_all_points_without_whole_workpiece_arrays(self):
        self.process._save_valid_data_core(95)
        self.process._save_valid_data_core(2)
        self.assertEqual(len(self.process.direction_states["left"].xyz_data), 0)
        self.assertEqual(len(self.process.all_xyz_data), 0)
        self.process._save_workpiece_data()
        job = self.process.save_task_queue.get_nowait()
        left = np.concatenate(list(read_blocks(self.pool.descriptor, job["channels"]["left"])))
        combined = np.concatenate(list(read_blocks(self.pool.descriptor, job["channels"]["combined"])))
        self.assertEqual(len(left), 4)
        np.testing.assert_array_equal(left[:, :2], [[100, 200], [300, 400]] * 2)
        np.testing.assert_array_equal(combined[:, :2], [[10, 20], [30, 40]] * 2)
        self.assertTrue(self.process.viz_queue.empty())
        self.assertEqual(job["z_reset_threshold"], 100)

    def test_second_workpiece_can_submit_while_first_waits_for_saving(self):
        self.process._save_valid_data_core(0)
        self.process._save_workpiece_data()
        first = self.process.save_task_queue.get_nowait()
        self.process._save_valid_data_core(10)
        self.process._save_workpiece_data()
        second = self.process.save_task_queue.get_nowait()
        self.assertNotEqual(first["job_id"], second["job_id"])
        self.assertEqual(self.buffer.pending_jobs, 2)

    def test_stop_event_is_observed_in_inner_monitoring_loops(self):
        self.assertTrue(hasattr(self.process, "_stop_requested"), "stop event is not integrated")
        self.process.stop_event.set()
        self.assertTrue(self.process._stop_requested())

    def test_legacy_processing_strategy_keeps_accumulated_direction_data(self):
        self.process.strategy_name = "complete_workpiece"
        self.process._save_valid_data_core(95)
        self.process._save_valid_data_core(2)
        self.process._prepare_processing_data()
        self.assertEqual(len(self.process.direction_states["left"].xyz_data), 4)

    def test_three_modes_keep_their_own_coordinates_and_delivery_interfaces(self):
        from acquisition_sdk._internal.lidar.LidarAcquisitionStrategies import AcquisitionStrategyFactory
        for strategy in ("frame_by_frame", "complete_workpiece", "continuous_bidirectional"):
            for origin in (1, 2):
                with self.subTest(strategy=strategy, origin=origin):
                    self.buffer.release_unsaved()
                    self.process._processing_chunks = {}
                    self.process.strategy_name = strategy
                    self.process.read_data_config["translate_data_origin"] = origin
                    self.process.capture_direction = "reverse"
                    self.process.current_pulse = 2
                    self.process.lidar_status = 0
                    self.process.lidar_config = {"left": ["lidar1"]}
                    self.process.raw_data_queue = queue.Queue()
                    self.process.direction_states["left"].xyz_data = np.empty((0, 3))
                    self.process.direction_states["left"].stop_pulse = 2
                    self.process.continuous_scan_invalid = False
                    self.process._save_valid_data_core(95)
                    self.process._save_valid_data_core(2)
                    self.process._save_workpiece_data()
                    job = self.process.save_task_queue.get_nowait()
                    self.assertEqual(job["normalization"], "absolute_sorted" if strategy == "continuous_bidirectional" else "relative_z")
                    self.assertEqual(job["preview_enabled"], strategy != "complete_workpiece")
                    if strategy != "frame_by_frame":
                        self.process._prepare_processing_data()
                        data = self.process.direction_states["left"].xyz_data
                        self.assertEqual(len(data), 4)
                        self.assertEqual(set(data[:, 2]), {2., 95.} if strategy == "continuous_bidirectional" else {0., 7.})
                        AcquisitionStrategyFactory.create_strategy(strategy, self.process.read_data_config).send_raw_data(self.process)
                        packet = self.process.raw_data_queue.get_nowait()
                        self.assertEqual(packet["translate_data_origin"], origin)
                        self.assertEqual(packet["left_stop_pulse"], 2)
                        if origin == 1:
                            np.testing.assert_array_equal(packet["all_data"], self.process.all_xyz_data)
                        else:
                            np.testing.assert_array_equal(packet["left_data"], data)
                    # Release the test job; no real writer is running in this fixture.
                    self.buffer.acknowledge({"job_id": job["job_id"], "blocks": [b for v in job["channels"].values() for b in v]})

    def test_plc_frame_queue_continues_while_save_job_is_pending(self):
        from acquisition_sdk._internal.dataprocess.frame_by_frame.BuildSideFrame import build_side_frame
        self.process._save_valid_data_core(0)
        self.process._save_workpiece_data()
        self.process.raw_data_queue = queue.Queue()
        self.process.cm_accum = {}
        self.process.max_fifo = 160
        self.process.last_sent_fifo = -1
        self.process.active_directions = ["left"]
        self.process.build_side_frame = build_side_frame
        self.process.lidar_status = 0
        self.process.read_data_config.update(combined_y_min=0, combined_y_max=500)
        for fifo in (10, 11, 12):
            self.process.current_fifo = fifo
            self.process.send_data_to_queue({"left": np.array([[100, 200], [300, 400]])})
        self.assertEqual(self.buffer.pending_jobs, 1)
        for fifo in (10, 11, 12):
            message = self.process.raw_data_queue.get_nowait()
            self.assertEqual(message["fifo"], fifo)
            self.assertEqual(message["repeat_count"], 1)
            self.assertEqual(message["lidar_status"], 0)
            self.assertEqual(message["plc_generation"], 7)
            self.assertEqual(len(message["left"].FrameData), 50)

    def test_reset_discards_active_blocks_without_releasing_pending_save(self):
        from acquisition_sdk._internal.lidar.LidarDirectionState import LidarDirectionState
        self.process._save_valid_data_core(0)
        self.process._save_workpiece_data()
        job = self.process.save_task_queue.get_nowait()
        self.process._save_valid_data_core(10)
        config = {"left_scan_points_threshold": 10}
        self.process.direction_states = {"left": LidarDirectionState("left", config)}
        self.process._reset_base()
        self.assertFalse(self.buffer.has_data)
        self.assertEqual(self.buffer.pending_jobs, 1)
        points = np.concatenate(list(read_blocks(self.pool.descriptor, job["channels"]["left"])))
        self.assertEqual(len(points), 2)

    def test_continuous_interrupted_pass_releases_blocks_and_is_not_saved(self):
        from acquisition_sdk._internal.lidar.LidarAcquisitionStrategies import ContinuousBidirectionalStrategy
        from acquisition_sdk._internal.lidar.LidarDirectionState import LidarDirectionState
        from model.utils.ProcessHeartbeat import ProcessHeartbeat
        self.process.strategy_name = "continuous_bidirectional"
        self.process._save_valid_data_core(95)
        self.process.direction_states = {"left": LidarDirectionState("left", {"left_scan_points_threshold": 10})}
        self.process._heartbeat = ProcessHeartbeat()
        self.process.scan_position_tolerance = 1
        self.process.read_data_config["max_swing_pulse"] = 100
        self.process.plc_disconnected = True
        self.process.raw_data_queue = queue.Queue()
        self.process.lidar_status = 3
        self.process._update_pulse_data = lambda: (10, 0, "moving_forward")
        ContinuousBidirectionalStrategy(self.process.read_data_config).monitor_movement(self.process)
        self.assertTrue(self.process.continuous_scan_invalid)
        self.assertTrue(self.process.continuous_wait_for_idle)
        self.assertFalse(self.buffer.has_data)
        self.assertEqual(self.process._processing_chunks, {})
        self.process._save_workpiece_data()
        self.assertTrue(self.process.save_task_queue.empty())


if __name__ == "__main__":
    unittest.main()
