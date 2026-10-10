import os
from model.motionplan.motionutil.AxisLimits import build_axis, clamp_to_limit_yx
from model.motionplan.MachineAxisMap import get_axis_map, get_axis_position_limits, get_axis_speed_limit
from model.motionplan.MotionToTarget import MotionToTarget
from model.motionplan.motionutil.WorkpieceMotionHelper import WorkpieceMotionHelper
from model.utils.WorkpieceOriginUtil import get_origin_reference_x, get_origin_side
from model.utils.LoggerUtil import logger
from model.motionplan.motionutil.MotionUtil import MotionUtil
from model.utils.TomlLoader import TomlLoader

"""外底自动运动规划。

逻辑整理：
1. 只处理该设备队列中的第一个工件。
2. 队首不是柜体时：设备持续安全回原点；直到工件“过了后外侧”才允许删除。
3. 队首是柜体时，按以下阶段执行：
    - `wait_front_outside`：等待前外侧到达；若分枪使能，则 Y 轴先定位到 `gun_y_downer`，
      X 轴先定位到 `x_pre_distance`。
    - `recip_outside`：X 轴按 `outside_x_min - out_front_x_offset`、`outside_x_max - out_after_x_offset` 往复喷涂。
    - `return_origin`：后外侧到达后，设备安全回原点。
    - `finish`：清理状态，并允许删除当前工件。
"""


