import copy
import contextlib
import io
import os
import sys
import unittest
from types import SimpleNamespace


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from model.motionplan.MachineAxisMap import LIDAR_AXIS_MAP
from model.motionplan.MotionContinuousBidirectionalPlanning import MotionContinuousBidirectionalPlanning
from model.motionplan.MotionCleaningPlanning import MotionCleaningPlanning
from model.plc.MovingFrameData import AxisData, ReceiveMovingFrameData, SendMovingFrameData
from model.utils.TomlLoader import TomlLoader
from control.PlcCommunicationProcess import PlcCommunicationProcess
import queue


class _FakeContinuousScan:
    def __init__(self):
        self.stage = "waiting"
        self.last_allow_scan = None

    def update(self, feedback, ready=True, allow_scan=True):
        self.last_allow_scan = allow_scan
        frame = SendMovingFrameData()
        frame.Status = int(feedback.Status) & 0x01
        frame.Operate = 1 if (int(feedback.Status) & 0x01 and int(feedback.Operate) & 0x01) else 0
        frame.HeartBeat = feedback.HeartBeat
        frame.AxisList = [AxisData(Pos=axis.Pos, Speed=0, Status=0) for axis in feedback.AxisList]
        for index in LIDAR_AXIS_MAP.values():
            frame.AxisList[index] = AxisData(Pos=777, Speed=25, Status=0)
        return frame


class _FakeFrameQueueManager:
    def __init__(self, occupied=False, release_status=0):
        value = object() if occupied else None
        self.frame_stack = {"left": [value, None, None], "right": [value, None, None]}
        self.release_status = release_status
        self.update_count = 0

    def update_continuous_stations(self, plc_status):
        self.update_count += 1
        return self.release_status

    def continuous_slot_empty(self, index):
        return all(stack[index] is None for stack in self.frame_stack.values())


def _build_proc(status=0x7F, operate=0x01, occupied=False):
    machine_config = TomlLoader.load(os.path.join(PROJECT_ROOT, "model", "tomls", "MachineConfig3.toml"))
    feedback = ReceiveMovingFrameData(Status=status, Operate=operate, HeartBeat=9)
    # Keep every X axis at its safe position, while one Y axis per device is away
    # from safe. MotionToTarget can therefore command every axis toward safe now.
    for index in (2, 4, 6, 9):
        feedback.AxisList[index].Pos = 100
    return SimpleNamespace(
        plc_data=feedback,
        machine_config=machine_config,
        runtime_machine_config={int(sn): copy.deepcopy(cfg) for sn, cfg in machine_config.items()},
        num_devices=4,
        device_origin_complete={sn: False for sn in range(4)},
        device_returning_to_origin={sn: True for sn in range(4)},
        last_operate_state=0,
        lidar_status=0,
        continuous_scan=_FakeContinuousScan(),
        continuous_scan_pending=False,
        continuous_lidar_ready=True,
        frame_queue_manager=_FakeFrameQueueManager(occupied=occupied),
    )


class MotionContinuousBidirectionalPlanningTest(unittest.TestCase):
    def test_cleaning_planner_resolves_continuous_station_state(self):
        cleaning = MotionCleaningPlanning()
        with contextlib.redirect_stdout(io.StringIO()):
            enabled, ready, just_closed = cleaning.resolve_continuous_mode_state((1 << 15) | 1, 0, _FakeFrameQueueManager(occupied=True), False)

        self.assertTrue(enabled)
        self.assertFalse(ready)
        self.assertFalse(just_closed)

    def test_continuous_runtime_initializes_all_machine_motion_state(self):
        proc = PlcCommunicationProcess(queue.Queue(), queue.Queue(), queue.Queue(), strategy_name="continuous_bidirectional")

        proc._initialize_runtime_state()

        self.assertEqual(proc.num_devices, 4)
        self.assertEqual(set(proc.runtime_machine_config), {0, 1, 2, 3})
        self.assertEqual(proc.device_returning_to_origin, {0: True, 1: True, 2: True, 3: True})

    def test_builds_all_device_safe_commands_without_overwriting_lidar_axes(self):
        proc = _build_proc()

        frame = MotionContinuousBidirectionalPlanning().build_moving_frame(proc)

        self.assertEqual(frame.Operate & 0x1F, 0x1F)
        for index in range(18):
            self.assertEqual(frame.AxisList[index].Pos, 0, index)
            self.assertEqual(frame.AxisList[index].Status, 0, index)
        for index in LIDAR_AXIS_MAP.values():
            self.assertEqual((frame.AxisList[index].Pos, frame.AxisList[index].Speed), (777, 25))

    def test_servo_alarm_uses_status_bit_zero_and_disables_all_device_motion(self):
        proc = _build_proc(status=0x7E)

        frame = MotionContinuousBidirectionalPlanning().build_moving_frame(proc)

        self.assertEqual(frame.Operate & 0x1F, 0)

    def test_enabled_devices_keep_their_operate_bits_after_reaching_safe_position(self):
        proc = _build_proc(operate=0x01 | 0x02 | 0x08)
        proc.plc_data.AxisList = [AxisData() for _ in proc.plc_data.AxisList]
        proc.device_returning_to_origin = {sn: False for sn in range(4)}

        frame = MotionContinuousBidirectionalPlanning().build_moving_frame(proc)

        self.assertEqual(frame.Operate & 0x1F, 0x0B)

    def test_clean_mode_moves_x_to_max_only_after_all_station_data_is_empty(self):
        clean_bit = 1 << 15
        planner = MotionContinuousBidirectionalPlanning()

        ready_frame = planner.build_moving_frame(_build_proc(operate=clean_bit | 0x01, occupied=False))
        with contextlib.redirect_stdout(io.StringIO()):
            blocked_frame = planner.build_moving_frame(_build_proc(operate=clean_bit | 0x01, occupied=True))

        for index in (3, 5, 7, 10, 13, 16):
            self.assertEqual(ready_frame.AxisList[index].Pos, 900, index)
            self.assertEqual(blocked_frame.AxisList[index].Pos, 0, index)

    def test_clean_mode_prevents_a_new_lidar_scan(self):
        proc = _build_proc(operate=(1 << 15) | 0x01)
        proc.frame_queue_manager = _FakeFrameQueueManager(release_status=0x0E)

        frame = MotionContinuousBidirectionalPlanning().build_moving_frame(proc)

        self.assertFalse(proc.continuous_scan.last_allow_scan)
        self.assertEqual(proc.frame_queue_manager.update_count, 0)
        self.assertEqual(frame.Status & 0x0E, 0)


if __name__ == "__main__":
    unittest.main()
