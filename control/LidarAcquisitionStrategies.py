"""
激光雷达采数策略模块
支持三种采数策略：
1. ContinuousBidirectional - 双向连续采数
2. FrameByFrame - 逐帧采数发送
3. CompleteWorkpiece - 完整工件采集
"""

import time
import numpy as np
from abc import ABC, abstractmethod
from typing import Dict
from model.utils.LoggerUtil import logger
from model.utils.StrategyUtil import (
    COMPLETE_WORKPIECE_STRATEGY,
    CONTINUOUS_BIDIRECTIONAL_STRATEGY,
    FRAME_QUEUE_STRATEGY,
    validate_strategy_name,
)


class AcquisitionStrategy(ABC):
    """采数策略抽象基类"""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def monitor_movement(self, process_instance):
        """监测运动并采集数据"""
        pass

    @abstractmethod
    def update_scanning_state(self, process_instance, direction: str, state, same_origin_filtered, diff_origin_filtered):
        """更新扫描状态"""
        pass

    @abstractmethod
    def save_valid_data(self, process_instance):
        """保存有效数据"""
        pass

    @abstractmethod
    def check_scanning_completion(self, process_instance):
        """检查扫描是否完成"""
        pass

    @abstractmethod
    def send_raw_data(self, process_instance):
        """发送原始数据"""
        pass

    @abstractmethod
    def send_direction_data(self, process_instance, direction_data: Dict):
        """发送方向数据（逐帧发送）"""
        pass

    @abstractmethod
    def reset_for_next_workpiece(self, process_instance):
        """重置为下一个工件"""
        pass


class ContinuousBidirectionalStrategy(AcquisitionStrategy):
    """
    策略1: 双向连续采数
    - 从0到3000或3000到0不间断采数
    - 只在开始和结束时间断
    - 采完后一次性发送数据
    """

    def monitor_movement(self, proc):
        """以固定端点划分一趟扫描；回零时PLC发布stopped，不进入采集。"""
        start = int(proc.read_data_config.get("min_swing_pulse", 0))
        end = int(proc.read_data_config["max_swing_pulse"])
        tolerance = proc.scan_position_tolerance
        proc.continuous_scan_invalid = False
        proc.continuous_last_saved_pulse = None
        while not proc.shutdown_flag:
            proc._heartbeat.touch()
            pulse, _, status = proc._update_pulse_data()
            if getattr(proc, "continuous_wait_for_idle", False):
                if status not in ("moving_forward", "moving_reverse"):
                    proc.continuous_wait_for_idle = False
                    # 确认旧扫描已停止，允许PLC空走到端点后反向重采。
                    proc._push_lidar_status_update(reset_queue=True)
                proc._poll_lidar_status_if_due()
                proc._heartbeat.sleep(0.01)
                continue
            if proc.plc_disconnected:
                proc.continuous_scan_invalid = True
                break
            if proc.movement_detected:
                reached = pulse >= end - tolerance if proc.capture_direction == "forward" else pulse <= start + tolerance
                if reached and status == "stopped":
                    # PLC到端点后可能已经发布stopped，先判端点再判停止。
                    if pulse != proc.continuous_last_saved_pulse:
                        proc._capture_frame()
                    if proc.finish_test:
                        proc.continuous_scan_invalid = True
                        break
                    for state in proc.direction_states.values():
                        state.scanning_started = False
                        state.stop_pulse = pulse
                    proc.any_scanning_active = False
                    proc.finish_test = True
                    break
                expected = "moving_forward" if proc.capture_direction == "forward" else "moving_reverse"
                if status != expected:
                    proc.continuous_scan_invalid = True
                    logger.warning("Continuous scan interrupted before endpoint, discard current pass")
                    break
            elif status in ("moving_forward", "moving_reverse"):
                proc.capture_direction = "forward" if status == "moving_forward" else "reverse"
                proc.movement_detected = True
                for state in proc.direction_states.values():
                    state.scanning_started = True
                    state.has_scanned = True
                    state.start_pulse = pulse
            else:
                proc._poll_lidar_status_if_due()
                proc._heartbeat.sleep(0.01)
                continue

            if pulse != proc.continuous_last_saved_pulse:
                proc._capture_frame()
            if proc.finish_test:
                proc.continuous_scan_invalid = True
                break
            proc._heartbeat.sleep(0.01)

        if proc.continuous_scan_invalid or proc.shutdown_flag:
            proc.continuous_scan_invalid = True
            proc.continuous_wait_for_idle = True
            # 异常中断不得将残缺点云保存或交付为完整工件。
            proc._reset_base()
            proc._push_lidar_status_update()

    def update_scanning_state(self, proc, direction: str, state, same_origin_filtered, diff_origin_filtered):
        """在此策略中由监测方法控制"""
        pass

    def save_valid_data(self, proc):
        """沿用脉冲转毫米，保留实际扫描位置，不减有点起点或扫描起点。"""
        proc._save_valid_data_core(proc.current_pulse / float(proc.read_data_config["pulse_to_mm"]))
        proc.continuous_last_saved_pulse = proc.current_pulse

    def check_scanning_completion(self, proc):
        """由finish_test标志控制"""
        pass

    def send_raw_data(self, proc):
        """一次性发送所有数据"""
        if getattr(proc, "continuous_scan_invalid", False):
            return
        # 直接向PLC进程发送整趟XYZ点云，不经过分区处理。
        same_origin = int(proc.read_data_config["translate_data_origin"]) == 1
        raw_data = {
            "lidar_status": proc.lidar_status,
            "translate_data_origin": int(proc.read_data_config["translate_data_origin"]),
        }
        directions = set(proc.lidar_config)
        if same_origin:
            directions.update(("left", "right"))
            raw_data["all_data"] = proc.all_xyz_data
            raw_data["all_stop_pulse"] = proc.current_pulse
        for direction in sorted(directions):
            state = proc.direction_states.get(direction)
            points = proc.all_xyz_data if same_origin else getattr(state, "xyz_data", np.empty((0, 3)))
            raw_data[f"{direction}_data"] = points
            stop_pulse = getattr(state, "stop_pulse", None)
            raw_data[f"{direction}_stop_pulse"] = proc.current_pulse if stop_pulse is None else stop_pulse
        if any(isinstance(value, np.ndarray) and value.size > 0 for key, value in raw_data.items() if key.endswith("_data")):
            proc.raw_data_queue.put(raw_data)
            logger.info("Continuous whole-workpiece raw points sent directly to PLC process")

    def send_direction_data(self, proc, direction_data: Dict):
        """点云仍按整趟交付，激光状态每次采集及时通知PLC联锁。"""
        proc._push_lidar_status_update()

    def reset_for_next_workpiece(self, proc):
        """重置状态"""
        proc._reset_base()


