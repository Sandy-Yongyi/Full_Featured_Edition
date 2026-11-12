"""内外底两组 Y/X 规划：底部和横梁上方喷涂，Y 原点在下方。"""

from dataclasses import dataclass

from model.motionplan.MachineAxisMap import get_axis_position_limits
from model.motionplan.motionutil.InOutFramePlanningBase import InOutFramePlanningBase


@dataclass(frozen=True)
class BottomGeometry:
    x_min: int
    x_max: int
    y_min: int
    y2_blocked: bool


class MotionInOutDownPlanning(InOutFramePlanningBase):
    def _geometry(self, machine_cfg, runtime_cfg, frame_stack, y2_absolute=None):
        frames = frame_stack.get(machine_cfg["install_orietation"], ())
        center = int(machine_cfg["z_position"])
        search_front = self._parameter(machine_cfg, runtime_cfg, "search_front_z_offset")
        search_after = self._parameter(machine_cfg, runtime_cfg, "search_after_z_offset")
        ys = [int(row.H_Axis) for row in self._rows(frames, center - search_front, center + search_after)]
        front = self._parameter(machine_cfg, runtime_cfg, "out_z_front_offset")
        after = self._parameter(machine_cfg, runtime_cfg, "out_z_after_offset")
        margin = self._parameter(machine_cfg, runtime_cfg, "in_down_y_offset")
        if min(front, after, margin) < 0:
            raise ValueError("内外底搜索偏移不能为负")
        rows = list(self._rows(frames, center - front, center + after))
        if not ys and y2_absolute is None:
            ys = [int(row.H_Axis) for row in rows]
        if not ys:
            return None
        y_center = (min(ys) + max(ys)) / 2
        lower = [row for row in rows if row.H_Axis <= y_center]
        xs = [int(value) for row in lower for value in (row.V_Axis_Min, row.V_Axis_Max) if value is not None and value != 0]
        if not xs:
            return None
        blocked = y2_absolute is not None and any(y2_absolute - margin <= row.H_Axis <= y2_absolute + margin for row in rows)
        return BottomGeometry(min(xs), max(xs), min(int(row.H_Axis) for row in lower), blocked)

    def _build_without_beam(self, machine_cfg, runtime_cfg, plc_data, frame_stack):
        geometry = self._geometry(machine_cfg, runtime_cfg, frame_stack)
        if geometry is None:
            self.reset_motion_state(int(machine_cfg["sn"]))
            return self.motion_to_target.move_to_origin_safe(machine_cfg, runtime_cfg, plc_data)[0]
        origin1, _ = self._origin_heights(machine_cfg, runtime_cfg)
        y1_target = geometry.y_min - self._parameter(machine_cfg, runtime_cfg, "out_down_y_offset") - origin1
        _, y2_max = get_axis_position_limits(machine_cfg, "y2")
        commands = self._safe_pair(machine_cfg, runtime_cfg, plc_data, 2, y2_max)
        commands.update(self._pair_commands(machine_cfg, runtime_cfg, plc_data, 1, y1_target, geometry, True, commands["y2"].Pos))
        return commands

    def _build_commands(self, machine_cfg, runtime_cfg, plc_data, frame_stack, beam):
        origin1, origin2 = self._origin_heights(machine_cfg, runtime_cfg)
        y2_absolute = int(beam["y_top"]) + self.safety_beam + self._parameter(machine_cfg, runtime_cfg, "in_down_y_offset")
        geometry = self._geometry(machine_cfg, runtime_cfg, frame_stack, y2_absolute)
        if geometry is None:
            self.reset_motion_state(int(machine_cfg["sn"]))
            return self.motion_to_target.move_to_origin_safe(machine_cfg, runtime_cfg, plc_data)[0]
        down_offset = self._parameter(machine_cfg, runtime_cfg, "out_down_y_offset")
        # 内外底以 Y2 为约束基准，先生成 Y2 的本周期命令，再修正 Y1 目标及到位判断。
        if y2_absolute < origin2:
            commands = self._safe_pair(machine_cfg, runtime_cfg, plc_data, 2)
        else:
            commands = self._pair_commands(machine_cfg, runtime_cfg, plc_data, 2, y2_absolute - origin2, geometry, not geometry.y2_blocked)
        if int(beam["y_bottom"]) - self.safety_beam - down_offset < origin1:
            commands.update(self._safe_pair(machine_cfg, runtime_cfg, plc_data, 1))
        else:
            y1_absolute = geometry.y_min - down_offset
            keep_y = y1_absolute <= origin1
            y1_target = self._feedback(machine_cfg, plc_data, "y1") if keep_y else y1_absolute - origin1
            commands.update(self._pair_commands(machine_cfg, runtime_cfg, plc_data, 1, y1_target, geometry, not keep_y, commands["y2"].Pos))
        return commands

    def auto_inout_down_move(self, machine_cfg, runtime_cfg, plc_data, frame_queue_manager):
        return self._auto_move(machine_cfg, runtime_cfg, plc_data, frame_queue_manager, "lower")
