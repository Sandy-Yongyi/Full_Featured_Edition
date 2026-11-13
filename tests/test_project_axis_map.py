import unittest
from types import SimpleNamespace
from typing import cast

from model.motionplan.MachineAxisMap import MACHINE_AXIS_MAP, get_axis_map, get_axis_position_limits
from model.motionplan.MotionFrameByFramePlanning import MotionFrameByFramePlanning
from model.MovingFrameData import ReceiveMovingFrameData, AXIS_LIST_COUNT
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

    def test_inout_devices_without_beams_return_safe_and_all_axes_control_master_gate(self):
        from control.PlcCommunicationProcess import PlcCommunicationProcess
        config = TomlLoader.load("model/tomls/MachineConfig1.toml")
        feedback = ReceiveMovingFrameData(Status=3)
        for axis in feedback.AxisList:
            axis.Pos = 100
        for index in (0, 2, 10, 12):
            feedback.AxisList[index].Pos = -100
        planner = MotionFrameByFramePlanning()
        proc = SimpleNamespace(machine_config=config, num_devices=6, runtime_machine_config={}, device_enable_mask=127, plc_data=feedback, last_operate_state=0,
                               device_returning_to_origin=dict.fromkeys(range(6), False), device_origin_complete={}, frame_queue_manager=SimpleNamespace(frame_stack={}),
                               mode_config={"spray_mode": 0}, lidar_status=0, raw_data_timeout_active=False, strategy_name="frame_by_frame", frame_by_frame_motion_planner=planner)
        frame = planner.build_moving_frame(proc)
        for index in (0, 2, 4, 6, 10, 12, 14, 16):
            expected = -100 if index in (0, 2, 10, 12) else 100
            self.assertEqual((expected, 0), (frame.AxisList[index].Pos, frame.AxisList[index].Status))
        for index in (1, 3, 5, 7, 11, 13, 15, 17):
            self.assertEqual((0, 0), (frame.AxisList[index].Pos, frame.AxisList[index].Status))
            feedback.AxisList[index].Pos = 0
        proc.device_enable_mask = 1
        frame = planner.build_moving_frame(proc)
        self.assertEqual(127, frame.Operate & 127)
        self.assertFalse(PlcCommunicationProcess._all_devices_at_safe(cast(PlcCommunicationProcess, proc)))
        for axis in feedback.AxisList:
            axis.Pos = 0
        frame = planner.build_moving_frame(proc)
        self.assertEqual(1, frame.Operate & 127)
        self.assertTrue(PlcCommunicationProcess._all_devices_at_safe(cast(PlcCommunicationProcess, proc)))
        proc.device_enable_mask = 0
        self.assertEqual(0, planner.build_moving_frame(proc).Operate & 127)

    def test_old_lidar_axes_are_not_reused_for_spray_axes(self):
        from model.motionplan.MachineAxisMap import LIDAR_AXIS_MAP
        self.assertEqual({}, LIDAR_AXIS_MAP)

    def test_inout_up_final_axis_output_enforces_relative_y_order_on_both_sides(self):
        from model.motionplan.MachineAxisMap import apply_to_axis_list
        from model.MovingFrameData import AxisData, create_axis_list

        for side, indices in (("left", (0, 2)), ("right", (10, 12))):
            with self.subTest(side=side):
                config = dict(type="inout_up", install_orietation=side, min_limit_pos=[-1600, 0], max_limit_pos=[0, 1200], max_limit_speed=[500, 500])
                commands = {"y1": AxisData(Pos=-1000, Speed=300), "y2": AxisData(Pos=-1200, Speed=300)}
                axes = create_axis_list()
                apply_to_axis_list(commands, config, axes)
                self.assertEqual((-1000, -1000), (axes[indices[0]].Pos, axes[indices[1]].Pos))
                self.assertEqual(-1200, commands["y2"].Pos)

    def test_inout_up_conflicting_y2_limit_is_rejected_without_partial_axis_write(self):
        from model.motionplan.MachineAxisMap import apply_to_axis_list
        from model.MovingFrameData import AxisData, create_axis_list

        config = dict(type="inout_up", install_orietation="left", min_limit_pos=[-1600, 0, -1600, 0], max_limit_pos=[0, 1200, -1100, 1200])
        commands = {"y1": AxisData(Pos=-1000, Speed=300), "y2": AxisData(Pos=-1200, Speed=300)}
        axes = create_axis_list()
        with self.assertRaises(ValueError):
            apply_to_axis_list(commands, config, axes)
        self.assertTrue(all(axis.Pos == 0 and axis.Speed == 0 and axis.Status == 0 for axis in axes))

    def test_inout_down_final_axis_output_preserves_positive_relative_y_order(self):
        from model.motionplan.MachineAxisMap import apply_to_axis_list
        from model.MovingFrameData import AxisData, create_axis_list

        for side, indices in (("left", (4, 6)), ("right", (14, 16))):
            config = dict(type="inout_down", install_orietation=side, min_limit_pos=[0, 0], max_limit_pos=[1600, 1200], max_limit_speed=[500, 500])
            commands = {"y1": AxisData(Pos=1000, Speed=300), "y2": AxisData(Pos=800, Speed=300)}
            axes = create_axis_list()
            apply_to_axis_list(commands, config, axes)
            self.assertEqual((800, 800), (axes[indices[0]].Pos, axes[indices[1]].Pos))

    def test_inout_down_y1_lower_limit_cannot_be_bypassed_to_match_y2(self):
        from model.motionplan.MachineAxisMap import apply_to_axis_list
        from model.MovingFrameData import AxisData, create_axis_list

        config = dict(type="inout_down", install_orietation="left", min_limit_pos=[900, 0, 0, 0], max_limit_pos=[1600, 1200, 1600, 1200])
        commands = {"y1": AxisData(Pos=1000, Speed=300), "y2": AxisData(Pos=800, Speed=300)}
        axes = create_axis_list()
        with self.assertRaises(ValueError):
            apply_to_axis_list(commands, config, axes)
        self.assertTrue(all(axis.Speed == 0 and axis.Status == 0 for axis in axes))
