import threading
import time
import unittest

from control.ControlCenter import ControlCenter
from model.telemetry.UiState import LogEvent


class _Runtime:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.poll_count = 0

    def start_pipeline(self):
        self.started += 1

    def stop_pipeline(self):
        self.stopped += 1
        return []

    def poll(self):
        self.poll_count += 1
        return {"chain_position": 18229, "chain_status": "moving_forward", "logs": [LogEvent(level="INFO", message="PLC connected", source="plc")], }


class ControlCenterTests(unittest.TestCase):
    def test_start_and_stop_are_idempotent_and_publish_runtime_state(self):
        runtime = _Runtime()
        center = ControlCenter(runtime, strategy_name="complete_workpiece", chain_speed=25)

        self.assertTrue(center.start())
        self.assertFalse(center.start())
        center.poll_once()
        state = center.build_ui_state()

        self.assertTrue(state.running)
        self.assertEqual(1, runtime.started)
        self.assertEqual(18229, state.chain_position)
        self.assertEqual("moving_forward", state.chain_status)
        self.assertEqual("PLC connected", state.logs[-1].message)

        self.assertTrue(center.stop())
        self.assertFalse(center.stop())
        self.assertEqual(1, runtime.stopped)
        self.assertFalse(center.build_ui_state().running)
        self.assertFalse(center.build_ui_state().stopping)

    def test_start_failure_returns_controller_to_idle_state(self):
        class FailingRuntime(_Runtime):
            def start_pipeline(self):
                raise RuntimeError("PLC unavailable")

        center = ControlCenter(FailingRuntime(), strategy_name="frame_by_frame")

        with self.assertRaisesRegex(RuntimeError, "PLC unavailable"):
            center.start()

        state = center.build_ui_state()
        self.assertFalse(state.running)
        self.assertFalse(state.stopping)
        self.assertEqual("启动失败", state.chain_status)

    def test_setting_chain_speed_persists_then_notifies_running_runtime(self):
        runtime = _Runtime()
        persisted = []
        commands = []
        center = ControlCenter(runtime, strategy_name="continuous_bidirectional", save_chain_speed=persisted.append, send_control=commands.append,)

        center.set_chain_speed(32)
        self.assertEqual([32], persisted)
        self.assertEqual([], commands)
        self.assertEqual(32, center.build_ui_state().chain_speed)

        center.start()
        center.set_chain_speed(28)
        self.assertEqual([32, 28], persisted)
        self.assertEqual([{"lidar_scan_speed": 28}], commands)

    def test_setting_invalid_chain_speed_does_not_persist(self):
        persisted = []
        center = ControlCenter(_Runtime(), strategy_name="frame_by_frame", save_chain_speed=persisted.append)

        with self.assertRaisesRegex(ValueError, "1～50"):
            center.set_chain_speed(51)

        self.assertEqual([], persisted)

    def test_async_stop_keeps_state_stopping_until_workers_finish(self):
        release = threading.Event()
        finished = threading.Event()

        class SlowRuntime(_Runtime):
            def stop_pipeline(self):
                release.wait(timeout=1)
                finished.set()
                return []

        center = ControlCenter(SlowRuntime(), strategy_name="complete_workpiece", async_stop=True)
        center.start()

        self.assertTrue(center.stop())
        self.assertTrue(center.build_ui_state().stopping)
        release.set()
        self.assertTrue(finished.wait(timeout=1))
        deadline = time.monotonic() + 1
        while center.build_ui_state().stopping and time.monotonic() < deadline:
            center.poll_once()
            time.sleep(0.001)
        self.assertFalse(center.build_ui_state().stopping)

    def test_start_failure_cleans_partially_started_workers(self):
        class FailingRuntime(_Runtime):
            def start_pipeline(self):
                raise RuntimeError("partial startup")

        runtime = FailingRuntime()
        center = ControlCenter(runtime, "complete_workpiece")
        with self.assertRaisesRegex(RuntimeError, "partial startup"):
            center.start()
        self.assertEqual(1, runtime.stopped)

    def test_runtime_fault_triggers_stop_once_and_keeps_alarm(self):
        class FaultRuntime(_Runtime):
            def poll(self):
                return {"fault": "PLC heartbeat timeout", "alarms": ("PLC heartbeat timeout",)}

        runtime = FaultRuntime()
        center = ControlCenter(runtime, "complete_workpiece")
        center.start()
        center.poll_once()
        center.poll_once()
        self.assertEqual(1, runtime.stopped)
        self.assertFalse(center.running)
        self.assertIn("PLC heartbeat timeout", center.build_ui_state().alarms)

    def test_live_workers_after_shutdown_block_restart(self):
        class StuckRuntime(_Runtime):
            def has_live_workers(self):
                return self.stopped > 0

        center = ControlCenter(StuckRuntime(), "complete_workpiece")
        center.start()
        center.stop()
        self.assertTrue(center.stopping)
        self.assertFalse(center.start())
        self.assertEqual("停止失败", center.build_ui_state().chain_status)

    def test_shutdown_warning_stays_visible_after_runtime_returns_no_alarms(self):
        class WarningRuntime(_Runtime):
            def stop_pipeline(self):
                return ["点云保存未排空"]

            def poll(self):
                return {"alarms": ()}

        center = ControlCenter(WarningRuntime(), "complete_workpiece")
        center.start()
        center.stop()
        center.poll_once()
        self.assertIn("点云保存未排空", center.build_ui_state().alarms)
