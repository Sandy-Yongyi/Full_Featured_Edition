import os
from model.utils.LoggerUtil import logger
from model.utils.TomlLoader import TomlLoader
from model.motionplan.motionutil.AxisLimits import build_axis, clamp_to_limit_yx, clamp_to_limit_z, clamp_to_limit_r
from model.motionplan.MachineAxisMap import get_axis_position_limits, get_axis_speed_limit, get_axis_map
from model.motionplan.motionutil.FrameSearchHelper import FrameSearchHelper
from model.motionplan.MotionToTarget import MotionToTarget


class MotionOutRotatePlanning:
    """外侧翻转轴自动喷涂规划。"""

    def __init__(self):
        self.spray_cfg = TomlLoader.load(os.path.join(os.getcwd(), "model", "tomls", "SprayConfig.toml"))
        self.read_data_cfg = TomlLoader.load(os.path.join(os.getcwd(), "model", "tomls", "ReadDataConfig.toml"))
        self.motion_to_target = MotionToTarget()
        self.z_threshold = int(self.read_data_cfg.get("z_threshold", 10))
        self.y_threshold = int(self.read_data_cfg.get("y_threshold", 10))
        self.spray_pos_tolerance = int(self.spray_cfg.get("spray_pos_tolerance", 10))
        self.out_rotate_frame_threshold = int(self.spray_cfg.get("out_rotate_frame_threshold", 5) or 5)
        self.frame_helper = FrameSearchHelper(z_threshold=self.z_threshold)
        self._work_states = {}

    def reset_motion_state(self, sn=None):
        if sn is None:
            self._work_states = {}
            return
        self._work_states.pop(int(sn), None)

    def request_finish_after_current_recip(self, sn):
        state = self._work_states.get(int(sn))
        if state is None:
            return False
        current_state = state.get("state")
        if current_state not in ("recip_front_outside", "recip_after_outside"):
            return False
        state["pending_finish_after_recip"] = True
        logger.info(f"SN[{sn}] Device close requested during {current_state}, will finish current reciprocation before returning to origin")
        return True

    def should_continue_after_disable(self, sn):
        state = self._work_states.get(int(sn))
        if state is None:
            return False
        return bool(state.get("pending_finish_after_recip", False))

    def auto_out_rotate_move(self, machine_cfg, runtime_cfg, spray_cfg, plc_data, frame_queue_manager):
        sn = int(machine_cfg.get("sn", 0))
        spray_plan = self._get_spray_plan(machine_cfg, runtime_cfg)
        state = self._work_states.get(sn)
        if state is None or state.get("spray_plan") != spray_plan:
            state = self._create_initial_state(spray_plan)
            self._work_states[sn] = state
        frames = self.frame_helper.get_side_frames(machine_cfg, frame_queue_manager)

        if not frames:
            logger.warning(f"SN[{sn}] out_rotate side frames not ready")
            return self.motion_to_target.hold_current_position(machine_cfg, plc_data), False, False

        current_state = state["state"]
        logger.info(f"SN[{sn}] out_rotate state={current_state}")

        if current_state == "wait_front_outside":
            return self._state_wait_front_outside(machine_cfg, runtime_cfg, spray_cfg, plc_data, frames, state)
        if current_state == "wait_after_outside":
            return self._state_wait_after_outside(machine_cfg, runtime_cfg, plc_data, frames, state)
        if current_state == "recip_front_outside":
            return self._state_recip_front_outside(machine_cfg, runtime_cfg, spray_cfg, plc_data, frames, state)
        if current_state == "return_origin_before_bottom":
            return self._state_return_origin_before_bottom(machine_cfg, runtime_cfg, plc_data, state)
        if current_state == "bottom_reciprocate":
            return self._state_bottom_reciprocate(machine_cfg, runtime_cfg, spray_cfg, plc_data, frames, state)
        if current_state == "return_origin_before_after":
            return self._state_return_origin_before_after(machine_cfg, runtime_cfg, plc_data, state)
        if current_state == "recip_after_outside":
            return self._state_recip_after_outside(machine_cfg, runtime_cfg, spray_cfg, plc_data, frames, state)
        if current_state == "return_origin_before_finish":
            return self._state_return_origin_before_finish(machine_cfg, runtime_cfg, plc_data, state)

        self.reset_motion_state(sn)
        return self.motion_to_target.hold_current_position(machine_cfg, plc_data), True, False

    def _create_initial_state(self, spray_plan=0):
        return {
            "state": self._get_initial_state_by_plan(spray_plan),
            "x_phase": "to_max",
            "front_y_phase": "to_max",
            "front_cycles": 0,
            "after_y_phase": "to_max",
            "after_cycles": 0,
            "spray_plan": spray_plan,
            "after_seen_workpiece": False,
            "pending_finish_after_recip": False,
        }

    def _get_spray_plan(self, machine_cfg, runtime_cfg):
        spray_plan = runtime_cfg.get("spray_plan", machine_cfg.get("spray_plan", 0))
        try:
            spray_plan = int(spray_plan)
        except (TypeError, ValueError):
            spray_plan = 0
        return spray_plan if spray_plan in (0, 1, 2, 3) else 0

    def _get_initial_state_by_plan(self, spray_plan):
        if spray_plan == 3:
            return "wait_after_outside"
        return "wait_front_outside"

    def _state_wait_front_outside(self, machine_cfg, runtime_cfg, spray_cfg, plc_data, frames, state):
        sn = int(machine_cfg.get("sn", 0))
        spray_plan = state.get("spray_plan", 0)

        if spray_plan == 2:
            axis_cmds = self._build_wait_outside_axis_cmds(machine_cfg, runtime_cfg, plc_data, 0)
            if self._workpiece_present_in_range(machine_cfg, runtime_cfg, frames):
                state["state"] = "bottom_reciprocate"
                state["x_phase"] = "to_max"
                logger.info(f"SN[{sn}] First workpiece data detected in Z range, entering bottom reciprocation")
                return self._state_bottom_reciprocate(machine_cfg, runtime_cfg, spray_cfg, plc_data, frames, state)

            logger.debug(f"SN[{sn}] Waiting for first workpiece data in Z range before bottom reciprocation")
            return axis_cmds, False, False

        z_position = int(machine_cfg.get("z_position", 0))
        z_front_pos = self._get_front_z_pos(machine_cfg, runtime_cfg)
        z_after_pos = self._get_after_z_pos(machine_cfg, runtime_cfg)
        is_mid_open = self._is_mid_open_in_outside_window(frames, z_front_pos, z_after_pos, side="front")
        axis_cmds = self._build_wait_outside_axis_cmds(machine_cfg, runtime_cfg, plc_data, 0 if is_mid_open else -90)

        if is_mid_open:
            self.reset_motion_state(sn)
            logger.warning(
                f"SN[{sn}] Motion enabled when workpiece already reached out_rotate middle area at front side, "
                f"mark spraying finished without motion"
            )
            return axis_cmds, True, False

        if self._is_front_outside_arrived(frames, z_front_pos, z_position):
            state["state"] = "recip_front_outside"
            state["front_y_phase"] = "to_max"
            state["front_cycles"] = 0
            logger.info(
                f"SN[{sn}] Front outside data detected, stopping chain and entering front outside reciprocation, "
                f"z_range=({z_front_pos}, {z_position})"
            )
            return axis_cmds, False, True

        logger.debug(f"SN[{sn}] Waiting for front outside arrival, z_range=({z_front_pos}, {z_position})")
        return axis_cmds, False, False

    def _state_wait_after_outside(self, machine_cfg, runtime_cfg, plc_data, frames, state):
        sn = int(machine_cfg.get("sn", 0))
        z_position = int(machine_cfg.get("z_position", 0))
        z_front_pos = self._get_front_z_pos(machine_cfg, runtime_cfg)
        z_after_pos = self._get_after_z_pos(machine_cfg, runtime_cfg)
        is_mid_open = self._is_mid_open_in_outside_window(frames, z_front_pos, z_after_pos, side="after")
        axis_cmds = self._build_wait_outside_axis_cmds(machine_cfg, runtime_cfg, plc_data, 0 if is_mid_open else 90)

        if is_mid_open:
            self.reset_motion_state(sn)
            logger.warning(
                f"SN[{sn}] Motion enabled when workpiece already reached out_rotate middle area at rear side, "
                f"mark spraying finished without motion"
            )
            return axis_cmds, True, False

        if self._is_after_outside_arrived(frames, z_position, z_after_pos):
            state["state"] = "recip_after_outside"
            state["x_phase"] = "to_max"
            state["after_y_phase"] = "to_max"
            state["after_cycles"] = 0
            logger.info(
                f"SN[{sn}] Rear outside data detected, stopping chain and entering rear outside reciprocation, "
                f"z_range=({z_position}, {z_after_pos})"
            )
            return axis_cmds, False, True

        logger.debug(f"SN[{sn}] Waiting for rear outside arrival, z_range=({z_position}, {z_after_pos})")
        return axis_cmds, False, False

    def _state_recip_front_outside(self, machine_cfg, runtime_cfg, spray_cfg, plc_data, frames, state):
        sn = int(machine_cfg.get("sn", 0))
        _, start_limit, end_limit = self._get_stage_z_window_from_limits(machine_cfg)
        z_front_pos = self._get_front_z_pos(machine_cfg, runtime_cfg)
        axis_cmds = self._build_stage_axis_cmds(
            machine_cfg=machine_cfg,
            runtime_cfg=runtime_cfg,
            spray_cfg=spray_cfg,
            plc_data=plc_data,
            frames=frames,
            z_pos=z_front_pos,
            start_offset=start_limit,
            end_offset=end_limit,
            y_phase_key="front_y_phase",
            cycle_key="front_cycles",
            follow_mode="front",
            keep_z_follow=True,
        )
        done = self._is_stage_cycle_complete(machine_cfg, runtime_cfg, state, "front_cycles")
        if done:
            spray_plan = state.get("spray_plan", 0)
            if state.get("pending_finish_after_recip", False) or spray_plan == 1:
                state["state"] = "return_origin_before_finish"
                logger.info(f"SN[{sn}] Front outside reciprocation complete, returning to origin before finish")
            else:
                state["state"] = "return_origin_before_bottom"
                logger.info(f"SN[{sn}] Front outside reciprocation complete, returning to origin before bottom reciprocation")
        return axis_cmds, False, True

    def _state_return_origin_before_bottom(self, machine_cfg, runtime_cfg, plc_data, state):
        sn = int(machine_cfg.get("sn", 0))
        axis_cmds, all_ready = self.motion_to_target.move_to_origin_safe(machine_cfg, runtime_cfg, plc_data)
        if axis_cmds is None:
            axis_cmds = self.motion_to_target.hold_current_position(machine_cfg, plc_data)

        if all_ready:
            state["state"] = "bottom_reciprocate"
            state["x_phase"] = "to_max"
            logger.info(f"SN[{sn}] All axes returned to origin, bottom reciprocation can start")
            return axis_cmds, False, False

        logger.info(f"SN[{sn}] Returning all axes to origin before bottom reciprocation")
        return axis_cmds, False, True

    def _state_bottom_reciprocate(self, machine_cfg, runtime_cfg, spray_cfg, plc_data, frames, state):
        sn = int(machine_cfg.get("sn", 0))
        axis_cmds = self.motion_to_target.hold_current_position(machine_cfg, plc_data)
        x_axis = self._build_x_reciprocate_axis(machine_cfg, runtime_cfg, spray_cfg, plc_data, state, use_chain_speed=False)
        y_axis = self._build_bottom_y_axis(machine_cfg, runtime_cfg, plc_data, frames)
        z_axis = self._build_zero_z_axis(machine_cfg, runtime_cfg)
        r_axis = self._build_r_axis(machine_cfg, 0)

        if x_axis is not None:
            axis_cmds["x"] = x_axis
        if y_axis is not None:
            axis_cmds["y"] = y_axis
        if z_axis is not None:
            axis_cmds["z"] = z_axis
        if r_axis is not None:
            axis_cmds["r"] = r_axis

        if self._bottom_scan_empty(machine_cfg, runtime_cfg, frames):
            spray_plan = state.get("spray_plan", 0)
            if spray_plan == 2:
                state["state"] = "return_origin_before_finish"
                logger.info(f"SN[{sn}] Bottom reciprocation complete, returning to origin before finish")
            else:
                state["state"] = "return_origin_before_after"
                state["after_y_phase"] = "to_max"
                state["after_cycles"] = 0
                logger.info(f"SN[{sn}] Bottom reciprocation complete, returning to origin before rear outside reciprocation")
            return axis_cmds, False, True

        return axis_cmds, False, False

    def _state_return_origin_before_after(self, machine_cfg, runtime_cfg, plc_data, state):
        sn = int(machine_cfg.get("sn", 0))
        axis_cmds, all_ready = self.motion_to_target.move_to_origin_safe(machine_cfg, runtime_cfg, plc_data)
        if axis_cmds is None:
            axis_cmds = self.motion_to_target.hold_current_position(machine_cfg, plc_data)

        if all_ready:
            state["state"] = "recip_after_outside"
            state["x_phase"] = "to_max"
            logger.info(f"SN[{sn}] All axes returned to origin, rear outside reciprocation can start")
            return axis_cmds, False, True

        logger.info(f"SN[{sn}] Returning all axes to origin before rear outside reciprocation")
        return axis_cmds, False, False

    def _state_recip_after_outside(self, machine_cfg, runtime_cfg, spray_cfg, plc_data, frames, state):
        sn = int(machine_cfg.get("sn", 0))
        _, start_limit, end_limit = self._get_stage_z_window_from_limits(machine_cfg)
        z_after_pos = self._get_after_z_pos(machine_cfg, runtime_cfg)
        axis_cmds = self._build_stage_axis_cmds(
            machine_cfg=machine_cfg,
            runtime_cfg=runtime_cfg,
            spray_cfg=spray_cfg,
            plc_data=plc_data,
            frames=frames,
            z_pos=z_after_pos,
            start_offset=start_limit,
            end_offset=end_limit,
            y_phase_key="after_y_phase",
            cycle_key="after_cycles",
            follow_mode="after",
            keep_z_follow=True,
        )
        done = self._is_stage_cycle_complete(machine_cfg, runtime_cfg, state, "after_cycles")
        if done:
            state["state"] = "return_origin_before_finish"
            logger.info(f"SN[{sn}] Rear outside reciprocation complete, returning to origin before finish")
            return axis_cmds, False, True
        return axis_cmds, False, True

    def _state_return_origin_before_finish(self, machine_cfg, runtime_cfg, plc_data, state):
        sn = int(machine_cfg.get("sn", 0))
        axis_cmds, all_ready = self.motion_to_target.move_to_origin_safe(machine_cfg, runtime_cfg, plc_data)
        if axis_cmds is None:
            axis_cmds = self.motion_to_target.hold_current_position(machine_cfg, plc_data)

        if all_ready:
            self.reset_motion_state(sn)
            logger.info(f"SN[{sn}] All axes returned to origin, spraying finished and chain released")
            return axis_cmds, True, False

        logger.info(f"SN[{sn}] Returning all axes to origin before finish")
        return axis_cmds, False, True

    def _workpiece_present_in_range(self, machine_cfg, runtime_cfg, frames):
        start_idx = self._get_front_z_pos(machine_cfg, runtime_cfg, include_spray_radius=False)
        end_idx = self._get_after_z_pos(machine_cfg, runtime_cfg, include_spray_radius=False)
        y_min, y_max = self.frame_helper.scan_y_range(frames, start_idx, end_idx)
        return y_min is not None and y_max is not None

    def _is_front_outside_arrived(self, frames, front_idx, after_idx, band_frames: int | None = None):
        """前外侧到达：前边界到前边界+N帧都有数据，直到后边界前其余帧无数据。"""
        band_frames = self.out_rotate_frame_threshold if band_frames is None else int(band_frames)
        front_idx = max(0, int(front_idx))
        after_idx = min(len(frames) - 1, int(after_idx))
        band_end = front_idx + int(band_frames)
        if front_idx > after_idx or band_end > after_idx:
            return False

        for idx in range(front_idx, band_end + 1):
            if not self.frame_helper.frame_has_data(self.frame_helper.get_frame_by_index(frames, idx)):
                return False

        for idx in range(band_end + 1, after_idx + 1):
            if self.frame_helper.frame_has_data(self.frame_helper.get_frame_by_index(frames, idx)):
                return False
        return True

    def _is_mid_open_in_outside_window(self, frames, front_idx, after_idx, side: str, band_frames: int | None = None):
        """中间打开判定：边界侧连续 N+1 帧有数据，且搜索范围剩余部分仍有数据。"""
        band_frames = self.out_rotate_frame_threshold if band_frames is None else int(band_frames)
        front_idx = max(0, int(front_idx))
        after_idx = min(len(frames) - 1, int(after_idx))
        if front_idx > after_idx:
            return False

        if side == "front":
            band_end = front_idx + int(band_frames)
            if band_end > after_idx:
                return False

            for idx in range(front_idx, band_end + 1):
                if not self.frame_helper.frame_has_data(self.frame_helper.get_frame_by_index(frames, idx)):
                    return False

            return any(
                self.frame_helper.frame_has_data(self.frame_helper.get_frame_by_index(frames, idx))
                for idx in range(band_end + 1, after_idx + 1)
            )

        band_start = after_idx - int(band_frames)
        if band_start < front_idx:
            return False

        for idx in range(band_start, after_idx + 1):
            if not self.frame_helper.frame_has_data(self.frame_helper.get_frame_by_index(frames, idx)):
                return False

        return any(
            self.frame_helper.frame_has_data(self.frame_helper.get_frame_by_index(frames, idx))
            for idx in range(front_idx, band_start)
        )

    def _is_after_outside_arrived(self, frames, front_idx, after_idx, band_frames: int | None = None):
        """后外侧到达：后边界-N帧到后边界都有数据，前边界到其前一帧无数据。"""
        band_frames = self.out_rotate_frame_threshold if band_frames is None else int(band_frames)
        front_idx = max(0, int(front_idx))
        after_idx = min(len(frames) - 1, int(after_idx))
        band_start = after_idx - int(band_frames)
        if front_idx > after_idx or band_start < front_idx:
            return False

        for idx in range(band_start, after_idx + 1):
            if not self.frame_helper.frame_has_data(self.frame_helper.get_frame_by_index(frames, idx)):
                return False

        for idx in range(front_idx, band_start):
            if self.frame_helper.frame_has_data(self.frame_helper.get_frame_by_index(frames, idx)):
                return False
        return True

    def _build_stage_axis_cmds(self, machine_cfg, runtime_cfg, spray_cfg, plc_data, frames,
                               z_pos, start_offset, end_offset, y_phase_key, cycle_key,
                               follow_mode, keep_z_follow):
        axis_cmds = self.motion_to_target.hold_current_position(machine_cfg, plc_data)
        window_start = z_pos + start_offset
        window_end = z_pos + end_offset
        y_min, y_max = self.frame_helper.scan_y_range(frames, window_start, window_end)

        if y_min is None or y_max is None:
            logger.warning(f"SN[{machine_cfg.get('sn', 0)}] No valid Y data found in scan window, holding current position")
            return axis_cmds

        x_axis = self._build_x_reciprocate_axis(
            machine_cfg,
            runtime_cfg,
            spray_cfg,
            plc_data,
            self._work_states[int(machine_cfg.get("sn", 0))],
            use_chain_speed=False,
        )
        y_axis = self._build_y_reciprocate_axis(machine_cfg, runtime_cfg, plc_data, y_min, y_max, y_phase_key, cycle_key)
        if keep_z_follow:
            z_axis = self._build_follow_z_axis(
                machine_cfg,
                runtime_cfg,
                plc_data,
                frames,
                z_pos,
                window_start,
                window_end,
                follow_mode,
            )
        else:
            z_axis = self._build_zero_z_axis(machine_cfg, runtime_cfg)
        if follow_mode == "front":
            r_axis = self._build_r_axis(machine_cfg, -90)
        elif follow_mode == "after":
            r_axis = self._build_r_axis(machine_cfg, 90)
        else:
            r_axis = self._build_hold_axis(machine_cfg, plc_data, "r")

        if x_axis is not None:
            axis_cmds["x"] = x_axis
        if y_axis is not None:
            axis_cmds["y"] = y_axis
        if z_axis is not None:
            axis_cmds["z"] = z_axis
        if r_axis is not None:
            axis_cmds["r"] = r_axis
        return axis_cmds

    def _build_wait_outside_axis_cmds(self, machine_cfg, runtime_cfg, plc_data, r_angle):
        """等待前/后外端时的固定等待姿态：xyz -> 0，r -> 指定角度。"""
        axis_cmds = self.motion_to_target.hold_current_position(machine_cfg, plc_data)
        x_speed = int(runtime_cfg.get("x_pos_speed", machine_cfg.get("x_pos_speed", 300)))
        y_speed = int(runtime_cfg.get("y_pos_speed", machine_cfg.get("y_pos_speed", 100)))
        z_speed = int(runtime_cfg.get("z_zeroing_speed", machine_cfg.get("z_zeroing_speed", 100)))

        for axis_name in machine_cfg.get("axis_type", []):
            min_limit, max_limit = get_axis_position_limits(machine_cfg, axis_name)
            axis_speed_limit = get_axis_speed_limit(machine_cfg, axis_name)

            if axis_name.startswith("x"):
                axis_cmds[axis_name] = build_axis(
                    clamp_to_limit_yx(0, min_limit, max_limit),
                    x_speed,
                    0,
                    axis_speed_limit,
                )
            elif axis_name == "y":
                axis_cmds[axis_name] = build_axis(
                    clamp_to_limit_yx(0, min_limit, max_limit),
                    y_speed,
                    0,
                    axis_speed_limit,
                )
            elif axis_name == "z":
                axis_cmds[axis_name] = build_axis(
                    clamp_to_limit_z(0, min_limit, max_limit),
                    z_speed,
                    0,
                    axis_speed_limit,
                )
            elif axis_name == "r":
                axis_cmds[axis_name] = self._build_r_axis(machine_cfg, r_angle)

        return axis_cmds

    def _get_stage_z_window_from_limits(self, machine_cfg):
        z_position = int(machine_cfg.get("z_position", 0) or 0)
        z_min_limit, z_max_limit = get_axis_position_limits(machine_cfg, "z")
        z_pos = int(z_position // self.z_threshold)
        start_limit = int(z_min_limit // self.z_threshold)
        end_limit = int(z_max_limit // self.z_threshold)
        return z_pos, start_limit, end_limit

    def _build_x_reciprocate_axis(self, machine_cfg, runtime_cfg, spray_cfg, plc_data, state, use_chain_speed=False):
        x_speed = int(runtime_cfg.get("x_recip_speed", machine_cfg.get("x_recip_speed", 300)))
        x_speed_limit = get_axis_speed_limit(machine_cfg, "x")
        if use_chain_speed:
            chain_running = int(getattr(plc_data, "ChainSpeed", 0) or 0) != 0
        else:
            chain_running = self._is_chain_running(plc_data)
        x_status = 1 if chain_running else 0
        x_min_limit, x_max_limit = get_axis_position_limits(machine_cfg, "x")
        x_min = int(spray_cfg.get("size_x_min", self.spray_cfg.get("size_x_min", 0)))
        x_max = int(spray_cfg.get("size_x_max", self.spray_cfg.get("size_x_max", 350)))
        if x_min > x_max:
            x_min, x_max = x_max, x_min
        x_min = clamp_to_limit_yx(x_min, x_min_limit, x_max_limit)
        x_max = clamp_to_limit_yx(x_max, x_min_limit, x_max_limit)

        x_cur = self._get_axis_pos(machine_cfg, plc_data, "x")
        phase = state.get("x_phase", "to_max")

        if x_cur > x_max:
            state["x_phase"] = "to_min"
            return build_axis(x_min, x_speed, x_status, x_speed_limit)

        if x_cur < x_min:
            state["x_phase"] = "to_max"
            return build_axis(x_max, x_speed, x_status, x_speed_limit)

        target = x_max if phase == "to_max" else x_min

        if abs(x_cur - target) <= self.spray_pos_tolerance:
            phase = "to_min" if phase == "to_max" else "to_max"
            state["x_phase"] = phase
            target = x_max if phase == "to_max" else x_min

        return build_axis(target, x_speed, x_status, x_speed_limit)

    def _build_y_reciprocate_axis(self, machine_cfg, runtime_cfg, plc_data, y_min, y_max, y_phase_key, cycle_key):
        sn = int(machine_cfg.get("sn", 0))
        state = self._work_states[sn]
        y_recip_speed = int(runtime_cfg.get("y_recip_speed", machine_cfg.get("y_recip_speed", 100)))
        y_speed_limit = get_axis_speed_limit(machine_cfg, "y")
        y_min_limit, y_max_limit = get_axis_position_limits(machine_cfg, "y")
        y_origin = self._get_y_origin_pos(machine_cfg)
        if y_min > y_max:
            y_min, y_max = y_max, y_min
        y_min = clamp_to_limit_yx(int(y_min) - y_origin, y_min_limit, y_max_limit)
        y_max = clamp_to_limit_yx(int(y_max) - y_origin, y_min_limit, y_max_limit)

        y_cur = self._get_axis_pos(machine_cfg, plc_data, "y")

        if y_cur > y_max:
            state[y_phase_key] = "to_min"
            return build_axis(y_min, y_recip_speed, 0, y_speed_limit)

        if y_cur < y_min:
            state[y_phase_key] = "to_max"
            return build_axis(y_max, y_recip_speed, 0, y_speed_limit)

        phase = state.get(y_phase_key, "to_max")
        target = y_max if phase == "to_max" else y_min

        if abs(y_cur - target) <= self.spray_pos_tolerance:
            if phase == "to_max":
                state[y_phase_key] = "to_min"
                target = y_min
            else:
                state[cycle_key] = int(state.get(cycle_key, 0)) + 1
                total_cycles = int(runtime_cfg.get("outside_total_cycles", machine_cfg.get("outside_total_cycles", 2)))
                if state[cycle_key] >= total_cycles:
                    target = y_min
                else:
                    state[y_phase_key] = "to_max"
                    target = y_max

        return build_axis(target, y_recip_speed, 0, y_speed_limit)

    def _build_bottom_y_axis(self, machine_cfg, runtime_cfg, plc_data, frames):
        y_pos_speed = int(runtime_cfg.get("y_pos_speed", machine_cfg.get("y_pos_speed", 100)))
        y_speed_limit = get_axis_speed_limit(machine_cfg, "y")
        y_min_limit, y_max_limit = get_axis_position_limits(machine_cfg, "y")
        y_min = self._scan_bottom_y_min(machine_cfg, runtime_cfg, frames)
        if y_min is None:
            return self._build_hold_axis(machine_cfg, plc_data, "y")

        spray_radius = int(machine_cfg.get("spray_radius", 0))
        y_offset = int(runtime_cfg.get("out_down_y_offset", machine_cfg.get("out_down_y_offset", 0)))
        y_origin = self._get_y_origin_pos(machine_cfg)
        bottom_recip_y_max = int(self.spray_cfg.get("bottom_recip_y_max", y_max_limit))

        if int(y_min) > bottom_recip_y_max:
            return self._build_hold_axis(machine_cfg, plc_data, "y")

        target = clamp_to_limit_yx(int(y_min) - (y_offset + spray_radius) - y_origin, y_min_limit, y_max_limit)
        return build_axis(target, y_pos_speed, 0, y_speed_limit)

    def _build_follow_z_axis(self, machine_cfg, runtime_cfg, plc_data, frames, z_pos, window_start, window_end, follow_mode):
        z_speed = int(runtime_cfg.get("z_zeroing_speed", machine_cfg.get("z_zeroing_speed", 100)))
        z_speed_limit = get_axis_speed_limit(machine_cfg, "z")
        z_min_limit, z_max_limit = get_axis_position_limits(machine_cfg, "z")
        y_cur = self._get_axis_pos(machine_cfg, plc_data, "y")
        y_origin = self._get_y_origin_pos(machine_cfg)
        y_offset = int(runtime_cfg.get("out_up_y_offset", machine_cfg.get("out_up_y_offset", 0)))
        y_center = y_cur + y_origin
        y_lower = y_center - y_offset
        y_upper = y_center + y_offset

        matched_indices = []
        for idx in self.frame_helper.iter_window_indices(window_start, window_end):
            frame = self.frame_helper.get_frame_by_index(frames, idx)
            if self.frame_helper.frame_has_y_in_band(frame, y_lower, y_upper):
                matched_indices.append(idx)

        if not matched_indices:
            return self._build_hold_axis(machine_cfg, plc_data, "z")

        if follow_mode == "front":
            target_idx = max(matched_indices)
            delta_mm = (z_min_limit + target_idx) * self.z_threshold
        else:
            target_idx = min(matched_indices)
            delta_mm = (z_max_limit - target_idx) * self.z_threshold

        target = clamp_to_limit_z(delta_mm, z_min_limit, z_max_limit)
        return build_axis(target, z_speed, 0, z_speed_limit)

    def _build_zero_z_axis(self, machine_cfg, runtime_cfg):
        z_speed = int(runtime_cfg.get("z_zeroing_speed", machine_cfg.get("z_zeroing_speed", 100)))
        return build_axis(0, z_speed, 0, get_axis_speed_limit(machine_cfg, "z"))

    def _build_r_axis(self, machine_cfg, angle):
        r_speed_limit = get_axis_speed_limit(machine_cfg, "r")
        r_min_limit, r_max_limit = get_axis_position_limits(machine_cfg, "r")
        target = clamp_to_limit_r(int(angle), r_min_limit, r_max_limit)
        return build_axis(target, r_speed_limit, 0, r_speed_limit)

    def _build_hold_axis(self, machine_cfg, plc_data, axis_name):
        try:
            cur_pos = self._get_axis_pos(machine_cfg, plc_data, axis_name)
        except Exception:
            return None
        return build_axis(cur_pos, 0, 0, get_axis_speed_limit(machine_cfg, axis_name))

    def _get_y_origin_pos(self, machine_cfg):
        origin_pos = machine_cfg.get("origin_pos", [])
        if isinstance(origin_pos, (list, tuple)) and len(origin_pos) > 0:
            return int(origin_pos[0] or 0)
        return 0

    def _get_front_z_pos(self, machine_cfg, runtime_cfg, include_spray_radius=True):
        z_position = int(machine_cfg.get("z_position", 0))
        spray_radius = int(machine_cfg.get("spray_radius", 0)) if include_spray_radius else 0
        z_front_offset = int(runtime_cfg.get("out_z_front_offset", machine_cfg.get("out_z_front_offset", 0)))
        return max(0, int((z_position - (z_front_offset + spray_radius)) / self.z_threshold))

    def _get_after_z_pos(self, machine_cfg, runtime_cfg, include_spray_radius=True):
        z_position = int(machine_cfg.get("z_position", 0))
        spray_radius = int(machine_cfg.get("spray_radius", 0)) if include_spray_radius else 0
        z_after_offset = int(runtime_cfg.get("out_z_after_offset", machine_cfg.get("out_z_after_offset", 0)))
        return max(0, int((z_position + (z_after_offset + spray_radius)) / self.z_threshold))

    def _scan_bottom_y_min(self, machine_cfg, runtime_cfg, frames):
        start_idx = self._get_front_z_pos(machine_cfg, runtime_cfg, include_spray_radius=True)
        end_idx = self._get_after_z_pos(machine_cfg, runtime_cfg, include_spray_radius=True)
        return self.frame_helper.scan_y_min(frames, start_idx, end_idx)

    def _bottom_scan_empty(self, machine_cfg, runtime_cfg, frames):
        return self._scan_bottom_y_min(machine_cfg, runtime_cfg, frames) is None

    def _is_stage_cycle_complete(self, machine_cfg, runtime_cfg, state, cycle_key):
        total_cycles = int(runtime_cfg.get("outside_total_cycles", machine_cfg.get("outside_total_cycles", 2)))
        return int(state.get(cycle_key, 0)) >= total_cycles

    def _get_axis_pos(self, machine_cfg, plc_data, axis_name):
        axis_map = get_axis_map(machine_cfg.get("type", ""), machine_cfg.get("install_orietation", "left"))
        idx = axis_map[axis_name]
        axis_list = self._get_plc_axis_container(plc_data)
        if idx >= len(axis_list):
            return 0
        item = axis_list[idx]
        if hasattr(item, "Pos"):
            return int(getattr(item, "Pos", 0) or 0)
        if isinstance(item, (list, tuple)) and len(item) > 0:
            return int(item[0] or 0)
        if isinstance(item, dict):
            return int(item.get("Pos", 0) or 0)
        return 0

    def _get_plc_axis_container(self, plc_data):
        axis_list = getattr(plc_data, "AxisList", None)
        if axis_list is not None:
            return axis_list
        axis_list = getattr(plc_data, "Axis_List", None)
        if axis_list is not None:
            return axis_list
        return []

    @staticmethod
    def _is_chain_running(plc_data):
        return getattr(plc_data, "ChainStatus", "stopped") in ("moving_forward", "moving_reverse")