class FrameByFrameStrategy(AcquisitionStrategy):
    """
    策略2: 逐帧采数发送
    - 只允许正向运动
    - 采集一帧就发送一帧
    - 支持首启动跳过逻辑
    """

    def monitor_movement(self, proc):
        """单向逐帧采数"""
        logger.info("Waiting for forward movement to start...")

        while True:
            if proc.shutdown_flag:
                break
            _, _, status = proc._update_pulse_data()

            if status == "moving_forward":
                if not proc.movement_detected:
                    logger.info("Forward motion start")
                    print("开始采集数据...")
                    proc.movement_detected = True
                    # 首启动记录起始脉冲
                    if proc.software_first_start and proc.start_motion_pulse is None:
                        proc.start_motion_pulse = proc.current_pulse
                        logger.info(f"[FrameByFrame StartupGuard] start_motion_pulse={proc.start_motion_pulse}")
                proc._capture_frame()
            else:
                proc._poll_lidar_status_if_due()
                time.sleep(0.01)

            if proc.finish_test:
                # 首启跳过模式中，不退出循环，重置扫描状态后继续监测下一个工件
                if proc.fbf_skipping_workpiece or proc.fbf_skip_complete:
                    logger.info("[FrameByFrame StartupGuard] Skipped workpiece cycle ended, continuing monitoring")
                    if proc.fbf_skipping_workpiece:
                        proc.fbf_skipping_workpiece = False
                        proc.fbf_skip_complete = True
                    proc.finish_test = False
                    proc.movement_detected = False
                    proc.all_xyz_data = np.empty((0, 3))
                    for state in proc.direction_states.values():
                        state.reset()
                    continue
                logger.info("Forward capture finished, saving data...")
                print("当前工件采集完成，正在保存数据...")
                break
            time.sleep(0.01)

    def update_scanning_state(self, proc, direction: str, state, same_origin_filtered, diff_origin_filtered):
        """更新扫描状态"""
        proc._update_scanning_state_base(direction, state)

    def save_valid_data(self, proc):
        """保存有效数据"""
        current_pulse, _, _ = proc._update_pulse_data()
        proc._save_valid_data_core(proc._get_current_scan_z_value(current_pulse))

    def check_scanning_completion(self, proc):
        """检查扫描是否完成"""
        proc._check_scanning_completion_default()

    def send_raw_data(self, proc):
        """逐帧发送已在send_direction_data中处理"""
        pass

    def send_direction_data(self, proc, direction_data: Dict):
        """逐帧调用send_data_to_queue发送FIFO数据，含首启动跳过逻辑"""

        # ---- 首启动检测：判断是否需要进入跳过模式 ----
        if proc.software_first_start and not proc.fbf_skipping_workpiece and not proc.fbf_skip_complete:
            has_data = any(
                isinstance(darr, np.ndarray) and darr.size > 0
                for darr in direction_data.values()
            )
            if has_data and proc.start_motion_pulse is not None:
                pulse_diff = proc._get_forward_pulse_diff(proc.start_motion_pulse, proc.current_pulse)
                moved_mm = pulse_diff / proc.read_data_config["pulse_to_mm"]
                if moved_mm <= proc.read_data_config["start_skip_mm"]:
                    proc.fbf_skipping_workpiece = True
                    proc.fbf_empty_frame_count = 0
                    logger.info(f"[FrameByFrame StartupGuard] Workpiece in middle detected, skip mode. moved_mm={moved_mm:.1f}")
                    proc._push_lidar_status_update()
                    return
                else:
                    proc.software_first_start = False
                    logger.info(f"[FrameByFrame StartupGuard] Normal start beyond skip zone. moved_mm={moved_mm:.1f}")

        # ---- 跳过模式：不发送帧，等待工件离开（连续100帧空数据） ----
        if proc.fbf_skipping_workpiece:
            all_empty = all(
                (darr is None) or (isinstance(darr, np.ndarray) and darr.size == 0)
                or (isinstance(darr, list) and len(darr) == 0)
                for darr in direction_data.values()
            )
            if all_empty:
                proc.fbf_empty_frame_count += 1
                if proc.fbf_empty_frame_count >= 100:
                    proc.fbf_skipping_workpiece = False
                    proc.fbf_skip_complete = True
                    logger.info("[FrameByFrame StartupGuard] 100 consecutive empty frames, workpiece passed")
            else:
                proc.fbf_empty_frame_count = 0
            proc._push_lidar_status_update()
            return

        # ---- 跳过完成，等待新工件数据才恢复发送 ----
        if proc.fbf_skip_complete:
            has_data = any(
                isinstance(darr, np.ndarray) and darr.size > 0
                for darr in direction_data.values()
            )
            if has_data:
                proc.fbf_skip_complete = False
                proc.software_first_start = False
                logger.info("[FrameByFrame StartupGuard] New workpiece detected, resuming normal send")
            else:
                proc._push_lidar_status_update()
                return

        # ---- 正常发送 ----
        proc.send_data_to_queue(direction_data)

    def reset_for_next_workpiece(self, proc):
        """重置状态"""
        if hasattr(proc, 'software_first_start') and proc.software_first_start:
            proc.software_first_start = False
        proc.cm_accum.clear()
        proc._reset_base()


