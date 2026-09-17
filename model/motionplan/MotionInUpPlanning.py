import os

from model.motionplan.motionutil.AxisLimits import build_axis, clamp_to_limit_yx
from model.motionplan.MachineAxisMap import get_axis_map, get_axis_position_limits, get_axis_speed_limit
from model.motionplan.MotionToTarget import MotionToTarget
from model.motionplan.motionutil.WorkpieceMotionHelper import WorkpieceMotionHelper
from model.motionplan.motionutil.MotionUtil import MotionUtil
from model.utils.LoggerUtil import logger
from model.utils.TomlLoader import TomlLoader

"""内顶自动运动规划。

逻辑整理：
1. 只处理该设备队列中的第一个工件。
2. 队首不是柜体时：设备持续安全回原点；直到工件“过了后外侧”才允许删除。
3. 队首是柜体时，按列处理 `inside_data`：
    - `wait_front_inside`：等待当前列前内侧到达；若当前列分枪使能，则 X 轴先定位到 `x_pre_distance`。
    - `recip_inside`：当前列允许喷涂时，X 轴按 `inside_x_min - in_front_x_offset`、`inside_x_max - in_after_x_offset` 往复喷涂。
      若 `in_z_front_offset + in_z_after_offset + 2 * spray_pos_tolerance > inside_z_span`，则先确保到达预进枪位再往复。
    - `return_origin`：最后一列后内侧到达后，设备安全回原点。
    - `finish`：清理状态，并允许删除当前工件。
4. 若当前列后内侧到达且存在下一列，则切换到下一列并重复执行等待前内侧与内侧往复。
"""


