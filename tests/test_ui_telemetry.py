import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


class UiTelemetryTests(unittest.TestCase):
    def test_publisher_throttles_and_never_waits_for_a_full_queue(self):
        from model.utils.UiTelemetry import UiStatusPublisher
        output = queue.Queue(maxsize=1)
        publisher = UiStatusPublisher(output, "plc")
        with patch("model.utils.UiTelemetry.time.monotonic", return_value=10):
            publisher.publish(connected=True)
            publisher.publish(connected=False)
        self.assertEqual(1, output.qsize())
        with patch("model.utils.UiTelemetry.time.monotonic", return_value=11):
            publisher.publish(connected=False)  # Full queue is harmless.
        self.assertTrue(output.get_nowait()["connected"])

    def test_runtime_requires_fresh_feedback_even_when_workers_are_alive(self):
        from control.QtPipelineRuntime import QtPipelineRuntime
        from control.UiState import TaskState
        runtime = QtPipelineRuntime()
        runtime.ui_status_queue = queue.Queue()
        runtime.plc_handler = SimpleNamespace(is_alive=lambda: True)
        runtime.lidar_acquisition = SimpleNamespace(is_alive=lambda: True)
        self.assertFalse(runtime.poll()["devices"][0].online)
        task = TaskState(name="当前工件", stage="外侧前喷")
        runtime.ui_status_queue.put({"source": "plc", "timestamp": 100, "connected": True, "pulse": 18229, "motion": "moving_forward", "task": task})
        runtime.ui_status_queue.put({"source": "lidar", "timestamp": 100, "connected": True, "status": 0})
        with patch("control.QtPipelineRuntime.time.monotonic", return_value=101):
            snapshot = runtime.poll()
        self.assertTrue(snapshot["devices"][0].online)
        self.assertTrue(snapshot["devices"][1].online)
        self.assertFalse(snapshot["devices"][2].online)  # Servo ready has no defined feedback yet.
        self.assertEqual(18229, snapshot["chain_position"])
        self.assertEqual(task, snapshot["task"])
        with patch("control.QtPipelineRuntime.time.monotonic", return_value=110):
            stale = runtime.poll()
            self.assertFalse(stale["devices"][0].online)
            self.assertEqual((), stale["task"].gun_plans)
            self.assertNotEqual(task.stage, stale["task"].stage)

    def test_plc_successful_scan_publishes_actual_pulse(self):
        from control.PlcCommunicationProcess import PlcCommunicationProcess
        from model.utils.UiTelemetry import UiStatusPublisher
        output = queue.Queue()
        process = PlcCommunicationProcess(queue.Queue(), queue.Queue(), queue.Queue())
        process.ui_status = UiStatusPublisher(output, "plc")
        process.plc = SimpleNamespace(scan=lambda _: SimpleNamespace(ChainPulse=18229, AxisList=[]))
        process.connection_type = 1
        process._update_chain_status = Mock()
        self.assertTrue(process._update_plc_data())
        message = output.get_nowait()
        self.assertTrue(message["connected"])
        self.assertEqual(18229, message["pulse"])

    def test_lidar_feedback_distinguishes_healthy_and_failed_scan(self):
        from control.LidarAcquisitionProcess import LidarAcquisitionProcess
        from model.utils.UiTelemetry import UiStatusPublisher
        output = queue.Queue()
        state = SimpleNamespace(ui_status=UiStatusPublisher(output, "lidar"),
                                active_directions=["left"], lidar_disconnected=False)
        LidarAcquisitionProcess._publish_ui_status(state, 0, force=True)
        self.assertTrue(output.get_nowait()["connected"])
        LidarAcquisitionProcess._publish_ui_status(state, 3, force=True)
        self.assertFalse(output.get_nowait()["connected"])