class CompleteWorkpieceStrategy(AcquisitionStrategy):
    """
    策略3: 完整工件采集
    - 复杂的启停判断逻辑
    - FIFO和pulse二维管理
    - 累积式缓存处理
    """

    def monitor_movement(self, proc):
        """完整工件采集监测"""
        logger.info("Waiting for forward movement to start...")
        last_status = "stopped"
        while True:
            if proc.shutdown_flag:
                break
            _, _, status = proc._update_pulse_data()

            if status == "moving_forward":
                if last_status in ("stopped", "moving_forward"):
                    if not proc.movement_detected:
                        logger.info("Forward motion start")
                        print("开始采集数据...")
                        proc.movement_detected = True
                        if proc.software_first_start and proc.start_motion_pulse is None:
                            proc.start_motion_pulse = proc.current_pulse
                            logger.info(f"[StartupGuard] start_motion_pulse={proc.start_motion_pulse}")
                proc._capture_frame()
            else:
                proc._poll_lidar_status_if_due()
                time.sleep(0.01)
            last_status = status

            if proc.finish_test:
                logger.info("Forward capture finished, saving data...")
                print("当前工件采集完成，正在保存数据...")
                break
            time.sleep(0.01)

    def update_scanning_state(self, proc, direction: str, state, same_origin_filtered, diff_origin_filtered):
        """更新扫描状态 - 含链接停止和停止原因标记"""
        stopped_by_points, stopped_by_max_length = proc._update_scanning_state_base(direction, state)
        if stopped_by_points:
            state.stop_reason = "points"
            state.is_link_anchor = True
        elif stopped_by_max_length:
            state.stop_reason = "max_length"
        proc._check_linked_stop_continuous()

    def save_valid_data(self, proc):
        """保存有效数据 - 完整工件模式"""
        if not proc.any_scanning_active:
            return
        current_pulse, _, _ = proc._update_pulse_data()
        proc._save_valid_data_core(proc._get_current_scan_z_value(current_pulse))

    def check_scanning_completion(self, proc):
        """检查扫描是否完成"""
        proc._check_scanning_completion_default()

    def send_raw_data(self, proc):
        """发送完整工件数据（对应LidarAcquisitionProcess2的_send_raw_data）"""
        translate_data_origin = int(proc.read_data_config.get("translate_data_origin", 2) or 2)
        raw_data = {
            "lidar_status": proc.lidar_status,
            "translate_data_origin": translate_data_origin,
        }

        direction_stop_pulses = {}
        valid_stop_pulses = []
        for direction, lidar_ids in proc.lidar_config.items():
            if not lidar_ids or len(lidar_ids) == 0:
                continue
            state = proc.direction_states.get(direction)
            if not state:
                continue
            stop_pulse = getattr(state, "stop_pulse", None)
            direction_stop_pulses[direction] = stop_pulse
            # None表示该方向没有完成扫描；真实脉冲0必须作为有效停止脉冲保留。
            if stop_pulse is not None:
                valid_stop_pulses.append(stop_pulse)

        common_stop_pulse = max(valid_stop_pulses) if valid_stop_pulses else 0

        if translate_data_origin == 1:
            for direction, stop_pulse in direction_stop_pulses.items():
                if stop_pulse is None:
                    raw_data[f"{direction}_stop_pulse"] = common_stop_pulse
                    logger.warning(f"Direction '{direction}' did not scan; use common stop pulse {common_stop_pulse}")
                else:
                    raw_data[f"{direction}_stop_pulse"] = stop_pulse

            if isinstance(proc.all_xyz_data, np.ndarray) and proc.all_xyz_data.size > 0:
                raw_data["all_data"] = proc.all_xyz_data
                raw_data["all_stop_pulse"] = common_stop_pulse

            proc.raw_data_queue.put(raw_data)
            logger.info("Raw data sent to processing queue (same origin)")
            return

        for direction, lidar_ids in proc.lidar_config.items():
            if not lidar_ids or len(lidar_ids) == 0:
                logger.debug(f"Skip sending data for direction '{direction}' (no lidar configured)")
                continue
            state = proc.direction_states.get(direction)
            if not state:
                continue

            stop_pulse = direction_stop_pulses.get(direction)
            if stop_pulse is None:
                raw_data[f"{direction}_stop_pulse"] = common_stop_pulse
                logger.warning(f"Direction '{direction}' did not scan; use common stop pulse {common_stop_pulse}")
            else:
                raw_data[f"{direction}_stop_pulse"] = stop_pulse
            raw_data[f"{direction}_data"] = getattr(state, "xyz_data", 0)

        proc.raw_data_queue.put(raw_data)
        logger.info("Raw data sent to processing queue")

    def send_direction_data(self, proc, direction_data: Dict):
        """完整工件模式不逐帧发送，只在首启动阶段用逐帧数据判断是否跳过当前工件。"""
        if getattr(proc, "complete_skip_current_workpiece", False):
            return
        if not getattr(proc, "software_first_start", False):
            return
        if proc.start_motion_pulse is None:
            return

        has_data = any(
            isinstance(darr, np.ndarray) and darr.size > 0
            for darr in direction_data.values()
        )
        if not has_data:
            return

        pulse_diff = proc._get_forward_pulse_diff(proc.start_motion_pulse, proc.current_pulse)
        moved_mm = pulse_diff / float(proc.read_data_config.get("pulse_to_mm", 1) or 1)
        start_skip_mm = float(proc.read_data_config.get("start_skip_mm", 0) or 0)
        if moved_mm <= start_skip_mm:
            proc.complete_skip_current_workpiece = True
            logger.info(
                f"[CompleteWorkpiece StartupGuard] Workpiece in middle detected, skip current workpiece. "
                f"moved_mm={moved_mm:.1f}, start_skip_mm={start_skip_mm:.1f}"
            )
            return

        proc.software_first_start = False
        logger.info(
            f"[CompleteWorkpiece StartupGuard] Normal start beyond skip zone. "
            f"moved_mm={moved_mm:.1f}, start_skip_mm={start_skip_mm:.1f}"
        )

    def reset_for_next_workpiece(self, proc):
        """重置状态"""
        if proc.software_first_start:
            proc.software_first_start = False
        if hasattr(proc, "complete_skip_current_workpiece"):
            proc.complete_skip_current_workpiece = False
        proc._reset_base()


class AcquisitionStrategyFactory:
    """采数策略工厂"""

    STRATEGIES = {
        CONTINUOUS_BIDIRECTIONAL_STRATEGY: ContinuousBidirectionalStrategy,
        FRAME_QUEUE_STRATEGY: FrameByFrameStrategy,
        COMPLETE_WORKPIECE_STRATEGY: CompleteWorkpieceStrategy,
    }

    @staticmethod
    def create_strategy(strategy_name: str, config: dict) -> AcquisitionStrategy:
        """创建策略实例"""
        strategy_name = validate_strategy_name(strategy_name)
        strategy_class = AcquisitionStrategyFactory.STRATEGIES[strategy_name]
        return strategy_class(config)
