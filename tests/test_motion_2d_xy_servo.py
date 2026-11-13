import unittest
from types import SimpleNamespace

from acquisition_sdk._internal.formats.frame_by_frame.AxisFrameDataFormat import AxisData as CloudRow, AxisFrameData
from model.motionplan.Motion2DXYServoFramePlanning import Motion2DXYServoFramePlanning
from model.MovingFrameData import ReceiveMovingFrameData


class XYServoTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(sn=2, type="H2D_XYservo", install_orietation="left", z_position=2000, x_position=0, origin_pos=[0], spray_num=3, spray_radius=500, axis_type=["y", "x"],
                           out_z_front_offset=50, out_z_after_offset=50, out_up_y_offset=100, out_down_y_offset=50, out_front_x_offset=50, x_pos_speed=400,
                           y_recip_speed=200, min_limit_pos=[0, 0], max_limit_pos=[600, 750], max_limit_speed=[300, 500], safe_pos=[0, 0])
        self.frames = [AxisFrameData() for _ in range(400)]
        self.queues = SimpleNamespace(frame_stack={"left": self.frames, "right": self.frames})
        self.plc = ReceiveMovingFrameData()
        self.planner = Motion2DXYServoFramePlanning(read_data_cfg={"z_threshold": 10}, spray_cfg={"spray_pos_tolerance": 5})

    def put(self, index, y=200, x=500):
        self.frames[index] = AxisFrameData([CloudRow(y, x + 100, x)])

    def test_geometry_and_independent_gun_bands(self):
        for index, expected in ((150, 1), (200, 2), (250, 4), (175, 3), (225, 6)):
            with self.subTest(index=index):
                self.frames[:] = [AxisFrameData() for _ in self.frames]
                self.put(index)
                self.assertEqual(expected, self.planner.scan_geometry(self.config, {}, self.queues).gun_mask)

    def test_motion_window_offsets_and_gun_window_are_independent(self):
        self.put(125, 100, 400)
        geometry = self.planner.scan_geometry(self.config, {}, self.queues)
        self.assertEqual(1, geometry.gun_mask)
        self.assertIsNone(geometry.x_min)
        self.put(145, 200, 500)
        self.put(255, 400, 450)
        self.put(144, 10, 10)
        self.put(256, 1000, 1)
        geometry = self.planner.scan_geometry(self.config, {}, self.queues)
        self.assertEqual((200, 400, 450), (geometry.y_min, geometry.y_max, geometry.x_min))

    def test_y_reciprocates_and_x_positions_with_runtime_offsets(self):
        self.put(200, 200, 500)
        self.put(210, 400, 550)
        commands, mask = self.planner.auto_xy_servo_move(self.config, {}, self.plc, self.queues)
        self.assertEqual((500, 200, 450, 400), (commands["y"].Pos, commands["y"].Speed, commands["x"].Pos, commands["x"].Speed))
        self.assertEqual(2, mask)
        self.assertEqual(2, commands["x"].Status)
        self.plc.AxisList[8].Pos = 500
        commands, _ = self.planner.auto_xy_servo_move(self.config, {}, self.plc, self.queues)
        self.assertEqual(150, commands["y"].Pos)
        self.plc.AxisList[8].Pos = 150
        commands, _ = self.planner.auto_xy_servo_move(self.config, {"out_front_x_offset": 100}, self.plc, self.queues)
        self.assertEqual((500, 400), (commands["y"].Pos, commands["x"].Pos))

    def test_position_and_speed_limits_and_right_side_mapping(self):
        self.config.update(sn=5, install_orietation="right", x_pos_speed=1000, y_recip_speed=1000, out_up_y_offset=1000, out_down_y_offset=1000)
        self.put(200, 200, 2000)
        self.plc.AxisList[18].Pos = 600
        commands, _ = self.planner.auto_xy_servo_move(self.config, {}, self.plc, self.queues)
        self.assertEqual((0, 300, 750, 500), (commands["y"].Pos, commands["y"].Speed, commands["x"].Pos, commands["x"].Speed))

    def test_invalid_configuration_and_all_zero_data_never_fire(self):
        self.frames[200] = AxisFrameData([CloudRow(0, 0, 0)])
        self.assertEqual(0, self.planner.scan_geometry(self.config, {}, self.queues).gun_mask)
        self.config["spray_num"] = 2
        commands, mask = self.planner.auto_xy_servo_move(self.config, {}, self.plc, self.queues)
        self.assertEqual(0, mask)
        self.assertTrue(all(axis.Speed == 0 and axis.Status == 0 for axis in commands.values()))

    def test_outside_queue_does_not_reuse_edge_frame(self):
        self.put(399)
        self.config["z_position"] = 10000
        geometry = self.planner.scan_geometry(self.config, {}, self.queues)
        self.assertEqual(0, geometry.gun_mask)
        self.assertIsNone(geometry.y_min)

    def test_machine_xy_positions_are_subtracted_before_limits(self):
        self.put(200, 200, 500)
        self.put(210, 400, 550)
        self.config.update(origin_pos=[100], x_position=100)
        commands, _ = self.planner.auto_xy_servo_move(self.config, {}, self.plc, self.queues)
        self.assertEqual((400, 350), (commands["y"].Pos, commands["x"].Pos))
        self.plc.AxisList[8].Pos = 400
        commands, _ = self.planner.auto_xy_servo_move(self.config, {}, self.plc, self.queues)
        self.assertEqual(50, commands["y"].Pos)

    def test_missing_origin_height_disables_motion_and_guns(self):
        self.put(200)
        del self.config["origin_pos"]
        commands, mask = self.planner.auto_xy_servo_move(self.config, {}, self.plc, self.queues)
        self.assertEqual(0, mask)
        self.assertTrue(all(a.Speed == 0 and a.Status == 0 for a in commands.values()))

    def test_origin_height_accepts_normalized_scalar_and_runtime_update(self):
        self.put(200, 200, 500)
        self.put(210, 400, 550)
        for origin in (100, [100]):
            with self.subTest(origin=origin):
                commands, _ = self.planner.auto_xy_servo_move(self.config, {"origin_pos": origin}, self.plc, self.queues)
                self.assertEqual(400, commands["y"].Pos)

    def test_three_gun_device_rejects_ambiguous_origin_list(self):
        self.put(200)
        self.config["origin_pos"] = [1020, 2500]
        commands, mask = self.planner.auto_xy_servo_move(self.config, {}, self.plc, self.queues)
        self.assertEqual(0, mask)
        self.assertEqual(0, commands["x"].Speed)

    def make_runtime(self):
        from model.motionplan.MotionFrameByFramePlanning import MotionFrameByFramePlanning
        right = {**self.config, "sn": 5, "install_orietation": "right"}
        self.plc.Status = 1
        self.plc.Operate = 1 | (1 << 3) | (1 << 6)
        proc = SimpleNamespace(machine_config={"2": self.config, "5": right}, runtime_machine_config={}, num_devices=6, plc_data=self.plc, mode_config={"spray_mode": 0},
                               device_enable_mask=self.plc.Operate, last_operate_state=0, device_returning_to_origin=dict.fromkeys(range(6), False),
                               device_origin_complete={}, frame_queue_manager=self.queues,
                               lidar_status=0, raw_data_timeout_active=False)
        return MotionFrameByFramePlanning(), proc

    def test_frame_dispatch_maps_xy_and_gun_status_for_both_devices(self):
        self.put(150)
        self.put(200)
        self.put(250)
        planner, proc = self.make_runtime()
        frame = planner.build_moving_frame(proc)
        self.assertEqual((7, 7), (frame.AxisList[9].Status, frame.AxisList[19].Status))
        self.assertEqual((200, 200), (frame.AxisList[8].Speed, frame.AxisList[18].Speed))
        self.assertEqual((0, 0), (frame.Gun_cont1, frame.Gun_cont2))
        restored, _ = type(frame).from_bytes(frame.to_bytes())
        self.assertEqual((7, 7), (restored.AxisList[9].Status, restored.AxisList[19].Status))
        self.assertEqual(0x8002, restored.Control & 0xFFFF)

    def test_pc_auto_status_bit_does_not_trigger_servo_alarm(self):
        self.put(200)
        planner, proc = self.make_runtime()
        proc.plc_data.Status = 3
        frame = planner.build_moving_frame(proc)
        self.assertEqual((2, 2), (frame.AxisList[9].Status, frame.AxisList[19].Status))

    def test_disabled_fault_manual_and_cleaning_paths_clear_guns(self):
        self.put(200)
        for reason in ("disabled", "servo_fault", "lidar_fault", "timeout", "manual", "cleaning"):
            with self.subTest(reason=reason):
                planner, proc = self.make_runtime()
                if reason == "disabled":
                    proc.device_enable_mask = 1
                elif reason == "servo_fault":
                    self.plc.Status = 0
                elif reason == "lidar_fault":
                    proc.lidar_status = 1
                elif reason == "timeout":
                    proc.raw_data_timeout_active = True
                elif reason == "manual":
                    proc.mode_config["spray_mode"] = 1
                else:
                    self.plc.Operate |= planner.cleaning_planner.CLEAN_MODE_BIT
                frame = planner.build_moving_frame(proc)
                self.assertEqual((0, 0), (frame.AxisList[9].Status, frame.AxisList[19].Status))

    def test_planner_uses_ui_request_and_not_plc_device_bits(self):
        self.put(200)
        planner, proc = self.make_runtime()
        proc.device_enable_mask = 1 | (1 << 6)
        frame = planner.build_moving_frame(proc)
        self.assertEqual((0, 2), (frame.AxisList[9].Status, frame.AxisList[19].Status))
        proc.device_enable_mask = 0
        frame = planner.build_moving_frame(proc)
        self.assertEqual((0, 0), (frame.AxisList[9].Status, frame.AxisList[19].Status))
