import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


class UiTelemetryTests(unittest.TestCase):
    def test_servo_and_mode_decode_independent_bits_and_expire(self):
        from control.PipelineRuntime import PipelineRuntime
        runtime = PipelineRuntime()
        runtime.strategy_name = "frame_by_frame"
        runtime.ui_status_queue = queue.Queue()
        runtime.plc_handler = SimpleNamespace(is_alive=lambda: True)
        for status, healthy, mode in ((0, False, "PLC点动模式"), (1, True, "PLC点动模式"), (2, False, "PC自动模式"), (3, True, "PC自动模式")):
            with self.subTest(status=status):
                runtime.ui_status_queue.put({"source": "plc", "timestamp": 100, "connected": True, "plc_status": status})
                with patch("control.PipelineRuntime.time.monotonic", return_value=101):
                    servo = runtime.poll()["devices"][2]
                self.assertEqual(healthy, servo.online)
                self.assertIn(mode, servo.detail)
        runtime.strategy_name = "continuous_bidirectional"
        with patch("control.PipelineRuntime.time.monotonic", return_value=101):
            self.assertEqual("", runtime.poll()["devices"][2].detail)
        with patch("control.PipelineRuntime.time.monotonic", return_value=110):
            servo = runtime.poll()["devices"][2]
        self.assertFalse(servo.online)
        self.assertEqual("等待 PLC", servo.detail)

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
        from control.PipelineRuntime import PipelineRuntime
        from model.telemetry.UiState import TaskState
        runtime = PipelineRuntime()
        runtime.ui_status_queue = queue.Queue()
        runtime.plc_handler = SimpleNamespace(is_alive=lambda: True)
        runtime.lidar_acquisition = SimpleNamespace(is_alive=lambda: True)
        self.assertFalse(runtime.poll()["devices"][0].online)
        task = TaskState(name="当前工件", stage="外侧前喷")
        runtime.ui_status_queue.put({"source": "plc", "timestamp": 100, "connected": True, "pulse": 18229, "motion": "moving_forward", "task": task})
        runtime.ui_status_queue.put({"source": "lidar", "timestamp": 100, "connected": True, "status": 0})
        with patch("control.PipelineRuntime.time.monotonic", return_value=101):
            snapshot = runtime.poll()
        self.assertTrue(snapshot["devices"][0].online)
        self.assertTrue(snapshot["devices"][1].online)
        self.assertFalse(snapshot["devices"][2].online)  # Servo ready has no defined feedback yet.
        self.assertEqual(18229, snapshot["chain_position"])
        self.assertEqual(task, snapshot["task"])
        with patch("control.PipelineRuntime.time.monotonic", return_value=110):
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
        process.plc = SimpleNamespace(scan=lambda _: SimpleNamespace(ChainPulse=18229, Status=3, AxisList=[]))
        process.connection_type = 1
        process._update_chain_status = Mock()
        self.assertTrue(process._update_plc_data())
        message = output.get_nowait()
        self.assertTrue(message["connected"])
        self.assertEqual(18229, message["pulse"])
        self.assertEqual(3, message["plc_status"])

    def test_lidar_feedback_distinguishes_healthy_and_failed_scan(self):
        from acquisition_sdk._internal.lidar.LidarAcquisitionProcess import LidarAcquisitionProcess
        from model.utils.UiTelemetry import UiStatusPublisher
        output = queue.Queue()
        state = SimpleNamespace(ui_status=UiStatusPublisher(output, "lidar"),
                                active_directions=["left"], lidar_disconnected=False)
        LidarAcquisitionProcess._publish_ui_status(state, 0, force=True)
        self.assertTrue(output.get_nowait()["connected"])
        LidarAcquisitionProcess._publish_ui_status(state, 3, force=True)
        self.assertFalse(output.get_nowait()["connected"])
