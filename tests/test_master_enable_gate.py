import queue
import unittest
from types import SimpleNamespace

from model.motionplan.motionutil.DeviceEnableHelper import validate_enable_transition


class MasterEnableGateTests(unittest.TestCase):
    def test_master_transition_requires_auto_and_safe_closed_devices(self):
        for auto in (False, None):
            with self.assertRaises(ValueError):
                validate_enable_transition(0, 1, auto, True)
        validate_enable_transition(0, 1, True, False)
        with self.assertRaises(ValueError):
            validate_enable_transition(9, 0, True, True)
        with self.assertRaises(ValueError):
            validate_enable_transition(1, 0, True, False)
        validate_enable_transition(1, 0, False, True)
        validate_enable_transition(9, 1, False, False)

    def test_white_hint_tracks_mode_and_waits_for_safe_return(self):
        from dataclasses import replace
        from PyQt6.QtWidgets import QApplication
        from model.telemetry.UiState import UiState, DeviceState
        from view.qt.pages import DeviceControlPage
        app = QApplication.instance() or QApplication([])
        self.addCleanup(app.processEvents)
        sent = []
        page = DeviceControlPage(SimpleNamespace(set_device_enable_mask=sent.append))
        state = UiState(strategy_name="frame_by_frame", running=True, devices=(DeviceState("PLC", True),), pc_auto_mode=False)
        page.apply_state(state)
        self.assertFalse(page.enable_button.isEnabled())
        self.assertEqual("PLC点动模式无法使能", page.enable_hint.text())
        page.enable_button.click()
        self.assertEqual([], sent)
        page.apply_state(replace(state, pc_auto_mode=True))
        self.assertTrue(page.enable_button.isEnabled())
        self.assertEqual("PC自动模式可开启使能", page.enable_hint.text())
        page.enable_button.click()
        self.assertEqual(1, sent[-1])
        self.assertFalse(page.enable_button.isEnabled())
        self.assertEqual("设备未全部关闭并安全回位，无法关闭使能", page.enable_hint.text())
        page.apply_state(replace(state, pc_auto_mode=True, device_enable_mask=1, all_devices_safe=True))
        self.assertTrue(page.enable_button.isEnabled())
        page.enable_button.click()
        self.assertEqual(0, sent[-1])
        self.assertIn("#ffffff", page.enable_hint.styleSheet())
        self.assertTrue(page.enable_hint.wordWrap())
        self.assertFalse(hasattr(page, "result"))

    def test_worker_checks_live_feedback_not_only_ui_permission(self):
        from control.PlcCommunicationProcess import PlcCommunicationProcess
        p = PlcCommunicationProcess.__new__(PlcCommunicationProcess)
        p.control_queue = queue.Queue()
        p.device_enable_mask = 0
        p.plc_data = SimpleNamespace(Status=1)
        p._all_devices_at_safe = lambda: True
        p.control_queue.put({"device_enable_mask": 1})
        p._update_enable_value()
        self.assertEqual(0, p.device_enable_mask)
        p.plc_data.Status = 3
        p.control_queue.put({"device_enable_mask": 1})
        p._update_enable_value()
        self.assertEqual(1, p.device_enable_mask)
        p._all_devices_at_safe = lambda: False
        p.control_queue.put({"device_enable_mask": 0})
        p._update_enable_value()
        self.assertEqual(1, p.device_enable_mask)

    def test_safe_feedback_checks_every_axis_and_rejects_unknown_mapping(self):
        from control.PlcCommunicationProcess import PlcCommunicationProcess
        from model.motionplan.MotionToTarget import MotionToTarget
        from model.MovingFrameData import ReceiveMovingFrameData
        p = PlcCommunicationProcess.__new__(PlcCommunicationProcess)
        p.strategy_name = "frame_by_frame"
        p.frame_by_frame_motion_planner = SimpleNamespace(motion_to_target=MotionToTarget())
        p.plc_data = ReceiveMovingFrameData()
        p.machine_config = {"2": dict(type="H2D_XYservo", install_orietation="left", axis_type=["y", "x"], safe_pos=[0, 0])}
        self.assertTrue(p._all_devices_at_safe())
        p.plc_data.AxisList[8].Pos = 100
        self.assertFalse(p._all_devices_at_safe())
        p.plc_data.AxisList[8].Pos = 0
        p.machine_config["2"]["type"] = "unknown"
        self.assertFalse(p._all_devices_at_safe())

    def test_rejected_latest_request_restores_button_request_but_stale_reply_does_not(self):
        import time
        from control.PipelineRuntime import PipelineRuntime
        runtime = PipelineRuntime()
        runtime.ui_status_queue = queue.Queue()
        runtime.plc_handler = SimpleNamespace(is_alive=lambda: True)
        runtime.send_control({"device_enable_mask": 1})
        old_id = runtime._enable_request_id
        runtime.send_control({"device_enable_mask": 0})
        message = dict(source="plc", timestamp=time.monotonic(), connected=True, plc_status=3, device_enable_error="not safe", device_enable_mask=1)
        runtime.ui_status_queue.put({**message, "device_enable_request_id": old_id})
        self.assertEqual(0, runtime.poll()["device_enable_mask"])
        runtime.ui_status_queue.put({**message, "device_enable_request_id": runtime._enable_request_id})
        self.assertEqual(1, runtime.poll()["device_enable_mask"])
