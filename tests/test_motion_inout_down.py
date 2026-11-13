import unittest
from types import SimpleNamespace
from unittest.mock import patch

from acquisition_sdk._internal.formats.frame_by_frame.AxisFrameDataFormat import AxisData as CloudRow, AxisFrameData
from model.motionplan.MotionInOutDownPlanning import MotionInOutDownPlanning
from model.MovingFrameData import ReceiveMovingFrameData


class InOutDownTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(sn=1, type="inout_down", install_orietation="left", axis_type=["y1", "x1", "y2", "x2"], origin_pos=[1300, 1600], x_position=1000,
                           z_position=100, search_front_z_offset=50, search_after_z_offset=50, out_z_front_offset=20, out_z_after_offset=20,
                           in_down_y_offset=100, out_down_y_offset=150, out_front_x_offset=50, out_after_x_offset=100, x_pos_speed=400, x_recip_speed=200,
                           y_pos_speed=300, max_limit_speed=[500, 500], min_limit_pos=[0, 0], max_limit_pos=[1600, 1200], safe_pos=[0, 0])
        self.process = dict(y_threshold=10, z_threshold=10, beams_threshold=0.7, merge_beams=300, beams_width=200, beams_min_valid_frames=5,
                            safety_beam=80, beam_y_large_move_threshold=100)
        self.planner = MotionInOutDownPlanning(self.process, {"y_threshold": 10, "z_threshold": 10}, {"spray_pos_tolerance": 5})
        self.plc = ReceiveMovingFrameData(Status=3)
        self.queues = SimpleNamespace(frame_stack={"left": [], "right": []})
        self.put_beam()

    def put_beam(self, shift=0):
        self.queues.frame_stack["left"] = [AxisFrameData([CloudRow(y + shift, 1800, 1500) for y in (1800, 1810, 3000, 3010)]) for _ in range(25)]

    def put_surface(self):
        self.queues.frame_stack["left"] = [AxisFrameData([CloudRow(y, 1800, 1500) for y in range(1800, 3020, 10)]) for _ in range(25)]

    def move(self, **runtime):
        return self.planner.auto_inout_down_move(self.config, runtime, self.plc, self.queues)

    def ready(self, y1=350, y2=390, x=450):
        offset = 4 if self.config["install_orietation"] == "left" else 14
        for index, value in enumerate((y1, x, y2, x), offset):
            self.plc.AxisList[index].Pos = value

    def test_first_lower_beam_positions_positive_y_then_both_x_reciprocate(self):
        commands = self.move()
        self.assertEqual((350, 390, 450, 450), tuple(commands[name].Pos for name in ("y1", "y2", "x1", "x2")))
        self.assertEqual((1, 1), (commands["x1"].Status, commands["x2"].Status))
        self.assertEqual(450, self.move()["x2"].Pos)
        self.ready()
        commands = self.move()
        self.assertEqual((700, 700, 200), (commands["x1"].Pos, commands["x2"].Pos, commands["x2"].Speed))
        self.plc.AxisList[7].Pos = 700
        self.assertEqual(450, self.move()["x2"].Pos)

    def test_inner_y2_local_points_use_position_speed_and_keep_powder(self):
        self.queues.frame_stack["left"][10].FrameData.append(CloudRow(2000, 1800, 1500))
        self.move()
        self.ready()
        commands = self.move()
        self.assertEqual((700, 450, 400, 1), (commands["x1"].Pos, commands["x2"].Pos, commands["x2"].Speed, commands["x2"].Status))

    def test_outer_y1_holds_actual_feedback_when_bottom_is_below_origin_after_beam_guard(self):
        self.queues.frame_stack["left"][10].FrameData.append(CloudRow(1100, 1800, 1500))
        self.plc.AxisList[4].Pos = 123
        commands = self.move()
        self.assertEqual((123, 450, 1), (commands["y1"].Pos, commands["x1"].Pos, commands["x1"].Status))

    def test_two_height_guards_are_independent_and_origin_equality_is_allowed(self):
        self.config["origin_pos"] = [1600, 1600]
        commands = self.move()
        self.assertEqual((0, 0, 0), (commands["y1"].Pos, commands["x1"].Pos, commands["x1"].Status))
        self.assertEqual(1, commands["x2"].Status)
        self.config["origin_pos"] = [1300, 2000]
        commands = self.move()
        self.assertEqual((0, 0), (commands["x2"].Pos, commands["x2"].Status))
        self.assertEqual(1, commands["x1"].Status)
        self.config["origin_pos"] = [1570, 1990]
        commands = self.move()
        self.assertEqual((1, 1), (commands["x1"].Status, commands["x2"].Status))

    def test_small_changes_continue_and_large_changes_wait_at_x_min_until_y_arrives(self):
        self.move()
        self.ready()
        self.move()
        self.plc.AxisList[7].Pos = 550
        self.put_beam(100)
        self.assertEqual(700, self.move()["x2"].Pos)
        self.plc.AxisList[5].Pos = 550
        self.put_beam(110)
        for _ in range(2):
            commands = self.move()
            self.assertEqual((390, 450), (commands["y2"].Pos, commands["x2"].Pos))
        self.plc.AxisList[7].Pos = 450
        commands = self.move()
        self.assertEqual((500, 450), (commands["y2"].Pos, commands["x2"].Pos))
        self.plc.AxisList[6].Pos = 500
        self.assertEqual(700, self.move()["x2"].Pos)

    def test_no_lower_beam_surface_sprays_outer_and_parks_inner_at_max_after_x_safe(self):
        self.put_surface()
        commands = self.move()
        self.assertEqual((350, 1600, 0, 0), (commands["y1"].Pos, commands["y2"].Pos, commands["x2"].Pos, commands["x2"].Status))
        self.ready(y2=1600, x=0)
        self.plc.AxisList[5].Pos = 450
        self.assertEqual((700, 1), (self.move()["x1"].Pos, self.move()["x1"].Status))
        self.plc.AxisList[6].Pos = 400
        self.plc.AxisList[7].Pos = 500
        commands = self.move()
        self.assertEqual((400, 0, 0), (commands["y2"].Pos, commands["x2"].Pos, commands["x2"].Status))

    def test_no_beam_fallback_preserves_outer_motion_and_restarts_inner_on_reappearance(self):
        self.move()
        self.ready()
        self.move()
        self.plc.AxisList[5].Pos = 550
        self.put_surface()
        commands = self.move()
        self.assertEqual((700, 1, 0), (commands["x1"].Pos, commands["x1"].Status, commands["x2"].Status))
        self.put_beam()
        self.plc.AxisList[6].Pos = 1600
        self.assertEqual((390, 450), (self.move()["y2"].Pos, self.move()["x2"].Pos))

    def test_no_lower_geometry_or_missing_feedback_never_fires(self):
        self.queues.frame_stack["left"] = []
        self.assertTrue(all(axis.Pos == 0 and axis.Status == 0 for axis in self.move().values()))
        self.put_beam()
        for index in range(8, 13):
            self.queues.frame_stack["left"][index] = AxisFrameData([CloudRow(3000, 1800, 1500)])
        self.assertTrue(all(axis.Status == 0 for axis in self.move().values()))
        self.put_beam()
        self.plc.AxisList = []
        self.assertTrue(all(axis.Speed == 0 and axis.Status == 0 for axis in self.move().values()))

    def test_right_side_and_runtime_offsets_do_not_use_left_feedback(self):
        self.config.update(sn=4, install_orietation="right")
        self.assertTrue(all(axis.Status == 0 for axis in self.move().values()))
        self.queues.frame_stack["right"] = self.queues.frame_stack["left"]
        commands = self.move(out_down_y_offset=100, in_down_y_offset=50, out_front_x_offset=100)
        self.assertEqual((340, 340, 400), (commands["y1"].Pos, commands["y2"].Pos, commands["x2"].Pos))

    def test_y1_is_lowered_to_y2_and_arrival_uses_corrected_y1_target(self):
        self.config["origin_pos"] = [1000, 1800]
        commands = self.move()
        self.assertEqual((190, 190), (commands["y1"].Pos, commands["y2"].Pos))
        self.ready(y1=190, y2=190)
        commands = self.move()
        self.assertEqual((700, 700), (commands["x1"].Pos, commands["x2"].Pos))

    def test_position_speed_limits_and_zero_speed_powder(self):
        self.config.update(max_limit_pos=[300, 500], max_limit_speed=[150, 250])
        commands = self.move()
        self.assertEqual((300, 300, 150, 250), (commands["y1"].Pos, commands["y2"].Pos, commands["y1"].Speed, commands["x2"].Speed))
        commands = self.move(x_pos_speed=0)
        self.assertEqual((0, 0), (commands["x1"].Status, commands["x2"].Status))