class MotionOutDownPlanning:
    def __init__(self):
        self.spray_cfg = TomlLoader.load(os.path.join(os.getcwd(), "model", "tomls", "SprayConfig.toml"))
        self.process_cfg = TomlLoader.load(os.path.join(os.getcwd(), "model", "tomls", "ProcessConfig.toml"))
        self.read_data_cfg = TomlLoader.load(os.path.join(os.getcwd(), "model", "tomls", "ReadDataConfig.toml"))
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

    def auto_out_down_move(self, machine_cfg, runtime_cfg, plc_data, frame_queue):
        """单台外底设备自动运动。

        Returns:
            axis_cmds: 当前设备轴命令
            done: 当前队首工件是否处理完成，可删除
            stop_chain: 是否请求停链，外底当前固定为 False
        """
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
        is_cabinet = self.motion_util.check_if_cabinet(block, self.x_range, self.y_range, self.z_range)
        has_enabled_down_gun = self._has_enabled_down_gun(machine_cfg, block)

        if not is_cabinet or not has_enabled_down_gun:
            if not is_cabinet:
                logger.info(f"SN[{sn}] out_down first block is not cabinet, return to origin and wait for pass")
            else:
                logger.info(f"SN[{sn}] out_down no enabled gun, return to origin and wait for pass")
            axis_cmds, _ = self.motion_to_target.move_to_origin_safe(machine_cfg, runtime_cfg, plc_data)
            if axis_cmds is None:
                axis_cmds = self.motion_to_target.hold_current_position(machine_cfg, plc_data)
            done = self._has_after_over_arrived(ctx)
            if done:
                self.reset_motion_state(sn)
            return axis_cmds, done, False

        axis_cmds, done = self._handle_out_down_spray(ctx)
        return axis_cmds, done, False

    def _handle_out_down_spray(self, ctx):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        state_name = self._work_states[sn].get("state", "wait_front_outside")
        handler = self._dispatch_table_out_down().get(state_name)
        if handler is None:
            handler = self._state_wait_front_outside
        return handler(ctx)

    def _dispatch_table_out_down(self):
        """状态到处理函数映射。"""
        return {
            "wait_front_outside": self._state_wait_front_outside,
            "recip_outside": self._state_recip_outside,
            "return_origin": self._state_return_origin,
            "finish": self._state_finish,
        }

    def _state_wait_front_outside(self, ctx):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        self._log_outside_z_trace(ctx, "wait_front_outside")
        axis_cmds = self._build_wait_front_axes(ctx)
        if self._has_front_arrived(ctx) or self._has_front_over_arrived(ctx):
            self._work_states[sn]["state"] = "recip_outside"
            self._work_states[sn]["x_phase"] = "to_max"
            logger.info(f"SN[{sn}] out_down arrived front outside, start reciprocating")
        return axis_cmds, False

    def _state_recip_outside(self, ctx):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        state = self._work_states[sn]
        self._log_outside_z_trace(ctx, "recip_outside")
        axis_cmds = self._build_recip_axes(ctx, state)
        if self._has_after_arrived(ctx) or self._has_after_over_arrived(ctx):
            self._work_states[sn]["state"] = "return_origin"
            logger.info(f"SN[{sn}] out_down rear outside arrived, return origin")
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
            logger.info(f"SN[{sn}] out_down return origin done")
        return axis_cmds, False

    def _state_finish(self, ctx):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        self.reset_motion_state(sn)
        logger.info(f"SN[{sn}] out_down finish spraying")
        axis_cmds = self.motion_to_target.hold_current_position(ctx["machine_cfg"], ctx["plc_data"])
        return axis_cmds, True

    @staticmethod
    def _create_initial_state():
        return {"state": "wait_front_outside", "x_phase": "to_max"}

    def _build_wait_front_axes(self, ctx):
        machine_cfg = ctx["machine_cfg"]
        runtime_cfg = ctx["runtime_cfg"]
        plc_data = ctx["plc_data"]
        axis_cmds = self.motion_to_target.hold_current_position(machine_cfg, plc_data)
        x_min_limit, x_max_limit = get_axis_position_limits(machine_cfg, "x")
        x_speed = int(runtime_cfg.get("x_pos_speed", machine_cfg.get("x_pos_speed", 300)) or 300)
        x_speed_limit = get_axis_speed_limit(machine_cfg, "x")
        x_target = clamp_to_limit_yx(self.x_pre_distance, x_min_limit, x_max_limit)
        axis_cmds["x"] = build_axis(x_target, x_speed, 0, x_speed_limit)

        sn_value = machine_cfg.get("sn", None)
        sn = -1 if sn_value is None else int(sn_value)
        gun = WorkpieceMotionHelper.find_enabled_gun(ctx["block_data"], sn, group_type="down")
        if gun is not None and int(getattr(gun, "gun_y_enable", 0) or 0) == 1:
            y_min_limit, y_max_limit = get_axis_position_limits(machine_cfg, "y")
            y_speed = int(runtime_cfg.get("y_pos_speed", machine_cfg.get("y_pos_speed", 100)) or 100)
            y_speed_limit = get_axis_speed_limit(machine_cfg, "y")
            y_target = clamp_to_limit_yx(int(getattr(gun, "gun_y_downer", 0) or 0), y_min_limit, y_max_limit)
            axis_cmds["y"] = build_axis(y_target, y_speed, 0, y_speed_limit)
        elif gun is None:
            logger.warning(f"SN[{sn}] out_down missing precomputed gun distribution, keep Y axis disabled")

        return axis_cmds

    def _build_recip_axes(self, ctx, state):
        machine_cfg = ctx["machine_cfg"]
        runtime_cfg = ctx["runtime_cfg"]
        plc_data = ctx["plc_data"]
        outside = ctx["outside_data"][0]
        axis_cmds = self._build_wait_front_axes(ctx)
        x_min_limit, x_max_limit = get_axis_position_limits(machine_cfg, "x")
        x_speed = int(runtime_cfg.get("x_recip_speed", machine_cfg.get("x_recip_speed", 300)) or 300)
        x_speed_limit = get_axis_speed_limit(machine_cfg, "x")
        out_front_x_offset = int(runtime_cfg.get("out_front_x_offset", machine_cfg.get("out_front_x_offset", 100)) or 100)
        out_after_x_offset = int(runtime_cfg.get("out_after_x_offset", machine_cfg.get("out_after_x_offset", 100)) or 100)
        x_position = int(machine_cfg.get("x_position", 0) or 0)
        spray_status = 1 if self._is_chain_running(plc_data) else 0

        outside_x_min, outside_x_max = self._resolve_outside_x_range(outside)
        x_min_target = clamp_to_limit_yx(outside_x_min - out_front_x_offset - x_position, x_min_limit, x_max_limit)
        x_max_target = clamp_to_limit_yx(outside_x_max - out_after_x_offset - x_position, x_min_limit, x_max_limit)
        if x_min_target > x_max_target:
            x_min_target, x_max_target = x_max_target, x_min_target

        phase = state.get("x_phase", "to_max")
        x_cur = self._get_axis_pos(machine_cfg, plc_data, "x")
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

    @staticmethod
    def _is_chain_running(plc_data):
        return getattr(plc_data, "ChainStatus", "stopped") in ("moving_forward", "moving_reverse")

    def _has_front_arrived(self, ctx):
        front_z_machine, front_z_chain = self._get_front_z_pair(ctx)
        return self.motion_util.has_arrived_z(front_z_machine, front_z_chain)

    def _has_front_over_arrived(self, ctx):
        front_z_machine, front_z_chain = self._get_front_z_pair(ctx)
        return self.motion_util.has_over_arrive_z(front_z_machine, front_z_chain)

    def _has_after_arrived(self, ctx):
        after_z_machine, after_z_chain = self._get_after_z_pair(ctx)
        return self.motion_util.has_arrived_z(after_z_machine, after_z_chain)

    def _has_after_over_arrived(self, ctx):
        after_z_machine, after_z_chain = self._get_after_z_pair(ctx)
        return self.motion_util.has_over_arrive_z(after_z_machine, after_z_chain)

    def _get_front_z_pair(self, ctx):
        return WorkpieceMotionHelper.get_outside_front_z_pair(ctx, "out_z_front_offset", "outside_z_min")

    def _get_after_z_pair(self, ctx):
        return WorkpieceMotionHelper.get_outside_after_z_pair(ctx, "out_z_after_offset", "outside_z_max")

    def _log_outside_z_trace(self, ctx, state_name):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        outside = ctx["outside_data"][0]
        front_z_machine, front_z_chain = self._get_front_z_pair(ctx)
        after_z_machine, after_z_chain = self._get_after_z_pair(ctx)
        logger.debug(
            f"SN[{sn}] out_down state={state_name}, "
            f"front_z_machine={front_z_machine}, front_z_chain={front_z_chain}, "
            f"after_z_machine={after_z_machine}, after_z_chain={after_z_chain}, "
            f"fifo_frame_pos={ctx['fifo_frame_pos']}, "
            f"outside_z_min={int(getattr(outside, 'outside_z_min', 0) or 0)}, "
            f"outside_z_max={int(getattr(outside, 'outside_z_max', 0) or 0)}"
        )

    @staticmethod
    def _calc_chain_z(block, object_z):
        return int(block.fifo_frame_pos or 0) - int(object_z or 0)

    def _get_axis_pos(self, machine_cfg, plc_data, axis_name):
        axis_map = get_axis_map(machine_cfg.get("type", ""), machine_cfg.get("install_orietation", "left"))
        return self.motion_to_target._get_axis_current_pos(plc_data, axis_map[axis_name])

    def _resolve_outside_x_range(self, outside):
        outside_x_min = int(getattr(outside, "outside_x_min", 0) or 0)
        outside_x_max = int(getattr(outside, "outside_x_max", 0) or 0)
        if get_origin_side(self.read_data_cfg) == "right":
            reference_x = get_origin_reference_x(self.read_data_cfg, 2040.0)
            outside_x_min, outside_x_max = int(reference_x - outside_x_max), int(reference_x - outside_x_min)
        return outside_x_min, outside_x_max

    @staticmethod
    def _has_enabled_down_gun(machine_cfg, block):
        sn_value = machine_cfg.get("sn", None)
        sn = -1 if sn_value is None else int(sn_value)
        return WorkpieceMotionHelper.find_enabled_gun(block, sn, group_type="down") is not None