class MotionInUpPlanning:
    def __init__(self):
        self.spray_cfg = TomlLoader.load(os.path.join(os.getcwd(), "model", "tomls", "SprayConfig.toml"))
        self.process_cfg = TomlLoader.load(os.path.join(os.getcwd(), "model", "tomls", "ProcessConfig.toml"))
        self.motion_to_target = MotionToTarget()
        self.motion_util = MotionUtil()
        self.spray_pos_tolerance = int(self.spray_cfg.get("spray_pos_tolerance", 10) or 10)
        self.x_pre_distance = int(self.spray_cfg.get("x_pre_distance", 30) or 30)
        self.x_range = int(self.process_cfg.get("x_range", 300) or 300)
        self.y_range = int(self.process_cfg.get("y_range", 300) or 300)
        self.z_range = int(self.process_cfg.get("z_range", 300) or 300)
        self._work_states: dict[int, dict] = {}

    def reset_motion_state(self, sn=None):
        WorkpieceMotionHelper.reset_state(self._work_states, sn)

    def auto_in_up_move(self, machine_cfg, runtime_cfg, plc_data, frame_queue):
        sn = int(machine_cfg.get("sn", 0) or 0)
        WorkpieceMotionHelper.ensure_state(self._work_states, sn, self._create_initial_state)
        block = WorkpieceMotionHelper.peek_first_block(frame_queue)

        if block is None:
            self.reset_motion_state(sn)
            axis_cmds, _ = self.motion_to_target.move_to_origin_safe(machine_cfg, runtime_cfg, plc_data)
            if axis_cmds is None:
                axis_cmds = self.motion_to_target.hold_current_position(machine_cfg, plc_data)
            return axis_cmds, False, False

        ctx = WorkpieceMotionHelper.build_block_context(machine_cfg, runtime_cfg, plc_data, block)
        if not self.motion_util.check_if_cabinet(block, self.x_range, self.y_range, self.z_range) or not ctx.get("inside_data"):
            logger.info(f"SN[{sn}] in_up first block invalid for inside spray, return to origin and wait for pass")
            return self._move_origin_and_wait_pass(ctx)

        axis_cmds, done = self._handle_in_up_spray(ctx)
        return axis_cmds, done, False

    def _move_origin_and_wait_pass(self, ctx):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        axis_cmds, _ = self.motion_to_target.move_to_origin_safe(ctx["machine_cfg"], ctx["runtime_cfg"], ctx["plc_data"])
        if axis_cmds is None:
            axis_cmds = self.motion_to_target.hold_current_position(ctx["machine_cfg"], ctx["plc_data"])
        done = self._has_after_over_arrived(ctx)
        if done:
            self.reset_motion_state(sn)
        return axis_cmds, done, False

    def _handle_in_up_spray(self, ctx):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        state_name = self._work_states[sn].get("state", "wait_front_inside")
        handler = self._dispatch_table_in_up().get(state_name, self._state_wait_front_inside)
        return handler(ctx)

    def _dispatch_table_in_up(self):
        return {
            "wait_front_inside": self._state_wait_front_inside,
            "recip_inside": self._state_recip_inside,
            "return_origin": self._state_return_origin,
            "finish": self._state_finish,
        }

    def _state_wait_front_inside(self, ctx):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        axis_cmds = self._build_wait_front_axes(ctx)
        front_ready = self._has_front_arrived(ctx) or self._has_front_over_arrived(ctx)
        after_over = self._has_inside_after_over_arrived(ctx)

        if front_ready and not after_over:
            self._work_states[sn]["state"] = "recip_inside"
            self._work_states[sn]["x_phase"] = "to_max"
            logger.info(f"SN[{sn}] in_up current inside column reached front position, start reciprocating")
        elif after_over:
            if self._move_to_next_column_if_any(ctx):
                logger.info(f"SN[{sn}] in_up current inside column already passed after position, skip to next column")
            else:
                self._work_states[sn]["state"] = "return_origin"
                logger.info(f"SN[{sn}] in_up current inside column already passed after position, return origin")
        return axis_cmds, False

    def _state_recip_inside(self, ctx):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        state = self._work_states[sn]
        axis_cmds = self._build_recip_axes(ctx, state)
        if self._has_after_arrived(ctx) or self._has_inside_after_over_arrived(ctx):
            if self._move_to_next_column_if_any(ctx):
                logger.info(f"SN[{sn}] in_up current inside column done, switch to next column")
            else:
                self._work_states[sn]["state"] = "return_origin"
                logger.info(f"SN[{sn}] in_up all inside columns done, return origin")
        return axis_cmds, False

    def _state_return_origin(self, ctx):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        axis_cmds, all_ready = self.motion_to_target.move_to_origin_safe(
            ctx["machine_cfg"],
            ctx["runtime_cfg"],
            ctx["plc_data"],
        )
        if axis_cmds is None:
            axis_cmds = self.motion_to_target.hold_current_position(ctx["machine_cfg"], ctx["plc_data"])
        if all_ready:
            self._work_states[sn]["state"] = "finish"
            logger.info(f"SN[{sn}] in_up return origin done")
        return axis_cmds, False

    def _state_finish(self, ctx):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        self.reset_motion_state(sn)
        logger.info(f"SN[{sn}] in_up finish spraying")
        axis_cmds = self.motion_to_target.hold_current_position(ctx["machine_cfg"], ctx["plc_data"])
        return axis_cmds, True

    @staticmethod
    def _create_initial_state():
        return {"state": "wait_front_inside", "column_idx": 0, "x_phase": "to_max"}

    def _build_wait_front_axes(self, ctx):
        machine_cfg = ctx["machine_cfg"]
        runtime_cfg = ctx["runtime_cfg"]
        plc_data = ctx["plc_data"]
        axis_cmds = self.motion_to_target.hold_current_position(machine_cfg, plc_data)
        if not self._is_current_column_enabled(ctx):
            return axis_cmds

        x_min_limit, x_max_limit = get_axis_position_limits(machine_cfg, "x")
        x_speed = int(runtime_cfg.get("x_pos_speed", machine_cfg.get("x_pos_speed", 300)) or 300)
        x_speed_limit = get_axis_speed_limit(machine_cfg, "x")
        x_target = clamp_to_limit_yx(self.x_pre_distance, x_min_limit, x_max_limit)
        axis_cmds["x"] = build_axis(x_target, x_speed, 0, x_speed_limit)
        return axis_cmds

    def _build_recip_axes(self, ctx, state):
        machine_cfg = ctx["machine_cfg"]
        runtime_cfg = ctx["runtime_cfg"]
        plc_data = ctx["plc_data"]
        axis_cmds = self._build_wait_front_axes(ctx)
        if not self._is_current_column_enabled(ctx):
            return axis_cmds

        x_min_limit, x_max_limit = get_axis_position_limits(machine_cfg, "x")
        x_speed = int(runtime_cfg.get("x_recip_speed", machine_cfg.get("x_recip_speed", 300)) or 300)
        x_speed_limit = get_axis_speed_limit(machine_cfg, "x")
        in_front_x_offset = int(runtime_cfg.get("in_front_x_offset", machine_cfg.get("in_front_x_offset", 100)) or 100)
        in_after_x_offset = int(runtime_cfg.get("in_after_x_offset", machine_cfg.get("in_after_x_offset", 100)) or 100)
        x_position = int(machine_cfg.get("x_position", 0) or 0)
        x_cur = self._get_axis_pos(machine_cfg, plc_data, "x")
        spray_status = 1 if self._is_chain_running(plc_data) else 0

        if self._should_wait_pre_position_before_recip(ctx) and abs(x_cur - self.x_pre_distance) > self.spray_pos_tolerance:
            pre_target = clamp_to_limit_yx(self.x_pre_distance, x_min_limit, x_max_limit)
            axis_cmds["x"] = build_axis(pre_target, x_speed, 0, x_speed_limit)
            return axis_cmds

        inside_x_min, inside_x_max = self._get_current_inside_x_range(ctx)
        x_min_target = clamp_to_limit_yx(int(inside_x_min or 0) - in_front_x_offset - x_position, x_min_limit, x_max_limit)
        x_max_target = clamp_to_limit_yx(int(inside_x_max or 0) - in_after_x_offset - x_position, x_min_limit, x_max_limit)
        if x_min_target > x_max_target:
            x_min_target, x_max_target = x_max_target, x_min_target

        phase = state.get("x_phase", "to_max")
        target = x_max_target if phase == "to_max" else x_min_target
        if x_cur > x_max_target + self.spray_pos_tolerance:
            phase = "to_min"
            state["x_phase"] = phase
            target = x_min_target
        elif x_cur < x_min_target - self.spray_pos_tolerance:
            phase = "to_max"
            state["x_phase"] = phase
            target = x_max_target
        if abs(x_cur - target) <= self.spray_pos_tolerance:
            phase = "to_min" if phase == "to_max" else "to_max"
            state["x_phase"] = phase
            target = x_max_target if phase == "to_max" else x_min_target

        axis_cmds["x"] = build_axis(target, x_speed, spray_status, x_speed_limit)
        return axis_cmds

    def _move_to_next_column_if_any(self, ctx):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        inside_columns = ctx.get("inside_data") or []
        next_idx = int(self._work_states[sn].get("column_idx", 0) or 0) + 1
        if next_idx >= len(inside_columns):
            return False
        self._work_states[sn]["column_idx"] = next_idx
        self._work_states[sn]["state"] = "wait_front_inside"
        self._work_states[sn]["x_phase"] = "to_max"
        return True

    def _get_current_inside_column(self, ctx):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        inside_columns = ctx.get("inside_data") or []
        column_idx = int(self._work_states[sn].get("column_idx", 0) or 0)
        if 0 <= column_idx < len(inside_columns):
            return inside_columns[column_idx]
        return None

    def _get_current_group(self, ctx):
        block = ctx["block_data"]
        machine_cfg = ctx["machine_cfg"]
        sn_value = machine_cfg.get("sn", None)
        sn = -1 if sn_value is None else int(sn_value)
        inside_column = self._get_current_inside_column(ctx)
        if inside_column is None:
            return None
        group_id = inside_column.inside_id
        if group_id is None:
            group_id = int(self._work_states[sn].get("column_idx", 0) or 0)

        for machine_data in getattr(block, "distribe_gun_list", None) or []:
            machine_id = getattr(machine_data, "machine_id", None)
            if machine_id is None or int(machine_id) != sn:
                continue
            for gun_group in getattr(machine_data, "gun_groups", None) or []:
                if getattr(gun_group, "group_type", None) != "inside":
                    continue
                gun_group_id = getattr(gun_group, "group_id", None)
                if gun_group_id is not None and int(gun_group_id) == int(group_id):
                    return gun_group
        return None

    def _is_current_column_enabled(self, ctx):
        sn_value = ctx["machine_cfg"].get("sn", None)
        sn = -1 if sn_value is None else int(sn_value)
        gun_group = self._get_current_group(ctx)
        if gun_group is None:
            column_idx = int(self._work_states.get(sn, {}).get("column_idx", 0) or 0)
            inside_columns = ctx.get("inside_data") or []
            inside_column = self._get_current_inside_column(ctx)
            inside_id = None if inside_column is None else getattr(inside_column, "inside_id", None)
            available_group_ids = []
            for machine_data in getattr(ctx["block_data"], "distribe_gun_list", None) or []:
                machine_id = getattr(machine_data, "machine_id", None)
                if machine_id is None or int(machine_id) != sn:
                    continue
                for group in getattr(machine_data, "gun_groups", None) or []:
                    if getattr(group, "group_type", None) == "inside":
                        available_group_ids.append(getattr(group, "group_id", None))
            logger.warning(
                f"SN[{sn}] in_up missing current column gun distribution, keep X axis disabled: "
                f"column_idx={column_idx}, inside_count={len(inside_columns)}, inside_id={inside_id}, "
                f"available_inside_group_ids={available_group_ids}"
            )
            return False
        for gun in getattr(gun_group, "gundata_list", None) or []:
            if int(getattr(gun, "gun_y_enable", 0) or 0) == 1:
                return True
        return False

    def _get_current_inside_x_range(self, ctx):
        inside_column = self._get_current_inside_column(ctx)
        subinside_list = getattr(inside_column, "subinside_datalist", None) or []
        x_mins = [int(getattr(sub, "subinside_x_min", 0) or 0) for sub in subinside_list if getattr(sub, "subinside_x_min", None) is not None]
        x_maxs = [int(getattr(sub, "subinside_x_max", 0) or 0) for sub in subinside_list if getattr(sub, "subinside_x_max", None) is not None]
        return (min(x_mins) if x_mins else 0, max(x_maxs) if x_maxs else 0)

    def _get_current_inside_z_range(self, ctx):
        inside_column = self._get_current_inside_column(ctx)
        subinside_list = getattr(inside_column, "subinside_datalist", None) or []
        z_mins = [int(getattr(sub, "subinside_z_min", 0) or 0) for sub in subinside_list if getattr(sub, "subinside_z_min", None) is not None]
        z_maxs = [int(getattr(sub, "subinside_z_max", 0) or 0) for sub in subinside_list if getattr(sub, "subinside_z_max", None) is not None]
        return (min(z_mins) if z_mins else 0, max(z_maxs) if z_maxs else 0)

    def _should_wait_pre_position_before_recip(self, ctx):
        runtime_cfg = ctx["runtime_cfg"]
        machine_cfg = ctx["machine_cfg"]
        inside_z_min, inside_z_max = self._get_current_inside_z_range(ctx)
        inside_z_span = max(0, int(inside_z_max or 0) - int(inside_z_min or 0))
        in_front_offset = int(runtime_cfg.get("in_z_front_offset", machine_cfg.get("in_z_front_offset", 0)) or 0)
        in_after_offset = int(runtime_cfg.get("in_z_after_offset", machine_cfg.get("in_z_after_offset", 0)) or 0)
        return (in_front_offset + in_after_offset + 2 * self.spray_pos_tolerance) > inside_z_span

    def _has_front_arrived(self, ctx):
        front_z_machine, front_z_chain = self._get_front_z_pair(ctx)
        return self.motion_util.has_arrived_z(front_z_machine, front_z_chain)

    def _has_front_over_arrived(self, ctx):
        front_z_machine, front_z_chain = self._get_front_z_pair(ctx)
        return self.motion_util.has_over_arrive_z(front_z_machine, front_z_chain)

    def _has_after_arrived(self, ctx):
        after_z_machine, after_z_chain = self._get_after_z_pair(ctx)
        return self.motion_util.has_arrived_z(after_z_machine, after_z_chain)

    def _has_inside_after_over_arrived(self, ctx):
        after_z_machine, after_z_chain = self._get_after_z_pair(ctx)
        return self.motion_util.has_over_arrive_z(after_z_machine, after_z_chain)

    def _has_after_over_arrived(self, ctx):
        after_z_machine, after_z_chain = self._get_after_over_pair(ctx)
        return self.motion_util.has_over_arrive_z(after_z_machine, after_z_chain)

    def _get_front_z_pair(self, ctx):
        inside_z_min, _ = self._get_current_inside_z_range(ctx)
        return WorkpieceMotionHelper.get_inside_front_z_pair(ctx, "in_z_front_offset", inside_z_min)

    def _get_after_z_pair(self, ctx):
        _, inside_z_max = self._get_current_inside_z_range(ctx)
        return WorkpieceMotionHelper.get_inside_after_z_pair(ctx, "in_z_after_offset", inside_z_max)

    def _get_after_over_pair(self, ctx):
        outside = (ctx.get("outside_data") or [None])[0]
        if outside is None:
            return 0, 0
        return WorkpieceMotionHelper.get_outside_after_z_pair(ctx, "out_z_after_offset", "outside_z_max")

    def _get_axis_pos(self, machine_cfg, plc_data, axis_name):
        axis_map = get_axis_map(machine_cfg.get("type", ""), machine_cfg.get("install_orietation", "left"))
        return self.motion_to_target._get_axis_current_pos(plc_data, axis_map[axis_name])

    @staticmethod
    def _is_chain_running(plc_data):
        return getattr(plc_data, "ChainStatus", "stopped") in ("moving_forward", "moving_reverse")
