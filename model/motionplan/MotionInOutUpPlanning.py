"""内外顶两组 Y/X 规划：横梁下方和顶部喷涂，Y 原点在上方。"""

from dataclasses import dataclass

from model.motionplan.MachineAxisMap import get_axis_position_limits
from model.motionplan.motionutil.InOutFramePlanningBase import InOutFramePlanningBase


@dataclass(frozen=True)
class TopGeometry:
    x_min: int
    x_max: int
    y_max: int
    y1_blocked: bool


class MotionInOutUpPlanning(InOutFramePlanningBase):
    def _geometry(self, machine_cfg, runtime_cfg, frame_stack, y1_absolute=None):
        side = machine_cfg["install_orietation"]
        frames = frame_stack.get(side, ())
        center = int(machine_cfg["z_position"])
        search_front = self._parameter(machine_cfg, runtime_cfg, "search_front_z_offset")
        search_after = self._parameter(machine_cfg, runtime_cfg, "search_after_z_offset")
        ys = [int(row.H_Axis) for row in self._rows(frames, center - search_front, center + search_after)]
        front = self._parameter(machine_cfg, runtime_cfg, "out_z_front_offset")
        after = self._parameter(machine_cfg, runtime_cfg, "out_z_after_offset")
        margin = self._parameter(machine_cfg, runtime_cfg, "in_up_y_offset")
        if min(front, after, margin) < 0:
            raise ValueError("内外顶搜索偏移不能为负")
        rows = list(self._rows(frames, center - front, center + after))
        if not ys and y1_absolute is None:
            # 无梁且查梁窗口为空时，仍允许运动窗口自身提供上下半区的参考高度。
            ys = [int(row.H_Axis) for row in rows]
        if not ys:
            return None
        y_center = (min(ys) + max(ys)) / 2
        upper = [row for row in rows if row.H_Axis >= y_center]
        xs = [int(value) for row in upper for value in (row.V_Axis_Min, row.V_Axis_Max) if value is not None and value != 0]
        if not xs:
            return None
        blocked = y1_absolute is not None and any(y1_absolute - margin <= row.H_Axis <= y1_absolute + margin for row in rows)
        return TopGeometry(min(xs), max(xs), max(int(row.H_Axis) for row in upper), blocked)

    def _build_without_beam(self, machine_cfg, runtime_cfg, plc_data, frame_stack):
        geometry = self._geometry(machine_cfg, runtime_cfg, frame_stack)
        if geometry is None:
            self.reset_motion_state(int(machine_cfg["sn"]))
            return self.motion_to_target.move_to_origin_safe(machine_cfg, runtime_cfg, plc_data)[0]
        _, origin2 = self._origin_heights(machine_cfg, runtime_cfg)
        y1_min, _ = get_axis_position_limits(machine_cfg, "y1")
        commands = self._safe_pair(machine_cfg, runtime_cfg, plc_data, 1, y1_min)
        y2_target = geometry.y_max + self._parameter(machine_cfg, runtime_cfg, "out_up_y_offset") - origin2
        # 无梁时按可达 Y 限位定位顶部，独立维持 X2 往复，不清除已有的顶部往复阶段。
        commands.update(self._pair_commands(machine_cfg, runtime_cfg, plc_data, 2, y2_target, geometry, True, commands["y1"].Pos))
        return commands

    def _build_commands(self, machine_cfg, runtime_cfg, plc_data, frame_stack, beam):
        origin1, origin2 = self._origin_heights(machine_cfg, runtime_cfg)
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
            commands.update(self._pair_commands(machine_cfg, runtime_cfg, plc_data, 2, y2_target, geometry, not keep_y, commands["y1"].Pos))
        return commands

    def auto_inout_up_move(self, machine_cfg, runtime_cfg, plc_data, frame_queue_manager):
        return self._auto_move(machine_cfg, runtime_cfg, plc_data, frame_queue_manager, "upper")
