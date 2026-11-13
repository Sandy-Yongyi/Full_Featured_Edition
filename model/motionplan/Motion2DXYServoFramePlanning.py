import math
import os
from dataclasses import dataclass

from model.motionplan.MachineAxisMap import get_axis_index, get_axis_position_limits, get_axis_speed_limit
from model.motionplan.MotionToTarget import MotionToTarget
from model.motionplan.motionutil.AxisLimits import build_axis, clamp_to_limit_yx
from model.motionplan.motionutil.FrameSearchHelper import FrameSearchHelper
from model.MovingFrameData import AxisData
from model.utils.LoggerUtil import logger
from model.utils.TomlLoader import TomlLoader


@dataclass(frozen=True)
class XYServoGeometry:
    y_min: int | None = None
    y_max: int | None = None
    x_min: int | None = None
    gun_mask: int = 0


class Motion2DXYServoFramePlanning:
    """横向二维三枪：按帧窗口定位 X，自动往复 Y。"""
    def __init__(self, read_data_cfg=None, spray_cfg=None, motion_to_target=None):
        config_dir = os.path.join(os.getcwd(), "model", "tomls")
        read_data_cfg = read_data_cfg if read_data_cfg is not None else TomlLoader.load(os.path.join(config_dir, "ReadDataConfig.toml"))
        spray_cfg = spray_cfg if spray_cfg is not None else TomlLoader.load(os.path.join(config_dir, "SprayConfig.toml"))
        self.z_threshold = int(read_data_cfg.get("z_threshold", 10))
        self.tolerance = int(spray_cfg.get("spray_pos_tolerance", 10))
        self.frame_helper = FrameSearchHelper(self.z_threshold)
        self.motion_to_target = motion_to_target if motion_to_target is not None else MotionToTarget()
        self._toward_max: dict[int, bool] = {}
        self._errors: dict[int, str] = {}

    def reset_motion_state(self, sn):
        self._toward_max.pop(int(sn), None)

    def _rows(self, frames, z_start, z_end):
        # Do not clamp an entirely out-of-queue interval onto the nearest frame.
        start = max(0, math.ceil(z_start / self.z_threshold))
        end = min(len(frames) - 1, math.ceil(z_end / self.z_threshold))
        for index in range(start, end + 1):
            for row in getattr(frames[index], "FrameData", None) or ():
                if self.frame_helper.row_has_data(row):
                    yield row

    def scan_geometry(self, machine_cfg, runtime_cfg, frame_queue_manager):
        count = int(machine_cfg.get("spray_num", 0))
        spacing = int(machine_cfg.get("spray_radius", 0))
        if count != 3 or spacing <= 0:
            raise ValueError("H2D_XYservo requires spray_num=3 and positive spray_radius")
        center = int(machine_cfg.get("z_position", 0))
        front = self._parameter(machine_cfg, runtime_cfg, "out_z_front_offset")
        after = self._parameter(machine_cfg, runtime_cfg, "out_z_after_offset")
        if front < 0 or after < 0:
            raise ValueError("Z window offsets must not be negative")
        frames = self.frame_helper.get_side_frames(machine_cfg, frame_queue_manager)
        rows = list(self._rows(frames, center - spacing * (count - 2) - front, center + spacing * (count - 2) + after))
        valid = [row for row in rows if row.H_Axis is not None and row.V_Axis_Min is not None]
        half = spacing / 2
        bands = ((center - half - spacing, center - half), (center - half, center + half), (center + half, center + half + spacing))
        mask = sum(1 << i for i, (start, end) in enumerate(bands) if any(self._rows(frames, math.ceil(start), math.ceil(end))))
        if not valid:
            return XYServoGeometry(gun_mask=mask)
        return XYServoGeometry(min(int(row.H_Axis) for row in valid), max(int(row.H_Axis) for row in valid), min(int(row.V_Axis_Min) for row in valid), mask)

    @staticmethod
    def _parameter(machine_cfg, runtime_cfg, key):
        return int(runtime_cfg.get(key, machine_cfg.get(key, 0)))

    @staticmethod
    def _origin_height(machine_cfg, runtime_cfg):
        value = runtime_cfg.get("origin_pos", machine_cfg.get("origin_pos"))
        if isinstance(value, (list, tuple)):
            if len(value) != 1:
                raise ValueError("H2D_XYservo origin_pos must contain exactly one Y height")
            value = value[0]
        if value is None:
            raise ValueError("H2D_XYservo origin_pos is required")
        return int(value)

    @staticmethod
    def _axis(machine_cfg, name, position, speed):
        lower, upper = get_axis_position_limits(machine_cfg, name)
        lower, upper = max(-32768, lower), min(32767, upper)
        speed_limit = get_axis_speed_limit(machine_cfg, name)
        if lower > upper or speed_limit < 0:
            raise ValueError(f"Invalid {name} position/speed limits")
        return build_axis(clamp_to_limit_yx(position, lower, upper), speed, 0, min(32767, speed_limit))

    def build_zero_commands(self, machine_cfg, runtime_cfg, plc_data):
        self.reset_motion_state(machine_cfg["sn"])
        try:
            commands, ready = self.motion_to_target.move_to_origin_safe(machine_cfg, runtime_cfg, plc_data)
            if not commands:
                raise ValueError("Missing XY safe return commands")
            commands = {name: self._axis(machine_cfg, name, axis.Pos, axis.Speed) for name, axis in commands.items()}
            return commands, ready
        except Exception as exc:
            logger.error(f"H2D_XYservo safe return failed; disable motion and guns: {exc}")
            return {"y": AxisData(), "x": AxisData()}, False

    def auto_xy_servo_move(self, machine_cfg, runtime_cfg, plc_data, frame_queue_manager):
        """三枪局部掩码 bit0/1/2 同时写入 X 轴 Status。"""
        sn = int(machine_cfg["sn"])
        try:
            geometry = self.scan_geometry(machine_cfg, runtime_cfg, frame_queue_manager)
            if geometry.y_min is None or geometry.y_max is None or geometry.x_min is None:
                return self.build_zero_commands(machine_cfg, runtime_cfg, plc_data)[0], 0
            origin_height = self._origin_height(machine_cfg, runtime_cfg)
            y_low = geometry.y_min - self._parameter(machine_cfg, runtime_cfg, "out_down_y_offset") - origin_height
            y_high = geometry.y_max + self._parameter(machine_cfg, runtime_cfg, "out_up_y_offset") - origin_height
            low = self._axis(machine_cfg, "y", y_low, 0).Pos
            high = self._axis(machine_cfg, "y", y_high, 0).Pos
            if low >= high:
                raise ValueError("Y reciprocation range is empty after applying limits")
            y_index = get_axis_index(machine_cfg["type"], machine_cfg["install_orietation"], "y")
            current = int(plc_data.AxisList[y_index].Pos)
            toward_max = self._toward_max.get(sn, True)
            if current >= high - self.tolerance:
                toward_max = False
            elif current <= low + self.tolerance:
                toward_max = True
            self._toward_max[sn] = toward_max
            y_cmd = self._axis(machine_cfg, "y", high if toward_max else low, self._parameter(machine_cfg, runtime_cfg, "y_recip_speed"))
            x_target = geometry.x_min - self._parameter(machine_cfg, runtime_cfg, "out_front_x_offset") - int(machine_cfg["x_position"])
            x_cmd = self._axis(machine_cfg, "x", x_target, self._parameter(machine_cfg, runtime_cfg, "x_pos_speed"))
            x_cmd.Status = geometry.gun_mask if y_cmd.Speed > 0 and x_cmd.Speed > 0 else 0
            self._errors.pop(sn, None)
            return {"y": y_cmd, "x": x_cmd}, x_cmd.Status
        except Exception as exc:
            self.reset_motion_state(sn)
            message = str(exc)
            if self._errors.get(sn) != message:
                logger.error(f"SN[{sn}] H2D_XYservo planning failed; disable motion and guns: {exc}")
                self._errors[sn] = message
            return {"y": AxisData(), "x": AxisData()}, 0
