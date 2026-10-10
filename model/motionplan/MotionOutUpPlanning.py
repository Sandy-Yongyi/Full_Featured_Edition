import os
from model.motionplan.motionutil.AxisLimits import build_axis
from model.motionplan.motionutil.WorkpieceMotionHelper import WorkpieceMotionHelper
from model.utils.LoggerUtil import logger
from model.motionplan.motionutil.MotionUtil import MotionUtil
from model.utils.TomlLoader import TomlLoader

"""外顶自动运动规划。

规则：
1. 只处理当前设备队列中的第一个工件。
2. 不是柜体时，全程不喷涂；工件过了后外侧再删除。
3. 是柜体时分 3 个阶段：
   - `wait_front_outside`：等待前外侧到达，轴不动作，喷涂关闭。
   - `spray_outside`：到达前外侧后开始喷涂，轴不动作，仅 `Status=1`。
   - `finish`：到达后外侧后停止喷涂，返回完成以删除当前工件。
4. 外顶只有一个轴，因此 `Pos=0`、`Speed=0` 固定不变。
"""


class MotionOutUpPlanning:
    def __init__(self):
        self.spray_cfg = TomlLoader.load(os.path.join(os.getcwd(), "model", "tomls", "SprayConfig.toml"))
        self.process_cfg = TomlLoader.load(os.path.join(os.getcwd(), "model", "tomls", "ProcessConfig.toml"))
        self.motion_util = MotionUtil()
        self.x_range = int(self.process_cfg.get("x_range", 300) or 300)
        self.y_range = int(self.process_cfg.get("y_range", 300) or 300)
        self.z_range = int(self.process_cfg.get("z_range", 300) or 300)
        self._work_states: dict[int, dict] = {}

    def reset_motion_state(self, sn=None):
        WorkpieceMotionHelper.reset_state(self._work_states, sn)

    def auto_out_up_move(self, machine_cfg, runtime_cfg, plc_data, frame_queue):
        sn = int(machine_cfg.get("sn", 0) or 0)
        WorkpieceMotionHelper.ensure_state(self._work_states, sn, lambda: {"state": "wait_front_outside"})

        block = WorkpieceMotionHelper.peek_first_block(frame_queue)
        if block is None:
            self.reset_motion_state(sn)
            return {"y": self._build_idle_axis()}, False, False

        ctx = WorkpieceMotionHelper.build_block_context(machine_cfg, runtime_cfg, plc_data, block)
        if not self.motion_util.check_if_cabinet(block, self.x_range, self.y_range, self.z_range):
            done = self._has_after_over_arrived(ctx)
            if done:
                self.reset_motion_state(sn)
            return {"y": self._build_idle_axis()}, done, False

        axis_cmds, done = self._handle_out_up_spray(ctx)
        return axis_cmds, done, False

    def _handle_out_up_spray(self, ctx):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        state_name = self._work_states[sn].get("state", "wait_front_outside")
        handler = self._dispatch_table_out_up().get(state_name, self._state_wait_front_outside)
        return handler(ctx)

    def _dispatch_table_out_up(self):
        return {
            "wait_front_outside": self._state_wait_front_outside,
            "spray_outside": self._state_spray_outside,
            "finish": self._state_finish,
        }

    def _state_wait_front_outside(self, ctx):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        self._log_outside_z_trace(ctx, "wait_front_outside")
        axis_cmds = {"y": self._build_idle_axis()}
        if self._has_front_arrived(ctx) or self._has_front_over_arrived(ctx):
            self._work_states[sn]["state"] = "spray_outside"
            logger.info(f"SN[{sn}] out_up arrived front outside, start spray")
        return axis_cmds, False

    def _state_spray_outside(self, ctx):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        self._log_outside_z_trace(ctx, "spray_outside")
        chain_running = self._is_chain_running(ctx["plc_data"])
        status = 1 if chain_running and self._is_spray_enabled(ctx) else 0
        axis_cmds = {"y": self._build_axis(status=status)}
        if self._has_after_arrived(ctx) or self._has_after_over_arrived(ctx):
            self._work_states[sn]["state"] = "finish"
            logger.info(f"SN[{sn}] out_up arrived after outside, finish spray")
        return axis_cmds, False

    @staticmethod
    def _is_chain_running(plc_data):
        return getattr(plc_data, "ChainStatus", "stopped") in ("moving_forward", "moving_reverse")

    def _state_finish(self, ctx):
        sn = int(ctx["machine_cfg"].get("sn", 0) or 0)
        self.reset_motion_state(sn)
        logger.info(f"SN[{sn}] out_up finish spraying")
        return {"y": self._build_idle_axis()}, True

    @staticmethod
    def _build_axis(status: int):
        return build_axis(0, 0, status)

    def _build_idle_axis(self):
        return self._build_axis(status=0)

    def _is_spray_enabled(self, ctx):
        sn_value = ctx["machine_cfg"].get("sn", None)
        sn = -1 if sn_value is None else int(sn_value)
        if WorkpieceMotionHelper.find_enabled_gun(ctx["block_data"], sn) is not None:
            return True
        logger.warning(f"SN[{sn}] out_up missing precomputed gun distribution, keep spray disabled")
        return False

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
            f"SN[{sn}] out_up state={state_name}, "
            f"front_z_machine={front_z_machine}, front_z_chain={front_z_chain}, "
            f"after_z_machine={after_z_machine}, after_z_chain={after_z_chain}, "
            f"fifo_frame_pos={ctx['fifo_frame_pos']}, "
            f"outside_z_min={int(getattr(outside, 'outside_z_min', 0) or 0)}, "
            f"outside_z_max={int(getattr(outside, 'outside_z_max', 0) or 0)}"
        )
