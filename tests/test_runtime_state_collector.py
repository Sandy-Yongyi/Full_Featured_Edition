import queue
import unittest

import numpy as np

from model.telemetry.RuntimeStateCollector import RuntimeStateCollector


class _Filter:
    def __init__(self):
        self.calls = []

    def voxelReductionFilter(self, points, voxel_size):
        self.calls.append((points, voxel_size))
        return points[::2]


class RuntimeStateCollectorTests(unittest.TestCase):
    def test_backlog_filters_only_latest_points_even_with_box_only_update(self):
        frames = queue.Queue()
        point_filter = _Filter()
        collector = RuntimeStateCollector(queue.Queue(), point_filter)
        collector.set_visualization_queue(frames)
        older = np.zeros((6, 3))
        latest = np.arange(18).reshape(6, 3)
        frames.put({"points": older})
        frames.put({"points": latest})
        frames.put({"boxes": ["latest box"]})

        snapshot = collector.poll()

        self.assertEqual(1, len(point_filter.calls))
        self.assertIs(latest, point_filter.calls[0][0])
        np.testing.assert_array_equal(latest[::2], snapshot["points"])
        self.assertTrue(snapshot["points_updated"])
        self.assertEqual(["latest box"], snapshot["boxes"])

    def test_visualization_backlog_yields_to_logs_and_later_polls(self):
        frames = queue.Queue()
        logs = queue.Queue()
        logs.put(("stderr", "device disconnected"))
        collector = RuntimeStateCollector(logs, None, preview_voxel_mm=0)
        collector.set_visualization_queue(frames)
        for index in range(100):
            frames.put({"points": np.full((1, 3), index)})

        snapshot = collector.poll()

        self.assertGreater(frames.qsize(), 0, "One UI tick must not drain all pending clouds")
        self.assertLess(frames.qsize(), 100)
        self.assertEqual("device disconnected", snapshot["logs"][0].message)
        self.assertEqual("ERROR", snapshot["logs"][0].level)
        while not frames.empty():
            snapshot = collector.poll()
        np.testing.assert_array_equal([[99, 99, 99]], snapshot["points"])

    def test_latest_preprocessed_cloud_skips_filter_despite_older_raw_frame(self):
        frames = queue.Queue()
        point_filter = _Filter()
        collector = RuntimeStateCollector(queue.Queue(), point_filter)
        collector.set_visualization_queue(frames)
        frames.put({"points": np.zeros((6, 3))})
        latest = np.ones((3, 3))
        frames.put({"points": latest, "preview_processed": True})
        frames.put({"boxes": None})

        snapshot = collector.poll()

        self.assertEqual([], point_filter.calls)
        self.assertIs(latest, snapshot["points"])

    def test_explicit_clear_supersedes_pending_cloud_without_filtering_it(self):
        frames = queue.Queue()
        point_filter = _Filter()
        collector = RuntimeStateCollector(queue.Queue(), point_filter)
        collector.set_visualization_queue(frames)
        frames.put({"points": np.ones((6, 3)), "boxes": ["old box"]})
        frames.put({"points": None, "boxes": None})

        snapshot = collector.poll()

        self.assertEqual([], point_filter.calls)
        self.assertTrue(snapshot["updated"])
        self.assertTrue(snapshot["points_updated"])
        self.assertIsNone(snapshot["points"])
        self.assertIsNone(snapshot["boxes"])

    def test_poll_drains_logs_and_latest_visualization_without_touching_a_view(self):
        log_queue = queue.Queue()
        viz_queue = queue.Queue()
        log_queue.put(("stdout", "PLC online"))
        points = np.array([[0, 0, 0], [1, 1, 1], [2, 2, 2]], dtype=float)
        viz_queue.put({"points": points, "boxes": [{"name": "workpiece"}]})
        point_filter = _Filter()
        collector = RuntimeStateCollector(log_queue, point_filter, preview_voxel_mm=10)
        collector.set_visualization_queue(viz_queue)

        snapshot = collector.poll()

        self.assertEqual(["PLC online"], [event.message for event in snapshot["logs"]])
        self.assertEqual(1, len(point_filter.calls))
        np.testing.assert_array_equal(points[::2], snapshot["points"])
        self.assertEqual([{"name": "workpiece"}], snapshot["boxes"])

    def test_poll_does_not_filter_a_preprocessed_preview_or_clear_boxes(self):
        viz_queue = queue.Queue()
        points = np.array([[0, 0, 0]], dtype=float)
        viz_queue.put({"points": points, "preview_processed": True})
        point_filter = _Filter()
        collector = RuntimeStateCollector(queue.Queue(), point_filter, preview_voxel_mm=10)
        collector.set_visualization_queue(viz_queue)

        snapshot = collector.poll()

        self.assertEqual([], point_filter.calls)
        self.assertIsNone(snapshot["boxes"])
        np.testing.assert_array_equal(points, snapshot["points"])

    def test_log_and_visualization_polling_can_run_at_different_intervals(self):
        log_queue = queue.Queue()
        viz_queue = queue.Queue()
        log_queue.put(("stdout", "first"))
        viz_queue.put({"points": np.array([[1, 2, 3]], dtype=float)})
        collector = RuntimeStateCollector(log_queue, _Filter())
        collector.set_visualization_queue(viz_queue)

        self.assertEqual(["first"], collector.poll_logs())
        visualization = collector.poll_visualization()

        self.assertIsNotNone(visualization["points"])
        self.assertIsNone(visualization["boxes"])
