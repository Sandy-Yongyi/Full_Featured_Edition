"""工件静止时的四激光轴扫描；不依赖链条脉冲或喷涂设备规划。"""

import math

from model.motionplan.MachineAxisMap import LIDAR_AXIS_MAP
from model.plc.MovingFrameData import AxisData, SendMovingFrameData


class ContinuousLidarScan:
    def __init__(self, read_config, spray_config):
        self.start = int(read_config.get("min_swing_pulse", 0))
        self.end = int(read_config["max_swing_pulse"])
        self.tolerance = float(spray_config["spray_pos_tolerance"])
        if not (-32768 <= self.start < self.end <= 32767):
            raise ValueError("Scan endpoints must fit Int16, with start less than end.")
        if not math.isfinite(self.tolerance) or not 0 <= self.tolerance < (self.end - self.start) / 2:
            raise ValueError("Position tolerance must be nonnegative and less than half the scan travel.")
        self.set_speed(read_config.get("lidar_scan_speed", 25))
        self.stage = "startup"
        self.target = None
        self.pulse = self.start
        self.motion_status = "stopped"
        self.error = ""
        self.arrival_consumed = False
        self.retry_acknowledged = False

    def request_retry(self):
        """丢弃本趟，恢复后先空走到原目标端点，再反向完整扫描。"""
        if self.stage in ("scanning", "complete"):
            self.stage = "retry_wait"
            self.retry_acknowledged = False
            self.motion_status = "stopped"

    def set_speed(self, speed):
        if isinstance(speed, bool) or int(speed) != speed or not 1 <= int(speed) <= 32767:
            raise ValueError("Scan speed must be an integer between 1 and 32767 mm/s.")
        self.speed = int(speed)

    def update(self, feedback, ready=True, allow_scan=True):
        """返回目标帧；回零不发布运动状态，扫描状态沿用现有队列枚举。"""
        frame = SendMovingFrameData()
        frame.HeartBeat = int(feedback.HeartBeat)
        self.motion_status = "stopped"

        # basic validation and prepare axis list
        if not self._validate_and_prepare_frame(frame, feedback):
            return frame

        positions = [int(feedback.AxisList[index].Pos) for index in LIDAR_AXIS_MAP.values()]
        if not self._check_positions(positions, frame):
            return frame

        self.pulse = math.floor(sum(positions) / len(positions))
        if self.stage == "fault":
            self.motion_status = "error"
            return frame

        servo_normal = bool(int(feedback.Status) & 1)
        enabled = bool(int(feedback.Operate) & 1)
        arrived = bool(int(feedback.Status) & 2)
        frame.Status = int(servo_normal)
        frame.Operate = int(enabled and servo_normal)
        if not ready:
            frame.Operate = 0
            return frame
        if not servo_normal:
            if self.stage in ("scanning", "retry_wait", "retry_position"):
                self._fault("Servo fault during scanning; current scan discarded.")
            return frame
        if not enabled:
            if self.stage == "scanning":
                self.request_retry()
            return frame

        at_start = all(abs(p - self.start) <= self.tolerance for p in positions)
        at_end = all(abs(p - self.end) <= self.tolerance for p in positions)

        # handle arrival and stage transitions
        if not arrived:
            self.arrival_consumed = False
            if self.stage == "complete":
                self.stage = "waiting"
            elif self.stage == "scanning":
                self._fault("Workpiece arrival signal lost during scanning; current scan discarded.")
                return frame

        if not self._handle_retry_states(arrived, at_start, at_end):
            return frame

        # normal startup/homing/waiting/scanning flow
        if self.stage == "startup":
            self.stage = "waiting" if at_start or at_end else "homing"
            self.target = self.start if self.stage == "homing" else None
        if self.stage == "homing" and at_start:
            self.stage = "waiting"
            self.target = None
        if self.stage == "waiting" and arrived and not self.arrival_consumed and allow_scan:
            if not (at_start or at_end):
                self._fault("Lidar axes are not at an endpoint. Restart to home the axes.")
                return frame
            self.target = self.end if at_start else self.start
            self.arrival_consumed = True
            self.stage = "scanning"
        if self.stage == "scanning":
            reached = at_end if self.target == self.end else at_start
            if reached:
                self.stage = "complete"
            else:
                self.motion_status = "moving_forward" if self.target == self.end else "moving_reverse"

        if self.stage in ("homing", "scanning", "retry_position"):
            self._set_axes_target(frame)

        return frame

    def _validate_and_prepare_frame(self, frame, feedback):
        """Validate feedback length and prepare frame axis list."""
        if len(feedback.AxisList) != len(frame.AxisList):
            self._fault("PLC axis count does not match the frame definition.")
            return False
        frame.AxisList = [AxisData(Pos=int(axis.Pos), Speed=0, Status=0) for axis in feedback.AxisList]
        return True

    def _check_positions(self, positions, frame):
        """Validate lidar axis synchronization and range."""
        spread = max(positions) - min(positions)
        if spread > self.tolerance:
            self._fault(f"Lidar axes are out of sync: positions={positions}, spread={spread}, tolerance={self.tolerance}")
            return False
        if min(positions) < self.start - self.tolerance or max(positions) > self.end + self.tolerance:
            self._fault(f"Lidar axes exceed scan travel: {positions}")
            return False
        return True

    def _handle_retry_states(self, arrived, at_start, at_end):
        """Handle retry_wait and retry_position states. Returns False to abort update and keep frame."""
        if self.stage == "retry_wait":
            if not arrived or not self.retry_acknowledged:
                return False
            self.stage = "retry_position"
        if self.stage == "retry_position":
            if not arrived:
                self._fault("Workpiece arrival signal lost during rescan positioning.")
                return False
            reached = at_end if self.target == self.end else at_start
            if reached:
                self.target = self.start if self.target == self.end else self.end
                self.stage = "scanning"
        return True

    def _set_axes_target(self, frame):
        # Ensure Pos is an int; if target is unexpectedly None, fall back to start
        pos = self.start if self.target is None else int(self.target)
        for index in LIDAR_AXIS_MAP.values():
            frame.AxisList[index] = AxisData(Pos=pos, Speed=self.speed, Status=0)

    def _fault(self, message):
        # 异常锁存到重启，避免错误工件在位置恢复后自动续扫。
        if self.stage != "fault":
            self.error = message
        self.stage = "fault"
        self.motion_status = "error"
