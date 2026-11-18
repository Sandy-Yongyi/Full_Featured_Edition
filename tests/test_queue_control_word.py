import unittest
from types import SimpleNamespace

import numpy as np

from acquisition_sdk._internal.formats.complete_workpiece.BlockDataFormat import BlockData, OutsideData
from acquisition_sdk._internal.formats.frame_by_frame.AxisFrameDataFormat import AxisData as CloudRow, AxisFrameData
from model.MovingFrameData import ReceiveMovingFrameData, SendMovingFrameData
from model.motionplan.MotionCompleteWorkpiecePlanning import MotionCompleteWorkpiecePlanning
from model.motionplan.MotionContinuousBidirectionalPlanning import MotionContinuousBidirectionalPlanning
from model.motionplan.MotionFrameByFramePlanning import MotionFrameByFramePlanning


class QueueControlWordTests(unittest.TestCase):
    def build(self, planner, frame_stack=None, queues=None, **overrides):
        manager = SimpleNamespace(frame_stack=frame_stack or {}, queues=queues or {}, update_continuous_stations=lambda status: 0,
                                  continuous_slot_empty=lambda index: True)
        scan = SimpleNamespace(stage="waiting", update=lambda *args, **kwargs: SendMovingFrameData(Control=-32766))
        proc = SimpleNamespace(machine_config={}, num_devices=0, runtime_machine_config={}, device_enable_mask=1, plc_data=ReceiveMovingFrameData(Status=1),
                               last_operate_state=0, device_returning_to_origin={}, device_origin_complete={}, frame_queue_manager=manager,
                               mode_config={"spray_mode": 0}, lidar_status=0, raw_data_timeout_active=False, continuous_scan=scan,
                               continuous_scan_pending=False, continuous_lidar_ready=True)
        proc.__dict__.update(overrides)
        return planner.build_moving_frame(proc)

    def test_empty_queues_always_clear_bit0_bit1_and_old_bit15(self):
        for kind in (MotionFrameByFramePlanning, MotionCompleteWorkpiecePlanning, MotionContinuousBidirectionalPlanning):
            with self.subTest(planner=kind.__name__):
                self.assertEqual(0, self.build(kind()).Control)

    def test_frame_scans_every_direction_and_the_last_frame_for_any_nonzero_coordinate(self):
        planner = MotionFrameByFramePlanning()
        zeros = AxisFrameData([CloudRow(0, 0, 0)])
        stacks = {"left": [zeros] * 20, "right": [zeros] * 20, "right_upper": [zeros] * 20}
        self.assertEqual(0, self.build(planner, stacks).Control)
        for row in (CloudRow(100, 0, 0), CloudRow(0, 10, 0), CloudRow(0, 0, -10)):
            with self.subTest(row=row):
                stacks["right_upper"][-1] = AxisFrameData([row])
                frame = self.build(planner, stacks)
                restored, _ = SendMovingFrameData.from_bytes(frame.to_bytes())
                self.assertEqual(4, restored.Control)

    def test_data_bit_is_independent_of_enable_faults_manual_and_cleaning(self):
        stacks = {"right": [AxisFrameData([CloudRow(100, 20, 10)])]}
        for override in ({"device_enable_mask": 0}, {"plc_data": ReceiveMovingFrameData(Status=0)}, {"lidar_status": 1},
                         {"raw_data_timeout_active": True}, {"mode_config": {"spray_mode": 1}}, {"device_enable_mask": 32769}):
            with self.subTest(override=override):
                self.assertEqual(4, self.build(MotionFrameByFramePlanning(), stacks, **override).Control)

    def test_complete_workpiece_scans_all_device_queues_and_ignores_metadata(self):
        planner = MotionCompleteWorkpiecePlanning()
        queues = {"left": {0: [None]}, "right": {5: [None, {"data": None, "sn": 5}]}}
        self.assertEqual(0, self.build(planner, queues=queues).Control)
        queues["right"][5][-1] = {"data": BlockData(outside_data=[OutsideData(outside_y_min=2000)]), "sn": 5}
        self.assertEqual(4, self.build(planner, queues=queues, device_enable_mask=0).Control)
        queues["right"][5][-1] = {"data": None, "sn": 5}
        self.assertEqual(0, self.build(planner, queues=queues).Control)

    def test_complete_workpiece_retains_existing_nonempty_block_rule(self):
        queues = {"right": {5: [{"data": BlockData(outside_data=[OutsideData(outside_x_min=0)]), "sn": 5}]}}
        self.assertEqual(4, self.build(MotionCompleteWorkpiecePlanning(), queues=queues).Control)

    def test_continuous_retains_existing_station_occupancy_rule(self):
        stacks: dict[str, list[np.ndarray | None]] = {"left": [None, None, None], "right": [None, None, None]}
        planner = MotionContinuousBidirectionalPlanning()
        self.assertEqual(0, self.build(planner, stacks).Control)
        stacks["right"][2] = np.zeros((3, 3))
        self.assertEqual(4, self.build(planner, stacks).Control)
        stacks["right"][2] = None
        self.assertEqual(0, self.build(planner, stacks).Control)


if __name__ == "__main__":
    unittest.main()
