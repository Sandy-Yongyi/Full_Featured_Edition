import unittest
from types import SimpleNamespace

from acquisition_sdk._internal.formats.frame_by_frame.AxisFrameDataFormat import AxisData as CloudRow, AxisFrameData
from model.motionplan.MotionInOutUpPlanning import MotionInOutUpPlanning
from model.MovingFrameData import ReceiveMovingFrameData


class InOutUpTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(sn=0, type="inout_up", install_orietation="left", axis_type=["y1", "x1", "y2", "x2"], origin_pos=[3000, 3300], x_position=1000,
                           z_position=100, search_front_z_offset=50, search_after_z_offset=50, out_z_front_offset=20, out_z_after_offset=20,
                           in_up_y_offset=100, out_up_y_offset=150, out_front_x_offset=50, out_after_x_offset=100, x_pos_speed=400, x_recip_speed=200,
                           y_pos_speed=300, max_limit_speed=[500, 500], min_limit_pos=[-1600, 0], max_limit_pos=[0, 1200], safe_pos=[0, 0])
        self.process = dict(y_threshold=10, z_threshold=10, beams_threshold=0.7, merge_beams=300, beams_width=200, beams_min_valid_frames=5,
                            safety_beam=80, beam_y_large_move_threshold=100)
        self.planner = MotionInOutUpPlanning(self.process, {"y_threshold": 10, "z_threshold": 10}, {"spray_pos_tolerance": 5})
        self.plc = ReceiveMovingFrameData(Status=3)
        self.queues = SimpleNamespace(frame_stack={"left": [], "right": []})
        self.put_beam()

    def put_beam(self, shift=0):
        self.queues.frame_stack["left"] = [AxisFrameData([CloudRow(y + shift, 1800, 1500) for y in (1000, 1010, 2400, 2410)]) for _ in range(25)]

    def move(self, **runtime):
        return self.planner.auto_inout_up_move(self.config, runtime, self.plc, self.queues)

    def ready(self, y1=-780, y2=-740, x=450):
        for index, value in ((0, y1), (1, x), (2, y2), (3, x)):
            self.plc.AxisList[index].Pos = value

    def test_first_beam_moves_y_and_x_min_in_parallel_then_reciprocates(self):
        commands = self.move()
        self.assertEqual((-780, -740, 450, 450), tuple(commands[name].Pos for name in ("y1", "y2", "x1", "x2")))
        self.assertEqual((1, 1), (commands["x1"].Status, commands["x2"].Status))
        self.assertEqual(400, commands["x1"].Speed)
        commands = self.move()
        self.assertEqual(450, commands["x1"].Pos)
        self.ready()
        commands = self.move()
        self.assertEqual((700, 200), (commands["x1"].Pos, commands["x1"].Speed))
        self.plc.AxisList[1].Pos = 700
        self.assertEqual(450, self.move()["x1"].Pos)

    def test_small_y_changes_do_not_interrupt_reciprocation_and_100_is_not_large(self):
        self.move()
        self.ready()
        self.move()
        self.plc.AxisList[1].Pos = 550
        self.put_beam(100)
        commands = self.move()
        self.assertEqual((-680, 700, 200, 1), (commands["y1"].Pos, commands["x1"].Pos, commands["x1"].Speed, commands["x1"].Status))

    def test_large_change_waits_for_x_min_then_y_and_does_not_skip_wait_next_cycle(self):
        self.move()
        self.ready()
        self.move()
        self.plc.AxisList[1].Pos = 600
        self.put_beam(110)
        for _ in range(2):
            commands = self.move()
            self.assertEqual((-780, 450), (commands["y1"].Pos, commands["x1"].Pos))
        self.plc.AxisList[1].Pos = 450
        commands = self.move()
        self.assertEqual((-670, 450), (commands["y1"].Pos, commands["x1"].Pos))
        self.assertEqual(450, self.move()["x1"].Pos)
        self.plc.AxisList[0].Pos = -670
        self.assertEqual(700, self.move()["x1"].Pos)

    def test_local_points_lock_x1_at_min_but_keep_gun_on(self):
        rows = self.queues.frame_stack["left"][10].FrameData
        rows.append(CloudRow(2200, 1800, 1500))
        self.move()
        self.ready()
        commands = self.move()
        self.assertEqual((450, 400, 1), (commands["x1"].Pos, commands["x1"].Speed, commands["x1"].Status))
        self.assertEqual(700, commands["x2"].Pos)

    def test_y1_and_y2_height_guards_are_independent(self):
        self.config["origin_pos"] = [2200, 3300]
        commands = self.move()
        self.assertEqual((0, 0, 0), (commands["y1"].Pos, commands["x1"].Pos, commands["x1"].Status))
        self.assertEqual(1, commands["x2"].Status)
        self.config["origin_pos"] = [3000, 2600]
        commands = self.move()
        self.assertEqual((0, 0, 0), (commands["y2"].Pos, commands["x2"].Pos, commands["x2"].Status))
        self.assertEqual(1, commands["x1"].Status)

    def test_height_equal_to_origin_is_allowed_and_y2_actual_top_equal_holds_feedback(self):
        self.config["origin_pos"] = [2220, 2640]
        commands = self.move()
        self.assertEqual((0, 1), (commands["y1"].Pos, commands["x1"].Status))
        self.assertEqual(1, commands["x2"].Status)
        self.config["origin_pos"] = [3000, 3300]
        self.queues.frame_stack["left"][10].FrameData.append(CloudRow(3150, 1800, 1500))
        self.plc.AxisList[2].Pos = -125
        self.assertEqual(-125, self.move()["y2"].Pos)

    def test_safety_distance_and_large_change_threshold_are_configurable(self):
        self.process.update(safety_beam=100, beam_y_large_move_threshold=150)
        self.planner = MotionInOutUpPlanning(self.process, {"y_threshold": 10, "z_threshold": 10}, {"spray_pos_tolerance": 5})
        self.move()
        self.ready(y1=-800)
        self.move()
        self.plc.AxisList[1].Pos = 550
        self.put_beam(110)
        commands = self.move()
        self.assertEqual((-690, 700), (commands["y1"].Pos, commands["x1"].Pos))

    def test_beam_search_and_motion_search_have_independent_windows(self):
        self.config.update(search_front_z_offset=50, search_after_z_offset=50, out_z_front_offset=10, out_z_after_offset=10)
        self.queues.frame_stack["left"][8] = AxisFrameData([CloudRow(3000, 2200, 500)])
        commands = self.move()
        self.assertEqual((450, -740), (commands["x1"].Pos, commands["y2"].Pos))

    def test_limited_negative_y_target_and_zero_speed_never_fire(self):
        self.config["min_limit_pos"] = [-500, 0]
        commands = self.move()
        self.assertEqual((-500, -500), (commands["y1"].Pos, commands["y2"].Pos))
        commands = self.move(x_pos_speed=0)
        self.assertEqual((0, 0), (commands["x1"].Status, commands["x2"].Status))

    def test_y2_holds_feedback_when_top_surface_exceeds_origin_after_beam_guard(self):
        self.queues.frame_stack["left"][10].FrameData.append(CloudRow(3200, 1800, 1500))
        self.plc.AxisList[2].Pos = -120
        commands = self.move()
        self.assertEqual((-120, 450, 1), (commands["y2"].Pos, commands["x2"].Pos, commands["x2"].Status))

    def test_no_beam_returns_safe_and_reappearance_requires_initial_positioning(self):
        self.move()
        self.ready()
        self.move()
        self.queues.frame_stack["left"] = []
        commands = self.move()
        self.assertEqual((0, 0, 0, 0), tuple(commands[name].Status for name in ("y1", "x1", "y2", "x2")))
        self.assertEqual((0, 0), (commands["x1"].Pos, commands["x2"].Pos))
        self.put_beam()
        self.plc.AxisList[0].Pos = 0
        commands = self.move()
        self.assertEqual((-780, 450), (commands["y1"].Pos, commands["x1"].Pos))

    def put_surface_without_beam(self, height=2410):
        # 一个宽面超过梁厚限制，仍保留完整的上半区点云用于顶部喷涂。
        self.queues.frame_stack["left"] = [AxisFrameData([CloudRow(y, 1800, 1500) for y in range(1000, height + 1, 10)]) for _ in range(25)]

    def test_no_beam_with_upper_points_parks_y1_and_reciprocates_x2_after_y2_arrives(self):
        self.put_surface_without_beam()
        commands = self.move()
        self.assertEqual((-1600, 0, 0), (commands["y1"].Pos, commands["x1"].Pos, commands["x1"].Status))
        self.assertEqual((-740, 450, 1), (commands["y2"].Pos, commands["x2"].Pos, commands["x2"].Status))
        self.plc.AxisList[2].Pos = -740
        self.plc.AxisList[3].Pos = 450
        commands = self.move()
        self.assertEqual((700, 200, 1), (commands["x2"].Pos, commands["x2"].Speed, commands["x2"].Status))

    def test_no_beam_y1_waits_for_x1_safe_before_moving_to_min_limit(self):
        self.put_surface_without_beam()
        self.plc.AxisList[0].Pos = -500
        self.plc.AxisList[1].Pos = 450
        commands = self.move()
        self.assertEqual((-500, 0, 0), (commands["y1"].Pos, commands["x1"].Pos, commands["x1"].Status))
        self.assertGreaterEqual(commands["y2"].Pos, -500)
        self.plc.AxisList[1].Pos = 0
        self.assertEqual(-1600, self.move()["y1"].Pos)

    def test_no_beam_top_targets_are_clamped_to_reachable_y_and_still_reciprocate(self):
        for height, limit, expected_y in ((3500, -1600, 0), (2410, -500, -500)):
            with self.subTest(height=height):
                self.planner.reset_motion_state()
                self.put_surface_without_beam(height)
                self.config["min_limit_pos"] = [limit, 0]
                commands = self.move()
                self.assertEqual(expected_y, commands["y2"].Pos)
                self.plc.AxisList[2].Pos = expected_y
                self.plc.AxisList[3].Pos = 450
                commands = self.move()
                self.assertEqual((700, 1), (commands["x2"].Pos, commands["x2"].Status))

    def test_no_beam_no_upper_points_in_motion_window_returns_both_groups_safe(self):
        self.put_surface_without_beam()
        self.queues.frame_stack["left"][8:13] = [AxisFrameData([CloudRow(1000, 1800, 1500)]) for _ in range(5)]
        commands = self.move()
        self.assertTrue(all(axis.Pos == 0 and axis.Status == 0 for axis in commands.values()))

    def test_no_beam_empty_search_window_still_uses_upper_motion_points_on_correct_side(self):
        self.put_surface_without_beam()
        self.config.update(search_front_z_offset=0, search_after_z_offset=0, sn=3, install_orietation="right")
        self.queues.frame_stack["left"][10] = AxisFrameData([])
        self.assertTrue(all(axis.Status == 0 for axis in self.move().values()))
        self.queues.frame_stack["right"] = self.queues.frame_stack["left"]
        commands = self.move()
        self.assertEqual((-1600, -740, 450, 1), (commands["y1"].Pos, commands["y2"].Pos, commands["x2"].Pos, commands["x2"].Status))

    def test_no_beam_upper_rows_without_valid_x_never_fire(self):
        self.queues.frame_stack["left"] = [AxisFrameData([CloudRow(y, 0, 0) for y in range(1000, 2420, 10)]) for _ in range(25)]
        commands = self.move()
        self.assertTrue(all(axis.Pos == 0 and axis.Status == 0 for axis in commands.values()))

    def test_no_beam_fallback_preserves_top_reciprocation_and_restarts_inner_on_beam_return(self):
        self.move()
        self.ready()
        self.move()
        self.plc.AxisList[3].Pos = 550
        self.put_surface_without_beam()
        commands = self.move()
        self.assertEqual((700, 1, 0), (commands["x2"].Pos, commands["x2"].Status, commands["x1"].Status))
        self.put_beam()
        self.plc.AxisList[0].Pos = -1600
        commands = self.move()
        self.assertEqual((-780, 450, 1), (commands["y1"].Pos, commands["x1"].Pos, commands["x1"].Status))

    def test_right_side_and_runtime_offsets(self):
        self.config.update(sn=3, install_orietation="right")
        self.assertTrue(all(axis.Status == 0 for axis in self.move().values()))
        self.queues.frame_stack["right"] = self.queues.frame_stack["left"]
        self.plc.AxisList[10].Pos = -500
        commands = self.move(in_up_y_offset=50, out_front_x_offset=100)
        self.assertEqual((-730, 400), (commands["y1"].Pos, commands["x1"].Pos))

    def test_no_movement_geometry_or_missing_feedback_never_fires(self):
        self.config["out_z_front_offset"] = 0
        self.config["out_z_after_offset"] = 0
        self.queues.frame_stack["left"][10] = AxisFrameData([])
        self.assertTrue(all(axis.Status == 0 for axis in self.move().values()))
        self.put_beam()
        self.plc.AxisList = []
        self.assertTrue(all(axis.Status == 0 for axis in self.move().values()))

    def test_position_and_speed_limits_and_reset(self):
        self.config.update(max_limit_pos=[0, 500], max_limit_speed=[200, 250])
        commands = self.move()
        self.assertEqual((200, 250), (commands["y1"].Speed, commands["x1"].Speed))
        self.ready()
        commands = self.move()
        self.assertEqual(500, commands["x1"].Pos)
        self.planner.reset_motion_state(0)
        self.plc.AxisList[0].Pos = -750
        self.assertEqual(450, self.move()["x1"].Pos)

    def test_y2_cannot_go_below_y1_and_reciprocation_waits_for_corrected_target(self):
        self.config["origin_pos"] = [3220, 3760]
        commands = self.move()
        self.assertEqual((-1000, -1000), (commands["y1"].Pos, commands["y2"].Pos))
        self.ready(y1=-1000, y2=-1000)
        commands = self.move()
        self.assertEqual((700, 200, 1), (commands["x2"].Pos, commands["x2"].Speed, commands["x2"].Status))

    def test_y2_order_is_preserved_during_large_move_waiting_and_without_beam(self):
        self.move()
        self.ready()
        self.move()
        self.config["origin_pos"] = [3220, 3760]
        self.plc.AxisList[0].Pos = -1000
        self.plc.AxisList[2].Pos = -1200
        self.plc.AxisList[3].Pos = 600
        commands = self.move()
        self.assertGreaterEqual(commands["y2"].Pos, commands["y1"].Pos)
        self.queues.frame_stack["left"] = []
        commands = self.move()
        self.assertGreaterEqual(commands["y2"].Pos, commands["y1"].Pos)
        self.assertTrue(all(axis.Status == 0 for axis in commands.values()))


if __name__ == "__main__":
    unittest.main()
