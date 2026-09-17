from model.motionplan.MachineAxisMap import apply_device_axes_to_list
from model.motionplan.MotionCleaningPlanning import MotionCleaningPlanning
from model.motionplan.MotionToTarget import MotionToTarget
from model.plc.MovingFrameData import SendMovingFrameData
from model.utils.LoggerUtil import logger


class MotionContinuousBidirectionalPlanning:
    """第三模式统一运动规划入口。"""

    def __init__(self):
        self.cleaning_planner = MotionCleaningPlanning()
        self.motion_to_target = MotionToTarget()

    def build_moving_frame(self, proc) -> SendMovingFrameData:
        """生成包含激光轴、工位放行和全部喷涂设备轴的PLC运动帧。"""
        clean_mode_requested = self.cleaning_planner.is_clean_mode_enabled(proc.plc_data.Operate)
        release_status = 0
        if proc.continuous_scan.stage != "fault" and not clean_mode_requested:
            release_status = proc.frame_queue_manager.update_continuous_stations(int(proc.plc_data.Status))

        allow_scan = proc.frame_queue_manager.continuous_slot_empty(0) and not proc.continuous_scan_pending and not clean_mode_requested
        moving_frame = proc.continuous_scan.update(proc.plc_data, ready=proc.continuous_lidar_ready and proc.lidar_status == 0, allow_scan=allow_scan)

        if proc.continuous_scan.stage == "scanning":
            proc.continuous_scan_pending = True
        if proc.continuous_scan.stage != "fault":
            moving_frame.Status |= release_status

        self._build_device_safe_motion(proc, moving_frame)
        return moving_frame

    def _build_device_safe_motion(self, proc, moving_frame: SendMovingFrameData):
        """生成安全回位或清理指令，不修改激光轴。"""
        plc_status = int(proc.plc_data.Status or 0)
        plc_operate = int(proc.plc_data.Operate or 0)
        plc_enable = bool(plc_operate & 0x01)
        servo_alarm = not bool(plc_status & 0x01)
        lidar_abnormal = int(getattr(proc, "lidar_status", 0) or 0) in (1, 2, 3)
        force_disable_all = (not plc_enable) or servo_alarm or lidar_abnormal or proc.continuous_scan.stage == "fault"

        clean_mode_enabled, clean_mode_ready, clean_mode_just_closed = self.cleaning_planner.resolve_continuous_mode_state(
            plc_operate, proc.last_operate_state, proc.frame_queue_manager, force_disable_all
        )

        device_operate = 0
        effective_operate = 0 if force_disable_all else plc_operate
        for sn in range(proc.num_devices):
            machine_cfg = proc.machine_config.get(str(sn))
            if not machine_cfg:
                continue
            runtime_cfg = self._safe_return_runtime_config(proc.runtime_machine_config.get(sn, {}), machine_cfg)

            device_bit = sn + 1
            device_operate_enabled = bool(effective_operate & (1 << device_bit))
            last_device_operate = bool(proc.last_operate_state & (1 << device_bit))
            device_just_closed = last_device_operate and not device_operate_enabled
            should_return_safe = proc.device_returning_to_origin.get(sn, False) or device_just_closed or clean_mode_just_closed

            if clean_mode_enabled:
                axis_cmds = self.cleaning_planner.build_device_axis_cmds(machine_cfg, runtime_cfg, clean_mode_ready)
                all_ready = False
                proc.device_returning_to_origin[sn] = False
                proc.device_origin_complete[sn] = False
                device_operate |= 1 << device_bit
            elif device_operate_enabled or should_return_safe:
                axis_cmds, all_ready = self.motion_to_target.move_to_origin_safe(machine_cfg, runtime_cfg, proc.plc_data)
                proc.device_origin_complete[sn] = bool(all_ready)
                proc.device_returning_to_origin[sn] = not bool(all_ready)
                if not force_disable_all and (device_operate_enabled or not all_ready):
                    device_operate |= 1 << device_bit
            else:
                axis_cmds = self.motion_to_target.hold_current_position(machine_cfg, proc.plc_data)
                all_ready = proc.device_origin_complete.get(sn, False)

            if axis_cmds:
                apply_device_axes_to_list(proc.machine_config, sn, axis_cmds, moving_frame.AxisList)

        # Operate的bit0由激光状态机生成，bit1至bit4由设备运动规划生成。
        moving_frame.Operate = (int(moving_frame.Operate) & 0x01) | device_operate
        proc.last_operate_state = plc_operate
        logger.debug("Continuous motion frame: servo_alarm=%s, cleaning=%s, cleaning_ready=%s, Operate=%s", servo_alarm, clean_mode_enabled, clean_mode_ready, moving_frame.Operate)

    @staticmethod
    def _safe_return_runtime_config(runtime_cfg: dict, machine_cfg: dict) -> dict:
        """把第三模式的Z回位速度转换为通用安全回位规划器使用的参数。"""
        result = dict(runtime_cfg or {})
        if "z_zeroing_speed" not in result:
            result["z_zeroing_speed"] = result.get("z_back_speed", machine_cfg.get("z_back_speed", 100))
        return result
