import unittest
from types import SimpleNamespace

from model.motionplan.MachineAxisMap import MACHINE_AXIS_MAP, get_axis_map, get_axis_position_limits
from model.motionplan.MotionFrameByFramePlanning import MotionFrameByFramePlanning
from model.plc.MovingFrameData import ReceiveMovingFrameData, AXIS_LIST_COUNT
from model.utils.TomlLoader import TomlLoader


class ProjectAxisMapTests(unittest.TestCase):
    def test_six_devices_cover_all_twenty_axes_without_overlap(self):
        expected = {("inout_up", "left"): [0, 1, 2, 3], ("inout_down", "left"): [4, 5, 6, 7], ("H2D_XYservo", "left"): [8, 9],
                    ("inout_up", "right"): [10, 11, 12, 13], ("inout_down", "right"): [14, 15, 16, 17], ("H2D_XYservo", "right"): [18, 19]}
        actual = []
        for (kind, side), indices in expected.items():
            self.assertEqual(indices, list(get_axis_map(kind, side).values()))
            actual.extend(indices)
        self.assertEqual(list(range(AXIS_LIST_COUNT)), actual)
        self.assertEqual({"inout_up", "inout_down", "H2D_XYservo"}, set(MACHINE_AXIS_MAP))

    def test_four_axis_individual_limits_and_shared_limits(self):
        cfg = dict(type="inout_up", min_limit_pos=[0, 0], max_limit_pos=[600, 750, 1000, 750])
        self.assertEqual((0, 600), get_axis_position_limits(cfg, "y1"))
        self.assertEqual((0, 1000), get_axis_position_limits(cfg, "y2"))
        self.assertEqual((0, 750), get_axis_position_limits(cfg, "x2"))
        cfg["max_limit_pos"] = [500, 700]
        self.assertEqual((0, 500), get_axis_position_limits(cfg, "y2"))

    def test_inout_devices_only_return_safe_and_all_axes_control_master_gate(self):
        from control.PlcCommunicationProcess import PlcCommunicationProcess
        config = TomlLoader.load("model/tomls/MachineConfig1.toml")
        feedback = ReceiveMovingFrameData(Status=3)
        for axis in feedback.AxisList:
            axis.Pos = 100
        planner = MotionFrameByFramePlanning()
        proc = SimpleNamespace(machine_config=config, num_devices=6, runtime_machine_config={}, device_enable_mask=127, plc_data=feedback, last_operate_state=0,
                               device_returning_to_origin=dict.fromkeys(range(6), False), device_origin_complete={}, frame_queue_manager=SimpleNamespace(frame_stack={}),
                               mode_config={"spray_mode": 0}, lidar_status=0, raw_data_timeout_active=False, strategy_name="frame_by_frame", frame_by_frame_motion_planner=planner)
        frame = planner.build_moving_frame(proc)
        for index in (0, 2, 4, 6, 10, 12, 14, 16):
            self.assertEqual((100, 0), (frame.AxisList[index].Pos, frame.AxisList[index].Status))
        for index in (1, 3, 5, 7, 11, 13, 15, 17):
            self.assertEqual((0, 0), (frame.AxisList[index].Pos, frame.AxisList[index].Status))
            feedback.AxisList[index].Pos = 0
        proc.device_enable_mask = 1
        frame = planner.build_moving_frame(proc)
        self.assertEqual(127, frame.Operate & 127)
        self.assertFalse(PlcCommunicationProcess._all_devices_at_safe(proc))
        for axis in feedback.AxisList:
            axis.Pos = 0
        frame = planner.build_moving_frame(proc)
        self.assertEqual(1, frame.Operate & 127)
        self.assertTrue(PlcCommunicationProcess._all_devices_at_safe(proc))
        proc.device_enable_mask = 0
        self.assertEqual(0, planner.build_moving_frame(proc).Operate & 127)

    def test_old_lidar_axes_are_not_reused_for_spray_axes(self):
        from model.motionplan.MachineAxisMap import LIDAR_AXIS_MAP
        self.assertEqual({}, LIDAR_AXIS_MAP)
