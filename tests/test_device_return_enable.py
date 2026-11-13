import unittest
from types import SimpleNamespace

from model.MovingFrameData import ReceiveMovingFrameData
from model.motionplan.MotionFrameByFramePlanning import MotionFrameByFramePlanning
from model.motionplan.MotionCompleteWorkpiecePlanning import MotionCompleteWorkpiecePlanning


class ReturnEnableTests(unittest.TestCase):
    def make_proc(self):
        cfg = dict(sn=2, type="H2D_XYservo", install_orietation="left", axis_type=["y", "x"], safe_pos=[0, 0], min_limit_pos=[0, 0], max_limit_pos=[600, 750],
                   max_limit_speed=[300, 500], x_pos_speed=200, y_pos_speed=200, x_position=0, origin_pos=[0], spray_num=3, spray_radius=500, z_position=2000)
        feedback = ReceiveMovingFrameData(Status=1, Operate=127)
        feedback.AxisList[8].Pos = 100
        feedback.AxisList[9].Pos = 100
        queues = SimpleNamespace(frame_stack={"left": []}, queues={"left": {2: []}})
        return SimpleNamespace(machine_config={"2": cfg}, runtime_machine_config={}, num_devices=3, device_enable_mask=9, plc_data=feedback, last_operate_state=0,
                               device_returning_to_origin={2: False}, device_origin_complete={2: False}, frame_queue_manager=queues, mode_config={"spray_mode": 0},
                               lidar_status=0, raw_data_timeout_active=False)

    def test_closing_request_keeps_enable_until_both_axes_reach_safe(self):
        for planner_type in (MotionFrameByFramePlanning, MotionCompleteWorkpiecePlanning):
            for closed_mask in (1, 0):
                with self.subTest(planner=planner_type.__name__, closed_mask=closed_mask):
                    proc = self.make_proc()
                    planner = planner_type()
                    opened = planner.build_moving_frame(proc)
                    self.assertEqual(9, opened.Operate & 0x7F)
                    proc.device_enable_mask = closed_mask
                    returning = planner.build_moving_frame(proc)
                    self.assertEqual(9, returning.Operate & 0x7F)
                    self.assertEqual(0, returning.AxisList[9].Status)
                    proc.plc_data.AxisList[9].Pos = 0
                    only_x_ready = planner.build_moving_frame(proc)
                    self.assertEqual(9, only_x_ready.Operate & 0x7F)
                    proc.plc_data.AxisList[8].Pos = 0
                    complete = planner.build_moving_frame(proc)
                    self.assertEqual(closed_mask, complete.Operate & 0x7F)
                    self.assertFalse(proc.device_returning_to_origin[2])
                    self.assertEqual(closed_mask, planner.build_moving_frame(proc).Operate & 0x7F)

    def test_never_requested_devices_are_not_enabled_at_startup(self):
        for planner_type in (MotionFrameByFramePlanning, MotionCompleteWorkpiecePlanning):
            proc = self.make_proc()
            proc.device_enable_mask = 0
            frame = planner_type().build_moving_frame(proc)
            self.assertEqual(0, frame.Operate)
            self.assertEqual(0, frame.AxisList[9].Status)

    def test_reopen_during_return_finishes_return_before_resuming(self):
        proc = self.make_proc()
        planner = MotionFrameByFramePlanning()
        planner.build_moving_frame(proc)
        proc.device_enable_mask = 1
        planner.build_moving_frame(proc)
        proc.device_enable_mask = 9
        frame = planner.build_moving_frame(proc)
        self.assertEqual(0, frame.AxisList[9].Status)
        self.assertTrue(proc.device_returning_to_origin[2])
        self.assertEqual(9, frame.Operate)

    def test_missing_axis_feedback_never_confirms_safe_return(self):
        proc = self.make_proc()
        proc.device_enable_mask = 0
        proc.device_returning_to_origin[2] = True
        proc.plc_data.AxisList = []
        frame = MotionFrameByFramePlanning().build_moving_frame(proc)
        self.assertEqual(9, frame.Operate)
        self.assertFalse(proc.device_origin_complete[2])

    def test_runtime_ui_state_keeps_request_not_delayed_plc_mask(self):
        import time
        from control.PipelineRuntime import PipelineRuntime
        runtime = PipelineRuntime()
        runtime.plc_handler = SimpleNamespace(is_alive=lambda: True)
        runtime._ui_feedback["plc"] = {"connected": True, "timestamp": time.monotonic(), "device_enable_mask": 9}
        runtime.send_control({"device_enable_mask": 1})
        self.assertEqual(1, runtime.poll()["device_enable_mask"])
        runtime.plc_handler = None
        self.assertEqual(0, runtime.poll()["device_enable_mask"])
