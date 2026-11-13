import unittest
from types import SimpleNamespace
from unittest.mock import patch

from acquisition_sdk._internal.dataprocess.frame_by_frame.BeamDetector import BeamDetector
from acquisition_sdk._internal.formats.frame_by_frame.AxisFrameDataFormat import AxisData, AxisFrameData


def frame(*ys):
    return AxisFrameData([AxisData(y, 500, 300) for y in ys])


class BeamDetectorTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(y_threshold=10, z_threshold=10, beams_threshold=0.7, merge_beams=300, beams_width=200, beams_min_valid_frames=5)
        self.detector = BeamDetector(self.config)
        self.machine = dict(sn=0, type="inout_up", install_orietation="left", z_position=50, search_front_z_offset=50, search_after_z_offset=50)
        self.stacks = {"left": [frame() for _ in range(11)], "right": []}

    def fill(self, ys, count=5, start=0):
        for index in range(start, start + count):
            self.stacks["left"][index] = frame(*ys)

    def find(self, **runtime):
        return self.detector.find_for_machine(self.machine, self.stacks, runtime)

    def test_four_nonempty_frames_rejected_five_accepted_and_empty_frames_excluded(self):
        self.fill([1000, 1010, 2000, 2010], 4)
        self.assertEqual(dict(found=False, beam_type="upper", y_bottom=None, y_top=None), self.find())
        self.fill([1000, 1010, 2000, 2010], 5)
        self.assertEqual(dict(found=True, beam_type="upper", y_bottom=2000, y_top=2010), self.find())

    def test_minimum_nonempty_frames_is_configurable(self):
        self.detector = BeamDetector(dict(self.config, beams_min_valid_frames=6))
        self.fill([1000, 2000], 5)
        self.assertFalse(self.find()["found"])
        self.fill([1000, 2000], 6)
        self.assertTrue(self.find()["found"])

    def test_threshold_is_per_frame_and_repeated_rows_cannot_make_noise_a_beam(self):
        self.fill([1000, 1010, 2000, 2010], 10)
        for index in range(6):
            self.stacks["left"][index].FrameData.extend([AxisData(3000, 500, 300)] * 10)
        self.assertEqual(2010, self.find()["y_top"])
        self.stacks["left"][6].FrameData.append(AxisData(3000, 500, 300))
        self.assertEqual(3000, self.find()["y_top"])

    def test_single_segment_uses_all_valid_y_center_and_tie_is_lower(self):
        self.fill([2000, 2010])
        self.stacks["left"][0].FrameData.append(AxisData(1000, 500, 300))
        self.assertTrue(self.find()["found"])
        self.fill([1000, 1010])
        self.stacks["left"][0].FrameData.append(AxisData(2000, 500, 300))
        self.assertFalse(self.find()["found"])
        self.machine["type"] = "inout_down"
        self.assertEqual(1000, self.find()["y_bottom"])
        self.fill([1000, 1010])
        self.assertTrue(self.find()["found"])

    def test_multiple_segments_select_extremes_even_when_both_above_reference_center(self):
        self.fill([2000, 2010, 2500, 2510])
        self.stacks["left"][0].FrameData.append(AxisData(100, 500, 300))
        self.machine["type"] = "inout_down"
        self.assertEqual(2000, self.find()["y_bottom"])

    def test_gap_strictly_less_than_merge_and_thickness_includes_limit(self):
        self.fill([1000, 1200])
        self.machine["type"] = "inout_down"
        self.assertEqual((1000, 1200), (self.find()["y_bottom"], self.find()["y_top"]))
        self.fill([1000, 1210])
        self.assertFalse(self.find()["found"])
        self.fill([1000, 1300])
        self.assertEqual((1000, 1000), (self.find()["y_bottom"], self.find()["y_top"]))

    def test_y_continuity_uses_y_step_instead_of_z_step(self):
        self.detector = BeamDetector(dict(self.config, y_threshold=20, z_threshold=10, merge_beams=0))
        self.fill([1000, 1020, 2000, 2020])
        self.assertEqual((2000, 2020), (self.find()["y_bottom"], self.find()["y_top"]))

    def test_overwide_top_segment_does_not_fall_back_to_middle_segment(self):
        self.fill([1000, 1500, *range(2000, 2220, 10)])
        self.assertFalse(self.find()["found"])
        self.machine["type"] = "inout_down"
        self.assertEqual(1000, self.find()["y_bottom"])

    def test_window_boundaries_runtime_offsets_and_no_edge_reuse(self):
        self.fill([1000, 2000], 5, 3)
        self.assertTrue(self.find(search_front_z_offset=20, search_after_z_offset=20)["found"])
        self.assertFalse(self.find(search_front_z_offset=19, search_after_z_offset=20)["found"])
        self.machine["z_position"] = 10000
        self.assertFalse(self.find()["found"])
        self.machine["z_position"] = -10000
        self.assertFalse(self.find()["found"])

    def test_right_side_is_independent_and_missing_data_does_not_reuse_old_result(self):
        self.fill([1000, 2000])
        self.assertTrue(self.find()["found"])
        self.machine["install_orietation"] = "right"
        self.assertFalse(self.find()["found"])
        self.stacks["right"] = [frame(1200, 2200) for _ in range(5)]
        self.assertEqual(2200, self.find()["y_top"])
        self.stacks["right"] = []
        self.assertFalse(self.find()["found"])

    def test_explicit_side_api_returns_same_four_field_result(self):
        self.fill([1000, 1010, 2000, 2010])
        self.assertEqual(self.find(), self.detector.find_for_side("left", 50, 50, 50, self.stacks, "upper"))

    def test_invalid_parameters_are_rejected(self):
        for key, value in (("z_threshold", 0), ("y_threshold", 0), ("beams_threshold", 1.1), ("beams_threshold", float("nan")),
                           ("beams_min_valid_frames", 0), ("merge_beams", -1), ("beams_width", -1)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                BeamDetector(dict(self.config, **{key: value}))


class BeamDetectionIntegrationTests(unittest.TestCase):
    def test_inout_devices_delegate_detection_and_unreachable_down_beam_keeps_powder_off(self):
        from model.motionplan.MotionFrameByFramePlanning import MotionFrameByFramePlanning
        from model.MovingFrameData import ReceiveMovingFrameData
        from model.utils.TomlLoader import TomlLoader

        planner = MotionFrameByFramePlanning()
        config = TomlLoader.load("model/tomls/MachineConfig1.toml")
        stacks = {side: [frame(1000, 1010, 2000, 2010) for _ in range(400)] for side in ("left", "right")}
        plc = ReceiveMovingFrameData(Status=3)
        proc = SimpleNamespace(machine_config=config, num_devices=6, runtime_machine_config={}, device_enable_mask=127, plc_data=plc, last_operate_state=0,
                               device_returning_to_origin=dict.fromkeys(range(6), False), device_origin_complete={}, frame_queue_manager=SimpleNamespace(frame_stack=stacks),
                               mode_config={"spray_mode": 0}, lidar_status=0, raw_data_timeout_active=False)
        moving = planner.build_moving_frame(proc)
        self.assertFalse(hasattr(planner, "beam_results"))
        down_indices = (*range(4, 8), *range(14, 18))
        self.assertTrue(all(moving.AxisList[index].Pos == 0 and moving.AxisList[index].Status == 0 for index in down_indices))
        proc.device_enable_mask = 1
        with (patch.object(planner.inout_up_planner, "auto_inout_up_move", wraps=planner.inout_up_planner.auto_inout_up_move) as top_move,
              patch.object(planner.inout_down_planner, "auto_inout_down_move", wraps=planner.inout_down_planner.auto_inout_down_move) as bottom_move):
            disabled_frame = planner.build_moving_frame(proc)
            top_move.assert_not_called()
            bottom_move.assert_not_called()
        self.assertTrue(all(axis.Status == 0 for axis in disabled_frame.AxisList))


if __name__ == "__main__":
    unittest.main()
