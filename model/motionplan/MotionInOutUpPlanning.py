"""内外顶两组 Y/X 规划：横梁下方和顶部喷涂，Y 原点在上方。"""

import math
import os
from dataclasses import dataclass

from model.dataprocess.frame_by_frame.BeamDetector import BeamDetector
from model.motionplan.MachineAxisMap import get_axis_index, get_axis_position_limits, get_axis_safe_pos, get_axis_speed_limit
from model.motionplan.MotionToTarget import MotionToTarget
from model.plc.MovingFrameData import AxisData
from model.utils.LoggerUtil import logger
from model.utils.TomlLoader import TomlLoader


@dataclass
class TopPairState:
    waiting_y: bool = True
    returning_x: bool = False
    toward_max: bool = True


@dataclass(frozen=True)
class TopGeometry:
    x_min: int
    x_max: int
    y_max: int
    y1_blocked: bool


class MotionInOutUpPlanning:
    def __init__(self, process_cfg=None, read_data_cfg=None, spray_cfg=None, motion_to_target=None):
        config_dir = os.path.join(os.getcwd(), "model", "tomls")
        process_cfg = process_cfg if process_cfg is not None else TomlLoader.load(os.path.join(config_dir, "ProcessConfig.toml"))
        read_data_cfg = read_data_cfg if read_data_cfg is not None else TomlLoader.load(os.path.join(config_dir, "ReadDataConfig.toml"))
        spray_cfg = spray_cfg if spray_cfg is not None else TomlLoader.load(os.path.join(config_dir, "SprayConfig.toml"))
        detection_cfg = dict(process_cfg)
        detection_cfg.update({key: read_data_cfg[key] for key in ("y_threshold", "z_threshold") if key in read_data_cfg})
        self.beam_detector = BeamDetector(detection_cfg)
        self.z_threshold = self.beam_detector.z_threshold
        self.safety_beam = int(process_cfg.get("safety_beam", 80))
        self.large_move_threshold = int(process_cfg.get("beam_y_large_move_threshold", 100))
        self.tolerance = int(spray_cfg.get("spray_pos_tolerance", 20))
        if min(self.safety_beam, self.large_move_threshold, self.tolerance) < 0:
            raise ValueError("横梁安全距离、Y 大幅移动阈值和到位公差不能为负")
        self.motion_to_target = motion_to_target if motion_to_target is not None else MotionToTarget()
        self._states: dict[tuple[int, int], TopPairState] = {}
        self._errors: dict[int, str] = {}

    def reset_motion_state(self, sn: int | None = None):
        if sn is None:
            self._states.clear()
        else:
            for pair in (1, 2):
                self._states.pop((int(sn), pair), None)

    @staticmethod
    def _parameter(machine_cfg, runtime_cfg, key):
        return int(runtime_cfg.get(key, machine_cfg.get(key, 0)))

    @staticmethod
    def _axis(machine_cfg, name, position, speed, status=0):
        lower, upper = get_axis_position_limits(machine_cfg, name)
        lower, upper = max(-32768, lower), min(32767, upper)
        limit = min(32767, get_axis_speed_limit(machine_cfg, name))
        if lower > upper or limit < 0:
            raise ValueError(f"内外顶 {name} 限位无效")
        return AxisData(Pos=max(lower, min(int(position), upper)), Speed=max(0, min(int(speed), limit)), Status=int(status))

    @staticmethod
    def _feedback(machine_cfg, plc_data, name):
        index = get_axis_index("inout_up", machine_cfg["install_orietation"], name)
        axes = getattr(plc_data, "AxisList", None)
        if axes is None or index >= len(axes) or not hasattr(axes[index], "Pos"):
            raise ValueError(f"内外顶 {name} 缺少 PLC 位置反馈")
        return int(axes[index].Pos)

    def _rows(self, frames, start_z, end_z):
        start = max(0, math.ceil(start_z / self.z_threshold))
        end = min(len(frames) - 1, math.floor(end_z / self.z_threshold))
        for index in range(start, end + 1):
            for row in getattr(frames[index], "FrameData", None) or ():
                if row.H_Axis is not None and row.H_Axis > 0:
                    yield row

    def _geometry(self, machine_cfg, runtime_cfg, frame_stack, y1_absolute):
        side = machine_cfg["install_orietation"]
        frames = frame_stack.get(side, ())
        center = int(machine_cfg["z_position"])
        search_front = self._parameter(machine_cfg, runtime_cfg, "search_front_z_offset")
        search_after = self._parameter(machine_cfg, runtime_cfg, "search_after_z_offset")
        ys = [int(row.H_Axis) for row in self._rows(frames, center - search_front, center + search_after)]
        if not ys:
            return None
        y_center = (min(ys) + max(ys)) / 2
        front = self._parameter(machine_cfg, runtime_cfg, "out_z_front_offset")
        after = self._parameter(machine_cfg, runtime_cfg, "out_z_after_offset")
        margin = self._parameter(machine_cfg, runtime_cfg, "in_up_y_offset")
        if min(front, after, margin) < 0:
            raise ValueError("内外顶搜索偏移不能为负")
        rows = list(self._rows(frames, center - front, center + after))
        upper = [row for row in rows if row.H_Axis >= y_center]
        xs = [int(value) for row in upper for value in (row.V_Axis_Min, row.V_Axis_Max) if value is not None and value != 0]
        if not xs:
            return None
        blocked = any(y1_absolute - margin <= row.H_Axis <= y1_absolute + margin for row in rows)
        return TopGeometry(min(xs), max(xs), max(int(row.H_Axis) for row in upper), blocked)

    def _safe_pair(self, machine_cfg, runtime_cfg, plc_data, pair):
        self._states.pop((int(machine_cfg["sn"]), pair), None)
        y_name, x_name = f"y{pair}", f"x{pair}"
        safe_x = get_axis_safe_pos(machine_cfg, x_name)
        current_x = self._feedback(machine_cfg, plc_data, x_name)
        current_y = self._feedback(machine_cfg, plc_data, y_name)
        target_y = get_axis_safe_pos(machine_cfg, y_name) if abs(current_x - safe_x) <= self.tolerance else current_y
        return {y_name: self._axis(machine_cfg, y_name, target_y, self._parameter(machine_cfg, runtime_cfg, "y_pos_speed")),
                x_name: self._axis(machine_cfg, x_name, safe_x, self._parameter(machine_cfg, runtime_cfg, "x_pos_speed"))}

    def _pair_commands(self, machine_cfg, runtime_cfg, plc_data, pair, y_target, geometry, reciprocate):
        y_name, x_name = f"y{pair}", f"x{pair}"
        state_key = (int(machine_cfg["sn"]), pair)
        state = self._states.get(state_key)
        current_y = self._feedback(machine_cfg, plc_data, y_name)
        current_x = self._feedback(machine_cfg, plc_data, x_name)
        y_target = self._axis(machine_cfg, y_name, y_target, 0).Pos
        x_position = int(machine_cfg["x_position"])
        low = self._axis(machine_cfg, x_name, geometry.x_min - self._parameter(machine_cfg, runtime_cfg, "out_front_x_offset") - x_position, 0).Pos
        high = self._axis(machine_cfg, x_name, geometry.x_max - self._parameter(machine_cfg, runtime_cfg, "out_after_x_offset") - x_position, 0).Pos
        if high < low:
            raise ValueError("内外顶 X 往复终点小于起点")
        if state is None:
            state = TopPairState()
            self._states[state_key] = state
        elif not state.waiting_y and abs(y_target - current_y) > self.large_move_threshold:
            state.waiting_y = True
            state.returning_x = True
        x_at_min = abs(current_x - low) <= self.tolerance
        if state.returning_x and x_at_min:
            state.returning_x = False
        if state.waiting_y and not state.returning_x and abs(current_y - y_target) <= self.tolerance and x_at_min:
            state.waiting_y = False
            state.toward_max = True
        y_position = current_y if state.returning_x else y_target
        y_cmd = self._axis(machine_cfg, y_name, y_position, self._parameter(machine_cfg, runtime_cfg, "y_pos_speed"))
        x_target = low
        speed_key = "x_pos_speed"
        if reciprocate and not state.waiting_y:
            if state.toward_max and current_x >= high - self.tolerance:
                state.toward_max = False
            elif not state.toward_max and current_x <= low + self.tolerance:
                state.toward_max = True
            x_target = high if state.toward_max else low
            speed_key = "x_recip_speed"
        x_cmd = self._axis(machine_cfg, x_name, x_target, self._parameter(machine_cfg, runtime_cfg, speed_key))
        # 有效横梁与有效高度期间保持出粉，包括 X 定位、等待及往复换向。
        x_cmd.Status = 1 if x_cmd.Speed > 0 and y_cmd.Speed > 0 else 0
        return {y_name: y_cmd, x_name: x_cmd}

    def _build_commands(self, machine_cfg, runtime_cfg, plc_data, frame_stack, beam):
        origins = runtime_cfg.get("origin_pos", machine_cfg.get("origin_pos"))
        if not isinstance(origins, (list, tuple)) or len(origins) != 2:
            raise ValueError("内外顶 origin_pos 必须包含 Y1、Y2 两个离地高度")
        origin1, origin2 = int(origins[0]), int(origins[1])
        y1_absolute = int(beam["y_bottom"]) - self.safety_beam - self._parameter(machine_cfg, runtime_cfg, "in_up_y_offset")
        geometry = self._geometry(machine_cfg, runtime_cfg, frame_stack, y1_absolute)
        if geometry is None:
            self.reset_motion_state(int(machine_cfg["sn"]))
            return self.motion_to_target.move_to_origin_safe(machine_cfg, runtime_cfg, plc_data)[0]
        if y1_absolute > origin1:
            commands = self._safe_pair(machine_cfg, runtime_cfg, plc_data, 1)
        else:
            commands = self._pair_commands(machine_cfg, runtime_cfg, plc_data, 1, y1_absolute - origin1, geometry, not geometry.y1_blocked)
        up_offset = self._parameter(machine_cfg, runtime_cfg, "out_up_y_offset")
        if int(beam["y_top"]) + self.safety_beam + up_offset > origin2:
            commands.update(self._safe_pair(machine_cfg, runtime_cfg, plc_data, 2))
        else:
            y2_absolute = geometry.y_max + up_offset
            keep_y = y2_absolute >= origin2
            y2_target = self._feedback(machine_cfg, plc_data, "y2") if keep_y else y2_absolute - origin2
            commands.update(self._pair_commands(machine_cfg, runtime_cfg, plc_data, 2, y2_target, geometry, not keep_y))
        return commands

    def auto_inout_up_move(self, machine_cfg, runtime_cfg, plc_data, frame_queue_manager):
        sn = int(machine_cfg["sn"])
        try:
            for name in ("y1", "x1", "y2", "x2"):
                self._feedback(machine_cfg, plc_data, name)
            beam = self.beam_detector.find_for_side(machine_cfg["install_orietation"], int(machine_cfg["z_position"]),
                                                    self._parameter(machine_cfg, runtime_cfg, "search_front_z_offset"),
                                                    self._parameter(machine_cfg, runtime_cfg, "search_after_z_offset"), frame_queue_manager.frame_stack, "upper")
            if not beam["found"]:
                self.reset_motion_state(sn)
                commands, _ = self.motion_to_target.move_to_origin_safe(machine_cfg, runtime_cfg, plc_data)
            else:
                commands = self._build_commands(machine_cfg, runtime_cfg, plc_data, frame_queue_manager.frame_stack, beam)
            if not commands:
                raise ValueError("内外顶没有可用轴命令")
            self._errors.pop(sn, None)
            return commands
        except Exception as exc:
            self.reset_motion_state(sn)
            message = str(exc)
            if self._errors.get(sn) != message:
                logger.error(f"SN[{sn}] 内外顶规划失败，停止运动并关闭喷枪: {message}")
                self._errors[sn] = message
            return {name: AxisData() for name in ("y1", "x1", "y2", "x2")}
