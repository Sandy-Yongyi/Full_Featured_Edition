import os
from model.utils.LoggerUtil import logger
from model.utils.TomlLoader import TomlLoader
from model.motionplan.motionutil.AxisLimits import build_axis, clamp_to_limit_yx
from model.motionplan.MachineAxisMap import get_axis_position_limits, get_axis_speed_limit, get_axis_map
from model.motionplan.MotionToTarget import MotionToTarget
from model.motionplan.motionutil.FrameSearchHelper import FrameSearchHelper


class MotionInLiftPlanning:
    """内侧二维往复机自动喷涂规划。"""

    def __init__(self):
        self.spray_cfg = TomlLoader.load(os.path.join(os.getcwd(), "model", "tomls", "SprayConfig.toml"))
        self.read_data_cfg = TomlLoader.load(os.path.join(os.getcwd(), "model", "tomls", "ReadDataConfig.toml"))
        self.motion_to_target = MotionToTarget()
        self.z_threshold = int(self.read_data_cfg.get("z_threshold", 10))
        self.x_threshold = int(self.read_data_cfg.get("x_threshold", 10))
        self.spray_pos_tolerance = int(self.spray_cfg.get("spray_pos_tolerance", 10))
        self.frame_helper = FrameSearchHelper(z_threshold=self.z_threshold)
        self._work_states = {}

    def reset_motion_state(self, sn=None):
        if sn is None:
            self._work_states = {}
            return
        self._work_states.pop(int(sn), None)

    def auto_in_lift_move(self, machine_cfg, runtime_cfg, spray_cfg, plc_data, frame_queue_manager):
        sn = int(machine_cfg.get("sn", 0))
        state = self._work_states.setdefault(sn, self._create_initial_state())
        upper_direction = self.frame_helper.get_upper_direction(machine_cfg)
        if upper_direction not in frame_queue_manager.frame_stack:
            self._reset_safe_state(state)
            return self._build_safe_axis_cmds(machine_cfg, runtime_cfg, plc_data), False, False

        frames = self.frame_helper.get_upper_frames(machine_cfg, frame_queue_manager)
        chain_running = self._is_chain_running(plc_data)

        if not frames:
            logger.warning(f"SN[{sn}] in_lift upper frames not ready")
            return self._build_safe_axis_cmds(machine_cfg, runtime_cfg, plc_data), False, False

        detection = self._find_jump_target(machine_cfg, runtime_cfg, spray_cfg, frames)
        start_detected = self._is_start_detected(machine_cfg, runtime_cfg, spray_cfg, frames)

        if not start_detected or detection is None:
            if state.get("state") != "safe":
                logger.info(f"SN[{sn}] in_lift jump not found, returning to safe position")
            self._reset_safe_state(state)
            return self._build_safe_axis_cmds(machine_cfg, runtime_cfg, plc_data), False, False

        if state.get("state") != "reciprocate":
            logger.info(
                f"SN[{sn}] in_lift reciprocation started, x_target={detection['x_target']}, "
                f"y_range=({detection['y_min_target']}, {detection['y_max_target']})"
            )
            state["state"] = "reciprocate"
            state["y_phase"] = "to_max"

        axis_cmds = self.motion_to_target.hold_current_position(machine_cfg, plc_data)
        axis_cmds["x"] = self._build_x_axis(machine_cfg, runtime_cfg, chain_running, detection["x_target"])
        axis_cmds["y"] = self._build_y_reciprocate_axis(
            machine_cfg,
            runtime_cfg,
            plc_data,
            state,
            detection["y_min_target"],
            detection["y_max_target"],
        )

        logger.info(
            f"SN[{sn}] in_lift active, chain_running={chain_running}, x_target={detection['x_target']}, "
            f"y_range=({detection['y_min_target']}, {detection['y_max_target']})"
        )
        return axis_cmds, False, False

    def _create_initial_state(self):
        return {"state": "safe", "y_phase": "to_max"}

    def _reset_safe_state(self, state):
        state["state"] = "safe"
        state["y_phase"] = "to_max"

    def _build_safe_axis_cmds(self, machine_cfg, runtime_cfg, plc_data):
        axis_cmds, _ = self.motion_to_target.move_to_origin_safe(machine_cfg, runtime_cfg, plc_data)
        if axis_cmds is None:
            axis_cmds = self.motion_to_target.hold_current_position(machine_cfg, plc_data)
        return axis_cmds

    def _is_start_detected(self, machine_cfg, runtime_cfg, spray_cfg, frames):
        z_origin_idx = self._get_after_z_pos(machine_cfg, runtime_cfg)
        plus_frame = self.frame_helper.get_frame_by_index(frames, z_origin_idx + 5)
        minus_frame = self.frame_helper.get_frame_by_index(frames, z_origin_idx - 5)
        max_row_idx = self._get_x_scan_row_limit(spray_cfg)
        _, plus_y_max = self.frame_helper.scan_vertical_range_by_row_window(plus_frame, 0, max_row_idx)
        _, minus_y_max = self.frame_helper.scan_vertical_range_by_row_window(minus_frame, 0, max_row_idx)
        if plus_y_max is None or minus_y_max is None:
            return False
        y_jump_threshold = int(spray_cfg.get("y_jump_threshold", self.spray_cfg.get("y_jump_threshold", 1000)))
        return int(plus_y_max) - int(minus_y_max) > y_jump_threshold

    def _find_jump_target(self, machine_cfg, runtime_cfg, spray_cfg, frames):
        z_after_idx = self._get_after_z_pos(machine_cfg, runtime_cfg)
        z_front_idx = self._get_front_z_pos(machine_cfg, runtime_cfg)
        x_scan_row_limit = self._get_x_scan_row_limit(spray_cfg)
        y_jump_threshold = int(spray_cfg.get("y_jump_threshold", self.spray_cfg.get("y_jump_threshold", 1000)))

        for z_idx in self.frame_helper.iter_window_indices(z_after_idx, z_front_idx):
            frame = self.frame_helper.get_frame_by_index(frames, z_idx)
            jump_data = self._find_jump_in_frame(frame, x_scan_row_limit, y_jump_threshold)
            if jump_data is None:
                continue
            return self._build_detection_result(machine_cfg, runtime_cfg, jump_data)
        return None

    def _find_jump_in_frame(self, frame, x_scan_row_limit, y_jump_threshold):
        if frame is None or not getattr(frame, "FrameData", None):
            return None

        max_row = min(int(x_scan_row_limit), len(frame.FrameData) - 1)
        if max_row < 0:
            return None

        for row_idx in range(0, max_row + 1):
            backward_start = max(0, row_idx - 5)
            backward_end = max(0, row_idx - 1)
            forward_start = row_idx
            forward_end = min(max_row, row_idx + 5)

            if backward_end < backward_start:
                continue

            _, backward_y_max = self.frame_helper.scan_vertical_range_by_row_window(frame, backward_start, backward_end)
            forward_y_min, forward_y_max = self.frame_helper.scan_vertical_range_by_row_window(frame, forward_start, forward_end)
            if backward_y_max is None or forward_y_max is None or forward_y_min is None:
                continue

            if int(forward_y_max) - int(backward_y_max) > y_jump_threshold:
                jump_x_mm = row_idx * self.x_threshold
                return {
                    "jump_x_mm": jump_x_mm,
                    "y_min_abs": int(forward_y_min),
                    "y_max_abs": int(forward_y_max),
                }
        return None

    def _build_detection_result(self, machine_cfg, runtime_cfg, jump_data):
        x_min_limit, x_max_limit = get_axis_position_limits(machine_cfg, "x")
        y_min_limit, y_max_limit = get_axis_position_limits(machine_cfg, "y")
        spray_radius = int(machine_cfg.get("spray_radius", 0))
        x_position = int(machine_cfg.get("x_position", 0) or 0)
        x_offset = int(runtime_cfg.get("in_front_x_offset", machine_cfg.get("in_front_x_offset", 0)))
        y_offset = int(runtime_cfg.get("in_up_y_offset", machine_cfg.get("in_up_y_offset", 0)))
        y_origin = self._get_y_origin_pos(machine_cfg)

        x_target = clamp_to_limit_yx(int(jump_data["jump_x_mm"]) - x_offset - x_position - spray_radius, x_min_limit, x_max_limit)
        y_min_target = clamp_to_limit_yx(int(jump_data["y_min_abs"]) - y_offset - y_origin, y_min_limit, y_max_limit)
        y_max_target = clamp_to_limit_yx(int(jump_data["y_max_abs"]) - y_offset - y_origin, y_min_limit, y_max_limit)
        if y_min_target > y_max_target:
            y_min_target, y_max_target = y_max_target, y_min_target

        return {
            "x_target": x_target,
            "y_min_target": y_min_target,
            "y_max_target": y_max_target,
        }

    def _get_x_scan_row_limit(self, spray_cfg):
        x_scan_max = int(spray_cfg.get("x_scan_max", self.spray_cfg.get("x_scan_max", 500)))
        return max(0, int(x_scan_max / self.x_threshold))

    def _build_x_axis(self, machine_cfg, runtime_cfg, chain_running, x_target):
        x_speed = int(runtime_cfg.get("x_pos_speed", machine_cfg.get("x_pos_speed", 300)))
        status = 1 if chain_running else 0
        return build_axis(int(x_target), x_speed, status, get_axis_speed_limit(machine_cfg, "x"))

    def _build_y_reciprocate_axis(self, machine_cfg, runtime_cfg, plc_data, state, y_min_target, y_max_target):
        y_speed = int(runtime_cfg.get("y_recip_speed", machine_cfg.get("y_recip_speed", 100)))
        y_speed_limit = get_axis_speed_limit(machine_cfg, "y")
        y_min_limit, y_max_limit = get_axis_position_limits(machine_cfg, "y")
        y_min_target = clamp_to_limit_yx(int(y_min_target), y_min_limit, y_max_limit)
        y_max_target = clamp_to_limit_yx(int(y_max_target), y_min_limit, y_max_limit)
        if y_min_target > y_max_target:
            y_min_target, y_max_target = y_max_target, y_min_target

        y_cur = self._get_axis_pos(machine_cfg, plc_data, "y")
        phase = state.get("y_phase", "to_max")
        target = y_max_target if phase == "to_max" else y_min_target

        if abs(y_cur - target) <= self.spray_pos_tolerance:
            phase = "to_min" if phase == "to_max" else "to_max"
            state["y_phase"] = phase
            target = y_max_target if phase == "to_max" else y_min_target

        return build_axis(target, y_speed, 0, y_speed_limit)

    def _get_front_z_pos(self, machine_cfg, runtime_cfg):
        z_position = int(machine_cfg.get("z_position", 0))
        z_front_offset = int(runtime_cfg.get("in_z_front_offset", machine_cfg.get("in_z_front_offset", 0)))
        return max(0, int((z_position - z_front_offset) / self.z_threshold))

    def _get_after_z_pos(self, machine_cfg, runtime_cfg):
        z_position = int(machine_cfg.get("z_position", 0))
        z_after_offset = int(runtime_cfg.get("in_z_after_offset", machine_cfg.get("in_z_after_offset", 0)))
        return max(0, int((z_position + z_after_offset) / self.z_threshold))

    def _get_y_origin_pos(self, machine_cfg):
        origin_pos = machine_cfg.get("origin_pos", [])
        if isinstance(origin_pos, (list, tuple)) and len(origin_pos) > 0:
            return int(origin_pos[0] or 0)
        return 0

    def _get_axis_pos(self, machine_cfg, plc_data, axis_name):
        axis_map = get_axis_map(machine_cfg.get("type", ""), machine_cfg.get("install_orietation", "left"))
        return self.motion_to_target._get_axis_current_pos(plc_data, axis_map[axis_name])

    def _is_chain_running(self, plc_data):
        return getattr(plc_data, "ChainStatus", "stopped") in ("moving_forward", "moving_reverse")