class InOutDownDispatchTests(unittest.TestCase):
    def test_configured_origins_enabled_only_dispatch_and_close_reset(self):
        from model.motionplan.MotionFrameByFramePlanning import MotionFrameByFramePlanning
        from model.utils.TomlLoader import TomlLoader

        config = TomlLoader.load("model/tomls/MachineConfig1.toml")
        self.assertEqual([1300, 1600], config["1"]["origin_pos"])
        self.assertEqual([1300, 1600], config["4"]["origin_pos"])
        planner = MotionFrameByFramePlanning()
        stacks = {side: [AxisFrameData([CloudRow(y, 1800, 1500) for y in (1800, 1810, 3000, 3010)]) for _ in range(400)] for side in ("left", "right")}
        proc = SimpleNamespace(machine_config=config, num_devices=6, runtime_machine_config={}, device_enable_mask=1, plc_data=ReceiveMovingFrameData(Status=3),
                               last_operate_state=0, device_returning_to_origin=dict.fromkeys(range(6), False), device_origin_complete={},
                               frame_queue_manager=SimpleNamespace(frame_stack=stacks), mode_config={"spray_mode": 0}, lidar_status=0, raw_data_timeout_active=False)
        with patch.object(planner.inout_down_planner, "auto_inout_down_move", wraps=planner.inout_down_planner.auto_inout_down_move) as move:
            planner.build_moving_frame(proc)
            move.assert_not_called()
            proc.device_enable_mask = 1 | (1 << 2) | (1 << 5)
            output = planner.build_moving_frame(proc)
            self.assertEqual(2, move.call_count)
            self.assertEqual((1, 1, 1, 1), tuple(output.AxisList[i].Status for i in (5, 7, 15, 17)))
            proc.device_enable_mask = 1
            output = planner.build_moving_frame(proc)
            self.assertEqual(2, move.call_count)
            self.assertTrue(all(output.AxisList[i].Status == 0 for i in (5, 7, 15, 17)))
            self.assertEqual({}, planner.inout_down_planner._states)


if __name__ == "__main__":
    unittest.main()
