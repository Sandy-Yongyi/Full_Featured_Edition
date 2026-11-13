"""
统一的激光雷达采数处理类 - 支持三种采数策略
"""

import multiprocessing
import os
import sys
import time
import queue
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Dict
from model.utils.TomlLoader import TomlLoader
from acquisition_sdk._internal.lidar.LidarCommon import LidarManager
from acquisition_sdk._internal.dataprocess.DataSplitting import DataSplitting
from model.utils.LoggerUtil import logger, check_and_rotate_log
from acquisition_sdk._internal.dataprocess.DataFilter import DataFilter
from acquisition_sdk._internal.lidar.LidarDirectionState import LidarDirectionState
from acquisition_sdk._internal.pointcloud.PointCloudSaveBuffer import PointCloudSaveBuffer
from model.utils.LidarDirectionUtil import filter_active_direction_map
from model.utils.StrategyUtil import is_complete_workpiece_mode, is_continuous_bidirectional_mode, is_frame_by_frame_mode, validate_strategy_name
from model.utils.ProcessHeartbeat import ProcessHeartbeat
from model.utils.UiTelemetry import UiStatusPublisher
from acquisition_sdk._internal.lidar.LidarAcquisitionStrategies import AcquisitionStrategyFactory


class LidarAcquisitionProcess(multiprocessing.Process):
    def _text(self, chinese, english):
        return english if is_continuous_bidirectional_mode(self.strategy_name) else chinese

    """
    统一的激光雷达采数处理类
    支持三种策略: continuous_bidirectional, frame_by_frame, complete_workpiece
    """

    def __init__(self, pulse_queue, raw_data_queue, viz_queue, lidar_config: dict, config_dir: str,
                 strategy_name: str = "frame_by_frame", heartbeat=None, heartbeat_interval_s: float = 1.0,
                 save_pool_descriptor=None, save_task_queue=None, save_ack_queue=None,
                 save_status_queue=None, stop_event=None):
        """
        初始化采数处理

        Args:
            pulse_queue: 脉冲数据队列
            raw_data_queue: 原始数据输出队列
            viz_queue: 可视化数据队列
            lidar_config: 激光雷达配置
            config_dir: 配置目录
            strategy_name: 采数策略名称
        """
        super().__init__()

        self.config_dir = config_dir
        self.lidar_config = filter_active_direction_map(lidar_config)
        self.strategy_name = validate_strategy_name(strategy_name)
        self.pulse_queue = pulse_queue
        self.viz_queue = viz_queue
        self.raw_data_queue = raw_data_queue
        self._heartbeat = ProcessHeartbeat(heartbeat, heartbeat_interval_s)
        self.ui_status = UiStatusPublisher(None, "lidar")
        self.read_data_config = TomlLoader.load(f"{config_dir}\\ReadDataConfig.toml")
        self.scan_position_tolerance = int(TomlLoader.load(f"{config_dir}\\SprayConfig.toml")["spray_pos_tolerance"])
        self.process_config = TomlLoader.load(f"{config_dir}\\ProcessConfig.toml")
        self.draw_type = int(self.read_data_config.get("draw_type", 1))

        # 创建策略
        self.strategy = AcquisitionStrategyFactory.create_strategy(strategy_name, self.read_data_config)

        # 基础状态
        self.current_pulse = 0
        self.current_status = "stopped"
        self.movement_detected = False
        self.finish_test = False
        self.shutdown_flag = False
        self.lidar_status = 0
        self.last_reported_lidar_status = 0
        self.lidar_disconnected = False
        self.plc_disconnected = False
        self.plc_connection_generation = 0
        self.lidar_reconnected = False
        self.plc_reconnected = False
        self.any_scanning_active = False
        self.scan_base_pulse = None
        self.last_lidar_status_poll_time = 0.0
        self.lidar_status_poll_interval = float(self.read_data_config.get("lidar_status_poll_interval_s", 0.5) or 0.5)

        # 数据存储
        self.data_dir = Path(os.getcwd() + "\\data")
        self.data_dir.mkdir(exist_ok=True)
        self.all_xyz_data = np.empty((0, 3))
        self.save_pool_descriptor = save_pool_descriptor
        self.save_task_queue = save_task_queue
        self.save_ack_queue = save_ack_queue
        self.save_status_queue = save_status_queue
        self.stop_event = stop_event
        self.save_buffer = None
        self._processing_chunks = {}
        self._save_job_counter = 0
        self._last_log_check = 0.0
        self._buffer_warning = False

        # 方向状态
        self.direction_states: Dict = {}
        for direction in self.lidar_config.keys():
            config_to_use = self.read_data_config
            self.direction_states[direction] = LidarDirectionState(direction, config_to_use)

        # 确定有配置的方向列表（避免重复检查空配置）
        self.active_directions = list(self.lidar_config.keys())
        logger.debug(f"Active directions with lidar configuration: {self.active_directions}")

        # 策略特定初始化
        self._init_strategy_attributes()

        # 标准输出
        self.stdout = sys.stdout
        self.stderr = sys.stderr

    def _init_strategy_attributes(self):
        """初始化"""
        # 所有策略都需要这些基础属性
        self.max_fifo = self._get_max_chaincountcm()

        if is_continuous_bidirectional_mode(self.strategy_name):
            self.capture_direction = None

        elif is_frame_by_frame_mode(self.strategy_name):
            from acquisition_sdk._internal.dataprocess.frame_by_frame.BuildSideFrame import build_side_frame
            self.build_side_frame = build_side_frame
            self.cm_accum: Dict = {}
            self.last_sent_fifo = -1
            # 首启动跳过逻辑（工件在中间检测）
            self.software_first_start = True
            self.start_motion_pulse = None
            self.fbf_skipping_workpiece = False
            self.fbf_empty_frame_count = 0
            self.fbf_skip_complete = False

        elif is_complete_workpiece_mode(self.strategy_name):
            self.software_first_start = True
            self.start_motion_pulse = None
            self.complete_skip_current_workpiece = False

    def _get_max_chaincountcm(self) -> int:
        """基于 pulse 重置阈值推导 chaincountcm 的最大值。"""
        max_pulse = float(self.read_data_config.get("max_pulse", 160000) or 160000)
        pulse_to_mm = float(self.read_data_config.get("pulse_to_mm", 1) or 1)
        return max(1, int(round(max_pulse / pulse_to_mm / 10)))

    def _is_next_fifo(self, last_fifo: int, current_fifo: int) -> bool:
        """判断 chaincountcm 是否按 pulse 回绕规则前进 1。"""
        expected_fifo = (int(last_fifo) + 1) % (self.max_fifo + 1)
        return int(current_fifo) == expected_fifo

    def run(self):
        """主程序入口"""
        logger.info(f"LidarAcquisitionProcess.run() entered, pid={os.getpid()}")
        self._heartbeat.touch(force=True)

        if hasattr(self, "stdout"):
            sys.stdout = self.stdout
        if hasattr(self, "stderr"):
            sys.stderr = self.stderr

        try:
            if self.save_pool_descriptor is None or self.save_task_queue is None:
                raise RuntimeError("Point cloud saving requires a sibling save process and shared memory pool")
            self.save_buffer = PointCloudSaveBuffer(self.save_pool_descriptor, self.save_ack_queue)
            if not self._initialize_connections():
                print(self._text("激光连接失败，请检查连接并重新运行软件", "Lidar connection failed. Check the connection and restart the software."))
                logger.error("Lidar connection failed")
                return
            print(self._text(f"成功连接所有激光，启动采集策略: {self.strategy_name}", f"All lidars connected. Acquisition strategy: {self.strategy_name}"))
            self._init_direction_states()  # 初始化所有方向的状态数据
            self._acquisition_loop()

        except Exception as e:
            logger.exception(f"Unexpected error: {str(e)}")
            if self.save_status_queue is not None:
                self.save_status_queue.put({"type": "error", "source": "acquisition", "message": str(e)})

        finally:
            self._cleanup()

    def _acquisition_loop(self):
        """主采集循环"""
        while not self._stop_requested():
            self._heartbeat.touch()
            if self.plc_disconnected:
                self._update_pulse_data()
                logger.warning("PLC disconnected")
                self.strategy.reset_for_next_workpiece(self)
                self._heartbeat.sleep(1)
                continue

            self.strategy.monitor_movement(self)
            if self._stop_requested():
                break
            self._save_workpiece_data()

            skip_processing = False
            if self.lidar_reconnected:
                logger.info("Lidar reconnected; continuous mode delivers the next complete rescan, other modes skip the first workpiece")
                skip_processing = not is_continuous_bidirectional_mode(self.strategy_name)
                self.lidar_reconnected = False
            if self.plc_reconnected:
                logger.info("PLC reconnected; continuous mode delivers the next complete rescan, other modes skip the first workpiece")
                skip_processing = not is_continuous_bidirectional_mode(self.strategy_name)
                self.plc_reconnected = False

            if is_complete_workpiece_mode(self.strategy_name):
                if getattr(self, "complete_skip_current_workpiece", False):
                    skip_processing = True
                    logger.info("[CompleteWorkpiece StartupGuard] skip current startup workpiece, raw data will not be sent")
                # 首次启动 + start_skip_mmmm 内开始采集
                elif self.software_first_start and self.start_motion_pulse is not None:
                    pulse_diff = self._get_forward_pulse_diff(self.start_motion_pulse, self.current_pulse)
                    moved_mm = pulse_diff / self.read_data_config["pulse_to_mm"]
                    if moved_mm <= self.read_data_config["start_skip_mm"]:
                        skip_processing = True
            if not skip_processing:
                self._prepare_processing_data()
                self.strategy.send_raw_data(self)

            self.strategy.reset_for_next_workpiece(self)
            if not is_frame_by_frame_mode(self.strategy_name):
                self._heartbeat.sleep(0.1)

    def _stop_requested(self):
        return self.shutdown_flag or (self.stop_event is not None and self.stop_event.is_set())

    def _prepare_processing_data(self):
        """Preserve whole-workpiece computation interfaces, independently of saving.

        Relative workpieces still need normalized arrays for block finding; continuous
        passes still need absolute Z/Y/X order. No file I/O or save ACK is involved.
        """
        if is_frame_by_frame_mode(self.strategy_name):
            return
        threshold = self.read_data_config["max_pulse"] / self.read_data_config["pulse_to_mm"]
        for channel, chunks in self._processing_chunks.items():
            points = np.concatenate(chunks)
            if is_continuous_bidirectional_mode(self.strategy_name):
                points = points[np.lexsort((points[:, 0], points[:, 1], points[:, 2]))]
            else:
                points = self.data_split.normalize_xyz_points(points, threshold)
            if channel == "combined":
                self.all_xyz_data = points
            else:
                self.direction_states[channel].xyz_data = points
        self._processing_chunks = {}

    def _initialize_connections(self) -> bool:
        """初始化硬件连接"""
        try:
            self.lidar_manager = LidarManager(f"{self.config_dir}\\LidarConfig.toml")
            self.data_split = DataSplitting()
            self.data_filter = DataFilter()

            for direction, lidar_ids in self.lidar_config.items():
                for lidar_id in lidar_ids:
                    lidar = self.lidar_manager.get_lidar(lidar_id)
                    if not self._connect_with_retry(lidar, lidar_id, direction):
                        return False

            logger.info("All lidar connections established successfully")
            return True

        except Exception as e:
            logger.error(f"Connection initialization failed: {str(e)}")
            return False

    def _init_direction_states(self):
        """初始化所有方向的采数状态数据"""
        for direction, state in self.direction_states.items():
            state.xyz_data = np.empty((0, 3))
        logger.info("Direction states initialized")

    def _save_valid_data_core(self, z_value):
        """save_valid_data 核心逻辑 - 将当前帧数据按 z_value 拼接并累积"""
        if self.save_buffer is None:
            raise RuntimeError("Point cloud save buffer is not initialized")
        current_frame_data = np.empty((0, 3))
        for direction, state in self.direction_states.items():
            if state.scanning_started and state.last_same_origin_filtered.size > 0 and state.last_diff_origin_filtered.size > 0:
                same_origin_frame_data = np.column_stack((
                    state.last_same_origin_filtered[:, :2],
                    np.full(len(state.last_same_origin_filtered), z_value)
                ))
                diff_origin_frame_data = np.column_stack((
                    state.last_diff_origin_filtered[:, :2],
                    np.full(len(state.last_diff_origin_filtered), z_value)
                ))
                # 添加到各方向点云数据
                if self.read_data_config["translate_data_origin"] == 1:
                    direction_frame = same_origin_frame_data
                else:
                    direction_frame = diff_origin_frame_data
                self.save_buffer.append(direction, direction_frame)
                if not is_frame_by_frame_mode(self.strategy_name):
                    self._processing_chunks.setdefault(direction, []).append(direction_frame)

                # 添加到当前帧数据
                current_frame_data = np.vstack((current_frame_data, same_origin_frame_data)) if current_frame_data.size > 0 else same_origin_frame_data
        if current_frame_data.size > 0:
            sorted_frame_data = self.data_split.AxisSorting_yx(current_frame_data, self.read_data_config["y_threshold"])
            if isinstance(sorted_frame_data, np.ndarray) and sorted_frame_data.size > 0:
                self.save_buffer.append("combined", sorted_frame_data)
                if not is_frame_by_frame_mode(self.strategy_name):
                    self._processing_chunks.setdefault("combined", []).append(sorted_frame_data)
                logger.debug(f"save_valid_data_core - z_value: {z_value}, total accumulated data shape: {len(sorted_frame_data)}")
        self.save_buffer.poll_acks()
        low = self.save_buffer.free_blocks <= max(1, self.save_buffer.descriptor["block_count"] // 8)
        if low and not getattr(self, "_buffer_warning", False):
            logger.warning(f"Point cloud save buffer low: {self.save_buffer.free_blocks} free blocks")
        self._buffer_warning = low

    def _get_forward_pulse_diff(self, start_pulse: int, current_pulse: int | None = None) -> int:
        """计算脉冲从 start_pulse 向前运行到 current_pulse 的距离，支持回绕。

        当前 fifo 实际为由 pulse 推导出的 chaincountcm，回绕应与 pulse 保持一致。
        """
        if current_pulse is None:
            current_pulse = self.current_pulse
        max_pulse = int(self.read_data_config["max_pulse"])
        ring_size = max_pulse + 1
        return (int(current_pulse) - int(start_pulse)) % ring_size

    def _get_current_scan_z_value(self, current_pulse: int | None = None) -> float:
        """返回当前工件相对起点的连续 z 值（单位 mm）。"""
        if current_pulse is None:
            current_pulse = self.current_pulse
        if self.scan_base_pulse is None:
            return 0.0
        pulse_diff = self._get_forward_pulse_diff(self.scan_base_pulse, current_pulse)
        return pulse_diff / self.read_data_config["pulse_to_mm"]

    def _check_scanning_completion_default(self):
        """默认扫描完成检查逻辑（FrameByFrame 和 CompleteWorkpiece 共用）"""
        any_direction_finished = any(state.has_scanned and not state.scanning_started for state in self.direction_states.values())
        all_started_finished = all(not state.scanning_started for state in self.direction_states.values() if state.has_scanned)
        self.finish_test = any_direction_finished and all_started_finished and not self.any_scanning_active

        if self.finish_test:
            finished_directions = [d for d, state in self.direction_states.items() if state.has_scanned and not state.scanning_started]
            never_started = [d for d, state in self.direction_states.items() if not state.has_scanned]
            if never_started:
                logger.info(f"Scanning finished in directions: {finished_directions}. Directions never started: {never_started}")
            else:
                logger.info(f"All directions finished: {finished_directions}")

    def _update_scanning_state_base(self, direction, state):
        """扫描状态更新基础逻辑，返回 (stopped_by_points, stopped_by_max_length)"""
        current_pulse, current_fifo, current_status = self._update_pulse_data()
        if direction == "left":
            logger.debug(f"_update_scanning_state_base - current pulse: {current_pulse}, fifo: {current_fifo}, status: {current_status}")
        stopped_by_points = False
        stopped_by_max_length = False

        starttype = state.should_start_scanning(state.frame_counts)
        # 判断开始条件
        if starttype and not state.scanning_started and not state.has_scanned:
            state.scanning_started = True
            state.has_scanned = True
            state.start_pulse = current_pulse
            if self.scan_base_pulse is None:
                self.scan_base_pulse = current_pulse
            logger.info(f"{direction} scanning started at pulse {state.start_pulse}")
        # 判断结束条件
        if state.scanning_started and state.should_stop_scanning(state.frame_counts):
            state.scanning_started = False
            state.stop_pulse = current_pulse
            stopped_by_points = True
            logger.info(f"{direction}  points less than {state.points_threshold}," f"scanning stopped at pulse {state.stop_pulse}")
        elif state.start_pulse is not None:
            pulse_diff = self._get_forward_pulse_diff(state.start_pulse, current_pulse)
            max_allowed = self.read_data_config["max_scan_length"] * self.read_data_config["pulse_to_mm"]
            if pulse_diff > max_allowed:
                state.scanning_started = False
                state.stop_pulse = current_pulse
                stopped_by_max_length = True
                logger.info(f"{direction} scanning stopped due to max length")

        return stopped_by_points, stopped_by_max_length

    def _reset_base(self):
        """基础重置逻辑（所有策略共用）"""
        self.movement_detected = False
        self.finish_test = False
        self.all_xyz_data = np.empty((0, 3))
        self.scan_base_pulse = None
        self._processing_chunks = {}
        if self.save_buffer is not None:
            self.save_buffer.release_unsaved()
        for state in self.direction_states.values():
            state.reset()
        logger.info("System reset for next workpiece")

    def _invalidate_current_workpiece(self, reason: str):
        """当前工件作废。FrameByFrame 模式下立即清空队列并进入100空帧跳过。"""
        logger.warning(f"Current workpiece invalidated due to lidar issue: {reason}")
        if is_continuous_bidirectional_mode(self.strategy_name):
            print(f"Scan discarded: {reason}. After reconnection, reposition to the endpoint and rescan in reverse. Serious faults require a restart.")
            # 必须在阻塞重连之前通知PLC，不能等_capture_frame返回后再上报。
            self._push_lidar_status_update()
        else:
            print(f"当前工件作废：{reason}，设备回安全位，等待下一个工件")

        if is_frame_by_frame_mode(self.strategy_name):
            self._reset_framebyframe_state_after_fault()
            self._push_lidar_status_update(reset_queue=True)
            return

        self.finish_test = True
        self.any_scanning_active = False
        for state in self.direction_states.values():
            state.scanning_started = False

    def _reset_framebyframe_state_after_fault(self):
        """FrameByFrame 模式下的断开重置：清缓存、重置采数状态、进入跳过模式。"""
        self.cm_accum.clear()
        self._reset_base()
        self.fbf_skipping_workpiece = True
        self.fbf_skip_complete = False
        self.fbf_empty_frame_count = 0
        self.software_first_start = False

    def _rearm_startup_guard_after_lidar_recovery(self):
        """激光异常恢复后，重新启用首启动跳过逻辑。"""
        if not is_frame_by_frame_mode(self.strategy_name):
            return

        self.cm_accum.clear()
        self.last_sent_fifo = -1
        self.software_first_start = True
        self.start_motion_pulse = self.current_pulse if self.current_status == "moving_forward" else None
        self.fbf_skipping_workpiece = False
        self.fbf_skip_complete = False
        self.fbf_empty_frame_count = 0
        self.finish_test = False
        logger.info(
            f"[FrameByFrame StartupGuard] Rearmed after lidar recovery, "
            f"start_motion_pulse={self.start_motion_pulse}"
        )

    def _handle_lidar_status_transition(self, new_status: int, source: str = ""):
        """处理激光状态切换，异常恢复后重新启用启动跳过逻辑。"""
        new_status = int(new_status or 0)
        self._publish_ui_status(new_status)
        old_status = int(getattr(self, "last_reported_lidar_status", 0) or 0)
        self.last_reported_lidar_status = new_status

        if old_status in (1, 2, 3) and new_status == 0:
            logger.info(
                f"Lidar status recovered from {old_status} to 0"
                f"{f' ({source})' if source else ''}, rearm startup guard"
            )
            self._rearm_startup_guard_after_lidar_recovery()

    def _publish_ui_status(self, status: int, force: bool = False):
        publisher = getattr(self, "ui_status", None)
        if publisher is None or publisher.output_queue is None:
            return
        publisher.publish(
            force=force, status=int(status),
            connected=bool(self.active_directions) and int(status) == 0 and not self.lidar_disconnected,
        )

    def _connect_with_retry(self, lidar, lidar_id: str, direction: str) -> bool:
        """带重试的连接方法"""
        max_retries = self.read_data_config["lidar_connect_max_retries"]

        for attempt in range(max_retries):
            if self._stop_requested():
                return False
            try:
                self._heartbeat.touch()
                try:
                    lidar.disconnect()
                except Exception:
                    pass
                if lidar.connect():
                    logger.info(f"Successfully connected to {direction} lidar {lidar_id}")
                    print(self._text(f"成功连接{direction}激光 {lidar_id}", f"Connected to {direction} lidar {lidar_id}"))
                    return True

                print(self._text(f"{lidar_id}激光连接失败，正在尝试第{attempt+1}次重连...", f"Lidar {lidar_id} connection failed; reconnect attempt {attempt+1}..."))
                logger.warning(f"Attempt {attempt+1} failed for {direction} lidar {lidar_id}")

                if attempt < max_retries - 1:
                    self._heartbeat.sleep(10)

            except Exception as e:
                logger.error(f"Error connecting {direction} lidar {lidar_id}: {str(e)}")
                if attempt < max_retries - 1:
                    self._heartbeat.sleep(1)

        logger.error(f"Failed to connect {direction} lidar {lidar_id} after {max_retries} attempts")
        return False

    def _update_pulse_data(self):
        """更新脉冲数据 - 只消费队列中的最新值，减少积压处理开销"""
        was_disconnected = self.plc_disconnected
        if self.save_buffer is not None:
            self.save_buffer.poll_acks()
        now = time.monotonic()
        if now - self._last_log_check >= 60:
            check_and_rotate_log()
            self._last_log_check = now
        latest_pulse_data = None

        while True:
            try:
                pulse_data = self.pulse_queue.get_nowait()
                if pulse_data.get("pulse", 0) == -999:
                    self.plc_disconnected = True
                    self.plc_connection_generation = int(
                        pulse_data.get("plc_generation", self.plc_connection_generation) or 0
                    )
                    logger.warning("PLC disconnected detected!")
                    return self.current_pulse, getattr(self, "current_fifo", 0), "stopped"
                latest_pulse_data = pulse_data
            except queue.Empty:
                break
            except Exception as e:
                logger.error(f"Error processing pulse data: {str(e)}")
                return self.current_pulse, getattr(self, "current_fifo", 0), "stopped"

        if latest_pulse_data is not None:
            pulse_value = latest_pulse_data.get('pulse', 0)
            self.plc_disconnected = False
            self.plc_connection_generation = int(
                latest_pulse_data.get("plc_generation", self.plc_connection_generation) or 0
            )
            if self.current_pulse != pulse_value:
                self.current_pulse = pulse_value

            fifo_value = latest_pulse_data.get('fifo', 0)
            if not hasattr(self, "current_fifo"):
                self.current_fifo = fifo_value
                logger.info(f"Initialize current_fifo with first received value: {fifo_value}")
            elif self.current_fifo != fifo_value:
                old_fifo = self.current_fifo
                if not is_continuous_bidirectional_mode(self.strategy_name) and not self._is_next_fifo(old_fifo, fifo_value):
                    logger.warning(f"FIFO jump detected: old={old_fifo}, new={fifo_value}")
                self.current_fifo = fifo_value

            self.current_status = latest_pulse_data.get("status", "stopped")

        # 检测从断连状态恢复
        if was_disconnected and not self.plc_disconnected:
            self.plc_reconnected = True
            if is_frame_by_frame_mode(self.strategy_name):
                self.last_sent_fifo = int(getattr(self, "current_fifo", 0) or 0)
            logger.info("PLC reconnected")
        # logger.debug(f"Updated pulse data: pulse={self.current_pulse}, fifo={getattr(self, 'current_fifo', 'N/A')}, status={self.current_status}")
        return self.current_pulse, getattr(self, "current_fifo", 0), self.current_status

    def _capture_frame(self):
        """采集一帧数据"""
        if self.plc_disconnected:
            logger.warning("PLC disconnected, skipping frame capture")
            return

        self.lidar_status = 0
        direction_data = {}
        for direction in self.active_directions:
            state = self.direction_states[direction]
            same_origin_filtered, diff_origin_filtered = self._process_direction(direction)

            # 保存到方向状态
            state.last_same_origin_filtered = same_origin_filtered
            state.last_diff_origin_filtered = diff_origin_filtered

            # 更新帧计数，確保是numpy数组
            if isinstance(same_origin_filtered, np.ndarray):
                count_same = len(same_origin_filtered) if same_origin_filtered.size > 0 else 0
            else:
                count_same = 0
            if isinstance(diff_origin_filtered, np.ndarray):
                count_diff = len(diff_origin_filtered) if diff_origin_filtered.size > 0 else 0
            else:
                count_diff = 0

            if self.read_data_config["translate_data_origin"] == 1:
                state.update_frame_count(count_same)
            else:
                state.update_frame_count(count_diff)

            self.strategy.update_scanning_state(self, direction, state, same_origin_filtered, diff_origin_filtered)

            # 构建方向数据用于遭框发送，確保是numpy数组
            if self.read_data_config["translate_data_origin"] == 1:
                if isinstance(same_origin_filtered, np.ndarray) and same_origin_filtered.size > 0:
                    direction_data[direction] = same_origin_filtered
                else:
                    direction_data[direction] = np.empty((0, 3))
            else:
                if isinstance(diff_origin_filtered, np.ndarray) and diff_origin_filtered.size > 0:
                    direction_data[direction] = diff_origin_filtered
                else:
                    direction_data[direction] = np.empty((0, 3))

        # 更新全局扫描活跃状态
        self.any_scanning_active = any(state.scanning_started for state in self.direction_states.values())
        self._handle_lidar_status_transition(self.lidar_status, source="capture")

        # 逐帧发送方向数据（FrameByFrame策略在此处调用send_data_to_queue）
        self.strategy.send_direction_data(self, direction_data)
        self.strategy.save_valid_data(self)
        self.strategy.check_scanning_completion(self)

    def _push_lidar_status_update(self, reset_queue: bool = False):
        """向下游发送最新激光状态。"""
        self.raw_data_queue.put({
            "lidar_status": int(self.lidar_status),
            "reset_queue": bool(reset_queue),
            "plc_generation": int(self.plc_connection_generation),
        })

    def _poll_lidar_status_if_due(self, force: bool = False):
        """停止状态下周期性轮询激光状态，便于 PLC 及时联锁。"""
        now = time.time()
        if not force and (now - self.last_lidar_status_poll_time) < self.lidar_status_poll_interval:
            return

        polled_status = 0
        for direction in self.active_directions:
            for lidar_id in self.lidar_config.get(direction, []):
                lidar = self.lidar_manager.get_lidar(lidar_id)
                try:
                    self._heartbeat.touch()
                    _, lidar_status = lidar.scan()
                    self._heartbeat.touch()
                    polled_status = max(polled_status, int(lidar_status))
                    if self.lidar_disconnected:
                        self.lidar_reconnected = True
                    self.lidar_disconnected = False
                except (ConnectionResetError, BrokenPipeError, OSError) as e:
                    logger.error(f"{lidar_id} Lidar poll connection error: {str(e)}")
                    polled_status = 3
                    self.lidar_disconnected = True
                    self._publish_ui_status(3, force=True)
                    if is_continuous_bidirectional_mode(self.strategy_name):
                        self.lidar_status = 3
                        self._push_lidar_status_update()
                    if self._connect_with_retry(lidar, lidar_id, direction):
                        # 本周期已经采数失败，只恢复连接；下一周期重新发起完整采数请求。
                        self.lidar_reconnected = True
                        self.lidar_disconnected = False

        self.lidar_status = int(polled_status)
        self._handle_lidar_status_transition(self.lidar_status, source="poll")
        self.last_lidar_status_poll_time = now
        self._push_lidar_status_update()

    def _process_direction(self, direction: str):
        """
        处理指定方向的激光雷达数据
        Args:
            direction: 方向标识 ('left', 'right', 'forward', 'reverse' 等)
        Returns:
            (same_origin_filtered, diff_origin_filtered) - 两种坐标系的过滤点云
        """
        same_origin_all_points = []
        diff_origin_all_points = []

        # 扫描所有在此方向配置的激光雷达
        for lidar_id in self.lidar_config[direction]:
            lidar = self.lidar_manager.get_lidar(lidar_id)
            try:
                self._heartbeat.touch()
                all_data = lidar.scan()
                self._heartbeat.touch()
                if self.lidar_disconnected:
                    self.lidar_reconnected = True
                self.lidar_disconnected = False
            except (ConnectionResetError, BrokenPipeError, OSError) as e:
                logger.error(f"{lidar_id} Lidar Connection error: {str(e)}")
                self.lidar_status = max(self.lidar_status, 3)
                self.lidar_disconnected = True
                self._publish_ui_status(3, force=True)
                if self.movement_detected or self.any_scanning_active:
                    self._invalidate_current_workpiece(self._text(f"{direction}方向激光 {lidar_id} 连接断开", f"{direction} lidar {lidar_id} disconnected"))
                if not self._connect_with_retry(lidar, lidar_id, direction):
                    return np.empty((0, 3)), np.empty((0, 3))
                # 本周期丢弃残缺采数；重连后的下一周期再发送新的完整请求。
                self.lidar_reconnected = True
                self.lidar_disconnected = False
                return np.empty((0, 3)), np.empty((0, 3))

            data = all_data[0]
            self.lidar_status = max(self.lidar_status, int(all_data[1]))
            if int(all_data[1]) == 2 and (self.movement_detected or self.any_scanning_active):
                self._invalidate_current_workpiece(self._text(f"{direction}方向激光 {lidar_id} 异常", f"{direction} lidar {lidar_id} reported an error"))
            if data is not None:
                same_origin_all_points.extend(data.same_cartesian)
                diff_origin_all_points.extend(data.diff_cartesian)

        # 过滤并处理点云数据
        if same_origin_all_points and diff_origin_all_points:
            same_origin_filtered = self._process_lidar_data(True, same_origin_all_points, direction)
            diff_origin_filtered = self._process_lidar_data(False, diff_origin_all_points, direction)
            return same_origin_filtered, diff_origin_filtered

        return np.empty((0, 3)), np.empty((0, 3))

    def _process_lidar_data(self, same_origin_type: bool, data, direction: str) -> np.ndarray:
        """处理激光雷达原始数据"""
        if isinstance(data, list):
            data = np.array(data)

        config = self.read_data_config

        if same_origin_type:
            x_min = config["combined_x_min"]
            x_max = config["combined_x_max"]
            y_min = config["combined_y_min"]
            y_max = config["combined_y_max"]
        else:
            x_min = config[f"{direction}_x_min"]
            x_max = config[f"{direction}_x_max"]
            y_min = config[f"{direction}_y_min"]
            y_max = config[f"{direction}_y_max"]

        passthrough_filtered = self.data_filter.PassThroughFilter(data, x_min, x_max, y_min, y_max)

        if passthrough_filtered.size == 0:
            return np.empty((0, 2))

        # 逐帧采数场景最终只按区间建帧，不依赖排序结果，直接返回可明显降低热点开销
        if is_frame_by_frame_mode(self.strategy_name):
            return passthrough_filtered

        return self.data_split.AxisSorting_yx(passthrough_filtered, config["y_threshold"])

    def _save_workpiece_data(self, incomplete=False):
        """Seal existing shared blocks; never normalize or copy a workpiece here."""
        if self.save_buffer is None or not self.save_buffer.has_data:
            return
        if self.save_task_queue is None:
            raise RuntimeError("Point cloud save task queue is not initialized")
        started = time.perf_counter()
        self._save_job_counter += 1
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        job_id = f"{stamp}_{os.getpid()}_{self._save_job_counter}"
        suffix = job_id
        job = self.save_buffer.seal(
            job_id, filename_suffix=suffix, incomplete=incomplete,
            strategy=self.strategy_name,
            normalization="absolute_sorted" if is_continuous_bidirectional_mode(self.strategy_name) else "relative_z",
            preview_enabled=not (is_complete_workpiece_mode(self.strategy_name) and getattr(self, "draw_type", 1) == 2),
            preview_origin_config=(
                {key: self.read_data_config[key] for key in ("workpiece_origin_side", "workpiece_origin_reference_x") if key in self.read_data_config}
                if int(self.read_data_config.get("translate_data_origin", 1)) == 1 else None),
            z_reset_threshold=self.read_data_config["max_pulse"] / self.read_data_config["pulse_to_mm"])
        self.save_task_queue.put_nowait(job)
        logger.info(f"Submitted point cloud job {job_id}, channels={list(job['channels'])}, "
                    f"pending={self.save_buffer.pending_jobs}, submit_s={time.perf_counter() - started:.6f}, "
                    f"incomplete={incomplete}")

    def _cleanup(self):
        """Submit the captured part on stop, then close this process's mappings."""
        self.shutdown_flag = True
        # PLC has already stopped consuming live frames. Discarding its remaining
        # pipe backlog must not prevent the save-task feeder from flushing on exit.
        self.raw_data_queue.cancel_join_thread()
        if self.save_buffer is not None:
            try:
                self._save_workpiece_data(incomplete=True)
            except Exception as exc:
                logger.exception("Failed to submit final point cloud")
                if self.save_status_queue is not None:
                    self.save_status_queue.put({"type": "error", "source": "acquisition",
                                                "message": f"Final point cloud not submitted: {exc}"})
            finally:
                self.save_buffer.close()
        manager = getattr(self, "lidar_manager", None)
        if manager is not None:
            for lidar_ids in self.lidar_config.values():
                for lidar_id in lidar_ids:
                    try:
                        manager.get_lidar(lidar_id).disconnect()
                    except Exception as exc:
                        logger.error(f"Error disconnecting {lidar_id}: {exc}")
        logger.info("Acquisition connections closed")

    def _check_linked_stop_continuous(self):
        """链接停止逻辑"""
        link_mm = self.read_data_config["linked_stop_distance_mm"]
        link_pulse = link_mm * self.read_data_config["pulse_to_mm"]

        anchors = [state for state in self.direction_states.values() if state.is_link_anchor and state.stop_reason == "points" and state.stop_pulse is not None]

        if not anchors:
            return

        anchor = anchors[0]
        anchor_pulse = anchor.stop_pulse
        current_pulse = self.current_pulse

        for direction, state in self.direction_states.items():
            if not state.scanning_started:
                continue

            # pulse 距离
            pulse_diff = self._get_forward_pulse_diff(anchor_pulse, current_pulse)

            if pulse_diff >= link_pulse:
                state.scanning_started = False
                state.stop_pulse = self.current_pulse
                state.stop_reason = "linked"
                logger.info(f"{direction} stopped due to linked stop condition")

    def _force_finish_by_endpoint(self, pulse, reason: str):
        """行程端点强制结束"""
        if not any(state.scanning_started for state in self.direction_states.values()):
            logger.info(f"Force finish ignored ({reason}), already finished")
            return

        logger.info(f"Force finish by endpoint ({reason}), pulse={pulse}")

        for state in self.direction_states.values():
            if state.scanning_started:
                state.scanning_started = False
                state.stop_pulse = pulse
                logger.info(f"{state.direction} forced stop at pulse {pulse}")

        self.finish_test = True

    def send_data_to_queue(self, direction_data: dict):
        """累积式发送数据"""
        cur = int(self.current_fifo)
        if cur not in self.cm_accum:
            self.cm_accum[cur] = {}
        for dname, darr in direction_data.items():
            # 确保检查数据是否为numpy数组
            is_empty = (darr is None) or (isinstance(darr, np.ndarray) and darr.size == 0) or (isinstance(darr, list) and len(darr) == 0)
            if is_empty:
                self.cm_accum[cur].setdefault(dname, [])
            else:
                self.cm_accum[cur].setdefault(dname, []).append(darr)

        # 首次初始化：以首次接收到的FIFO值作为起点，而不是认为有缺帧
        if self.last_sent_fifo == -1:
            self.last_sent_fifo = (cur - 1) % (self.max_fifo + 1)
            logger.info(f"First FIFO received: {cur}, initialized last_sent_fifo to {self.last_sent_fifo}")

        fifo_delta = self._get_fifo_step_delta(self.last_sent_fifo, cur)
        reverse_tolerance = self.read_data_config.get("fifo_reverse_tolerance", 10) or 10

        # FIFO 没变，不发送
        if fifo_delta == 0:
            return

        # FIFO 倒退通常意味着读到了旧值/乱序值，不能按回绕缺帧补齐，否则会导致整批数据错位
        if fifo_delta < 0:
            backward_step = abs(fifo_delta)
            if backward_step > reverse_tolerance:
                self._handle_fifo_reverse_fault(cur=cur, backward_step=backward_step)
                return

            logger.warning(
                f"FIFO reverse/stale frame ignored: last_sent={self.last_sent_fifo}, cur={cur}, "
                f"backward_step={backward_step} (<= {reverse_tolerance}), waiting next forward fifo"
            )
            return

        repeat_count = fifo_delta
        if fifo_delta > 1:
            logger.warning(
                f"FIFO jump detected: last_sent={self.last_sent_fifo}, cur={cur}, "
                f"repeat current frame {fifo_delta} times to fill missing FIFOs"
            )

        self._send_single_fifo(cur, cur, repeat_count=repeat_count)
        self.last_sent_fifo = cur

    def _get_fifo_step_delta(self, last_fifo: int, current_fifo: int) -> int:
        """计算 FIFO 的有符号步数。

        返回值说明：
        - > 0: FIFO 前进了多少帧（含正常回绕）
        - = 0: FIFO 未变化
        - < 0: FIFO 倒退/收到旧帧，绝不能当成缺帧补齐
        """
        ring_size = self.max_fifo + 1
        forward_gap = (int(current_fifo) - int(last_fifo)) % ring_size

        if forward_gap == 0:
            return 0

        if forward_gap <= ring_size // 2:
            return forward_gap

        return forward_gap - ring_size

    def _handle_fifo_reverse_fault(self, cur: int, backward_step: int):
        """FIFO 反向超阈值异常处理：清空数据并触发设备回安全位。"""
        logger.error(
            f"FIFO reverse overflow detected: last_sent={self.last_sent_fifo}, cur={cur}, "
            f"backward_step={backward_step} (>{self.read_data_config.get('fifo_reverse_tolerance', 10) or 10}), clear all data and force safe return"
        )

        self.cm_accum.clear()
        # 标记激光异常，让 PLC 端进入 force_disable_all 分支并执行回原点/安全位
        self.lidar_status = 2
        self._invalidate_current_workpiece(f"FIFO后退超阈值({backward_step})")

    def _send_single_fifo(self, fifo_key, real_fifo_key, repeat_count: int = 1):
        """发送单个FIFO"""
        if fifo_key not in self.cm_accum:
            self.cm_accum[fifo_key] = {}

        accum = self.cm_accum[fifo_key]

        # 根据激光配置中非空的方向动态构建各方向帧数据
        fifo_data = {
            "fifo": real_fifo_key,
            "repeat_count": repeat_count,
            "lidar_status": int(self.lidar_status),
            "plc_generation": int(self.plc_connection_generation),
        }
        for direction in self.active_directions:
            frame = self.build_side_frame(accum, direction, self.read_data_config)
            fifo_data[direction] = frame

        self.raw_data_queue.put(fifo_data)
        logger.debug(
            f"Sent fifo {real_fifo_key} data to raw data queue, "
            f"repeat_count={repeat_count}, directions={self.active_directions}"
        )

        try:
            del self.cm_accum[real_fifo_key]
        except KeyError:
            logger.error(f"FIFO {real_fifo_key} not found in cm_accum")
