"""wx-free production runtime used by the PyQt6 control center.

It owns the same queues and worker processes as the legacy controller.  Qt
polls this object through ``ControlCenter`` instead of using wx timers.
"""

from __future__ import annotations

import multiprocessing
import os
import queue
import time
from typing import Any

from model.utils.ConfigurationService import ConfigurationService
from acquisition_sdk import LidarAcquisitionProcess
from control.PlcCommunicationProcess import PlcCommunicationProcess
from model.telemetry.RuntimeStateCollector import RuntimeStateCollector
from model.runtime.ProcessHealthMonitor import ProcessHealthMonitor
from acquisition_sdk import PointCloudFileProcess, resolve_txt_files
from model.telemetry.UiState import DeviceState, TaskState
from acquisition_sdk import DataFilter
from model.utils.LidarDirectionUtil import get_active_lidar_config
from model.utils.LoggerUtil import logger, manage_log_files, log_directory
from acquisition_sdk import PointCloudSaveService, stop_pipeline
from model.utils.StrategyUtil import is_complete_workpiece_mode, strategy_name_from_code
from model.utils.TomlLoader import TomlLoader
from model.utils.MachineConfigUtil import get_machine_config_path
from model.utils.UiTelemetry import UiStatusPublisher


class SubprocessRedirect:
    def __init__(self, output_queue, is_stderr: bool = False):
        self.output_queue = output_queue
        self.is_stderr = is_stderr
        self._pending = ""

    def write(self, text: str) -> int:
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            if line.strip():
                self.output_queue.put(("stderr" if self.is_stderr else "stdout", line.rstrip("\r")))
        return len(text)

    def flush(self) -> None:
        if self._pending:
            self.output_queue.put(("stderr" if self.is_stderr else "stdout", self._pending))
            self._pending = ""


class PipelineRuntime:
    """Production mode 2 plus developer TXT/PLC (1) and file-view (3) modes."""

    def __init__(self, config_dir: str | None = None, *, control_type: int = 2, data_path: str | None = None, data_name: str | None = None):
        if type(control_type) is not int or control_type not in (1, 2, 3):
            raise ValueError("control_type 只支持 1/2/3")
        self.control_type = control_type
        self.data_path = os.path.abspath(os.path.expanduser(data_path)) if data_path else None
        self.data_name = data_name
        self.toml_path = config_dir or os.path.join(os.getcwd(), "model", "tomls")
        self.mode_config_path = os.path.join(self.toml_path, "ModeConfig.toml")
        self.configuration_service = ConfigurationService(os.path.join(self.toml_path, "ReadDataConfig.toml"), self.mode_config_path)
        self.read_data_config = self.configuration_service.load_read_data()
        self.mode_config = TomlLoader.load(self.mode_config_path)
        self.sys_config = TomlLoader.load(os.path.join(self.toml_path, "SystemConfig.toml"))
        self.strategy_name = strategy_name_from_code(self.mode_config.get("strategy_name"))
        self.chain_speed = int(self.read_data_config.get("lidar_scan_speed", 25))
        self.process_heartbeat_interval_s = float(self.read_data_config.get("process_heartbeat_interval_s", 1))
        self.process_unresponsive_timeout_s = int(self.read_data_config.get("process_unresponsive_timeout_s", 60))
        self.control_queue = multiprocessing.Queue()
        self.log_queue = multiprocessing.Queue()
        self.ui_status_queue = multiprocessing.Queue(maxsize=32)
        self._ui_feedback: dict[str, dict] = {}
        self.processes: list[Any] = []
        self.process_heartbeats: dict[Any, Any] = {}
        self.save_service = None
        self.lidar_acquisition = None
        self.plc_handler = None
        self.data_processor = None
        self.file_loader = None
        self.running = False
        self._requested_device_enable_mask = 0
        self._enable_request_id = 0
        self._faults: list[str] = []
        self.filter = DataFilter()
        self.collector = RuntimeStateCollector(self.log_queue, self.filter, float(self.read_data_config.get("point_cloud_preview_voxel_mm", 10)))
        self.health_monitor = ProcessHealthMonitor(self.process_unresponsive_timeout_s)

    @staticmethod
    def _heartbeat():
        return multiprocessing.Value("d", time.monotonic())

    def _register(self, process: Any, heartbeat: Any) -> None:
        self.processes.append(process)
        self.process_heartbeats[process] = heartbeat

    def start_pipeline(self) -> None:
        if self.running:
            return
        if self.has_live_workers():
            raise RuntimeError("仍有工作进程未退出，禁止重新启动")
        mode_config = TomlLoader.load(self.mode_config_path)
        configured_strategy = strategy_name_from_code(mode_config.get("strategy_name"))
        if configured_strategy != self.strategy_name:
            raise ValueError("运行策略已变更，请重新启动软件后启动设备")
        files = resolve_txt_files(self.data_path, self.data_name) if self.control_type in (1, 3) else ()
        if self.control_type == 1 and self.strategy_name not in ("frame_by_frame", "complete_workpiece"):
            raise ValueError("TXT 联调目前支持 strategy_name=1/2，不支持策略 3")
        if self.control_type != 3:
            machine_path = get_machine_config_path(self.toml_path, self.strategy_name)
            try:
                TomlLoader.load(machine_path)
            except (OSError, ValueError) as exc:
                raise ValueError(f"设备配置无法加载：{machine_path}；{exc}") from exc
        self._ui_feedback.clear()
        self._requested_device_enable_mask = 0
        self.ui_status_queue = multiprocessing.Queue(maxsize=32)
        self._faults.clear()
        if self.control_type != 3:
            manage_log_files(log_directory)
        self.mode_config = mode_config
        spray_mode = int(self.mode_config.get("spray_mode", 0) or 0)
        raw_data_queue = multiprocessing.Queue()
        pulse_queue = multiprocessing.Queue()
        viz_queue = multiprocessing.Queue(maxsize=2)
        self.collector.set_visualization_queue(viz_queue)
        machine_data_queue = None
        if self.control_type == 1:
            from control.DataProcessWorker import DataProcessWorker
            heartbeat = self._heartbeat()
            loader = DataProcessWorker(raw_data_queue, pulse_queue, viz_queue, self.data_path,
                                       data_name=self.data_name, strategy_name=self.strategy_name,
                                       config_dir=self.toml_path, heartbeat=heartbeat,
                                       heartbeat_interval_s=self.process_heartbeat_interval_s)
            if not loader._discover_point_cloud_datasets():
                raise ValueError("未找到符合原点配置的 TXT 数据集；独立原点请使用 left_/right_ 等方向前缀")
            self.running = True
            loader.stdout = SubprocessRedirect(self.log_queue)
            loader.stderr = SubprocessRedirect(self.log_queue, is_stderr=True)
            loader.start()
            self.file_loader = loader
            self._register(loader, heartbeat)
        elif self.control_type == 3:
            heartbeat = self._heartbeat()
            loader = PointCloudFileProcess(files, viz_queue, self.ui_status_queue, heartbeat, self.process_heartbeat_interval_s, read_data_config=self.read_data_config)
            self.running = True
            loader.start()
            self.file_loader = loader
            self._register(loader, heartbeat)
            return
        else:
            self.running = True
        if self.control_type == 2 and spray_mode == 0:
            self.save_service = PointCloudSaveService.from_config_file(os.path.join(self.toml_path, "ReadDataConfig.toml"), os.path.join(os.getcwd(), "data", "points"), viz_queue,)
            self.save_service.start()
            self._register(self.save_service.worker, self.save_service.heartbeat)
            heartbeat = self._heartbeat()
            self.lidar_acquisition = LidarAcquisitionProcess(
                pulse_queue=pulse_queue, raw_data_queue=raw_data_queue, viz_queue=viz_queue,
                lidar_config=get_active_lidar_config(self.sys_config), config_dir=self.toml_path,
                strategy_name=self.strategy_name, heartbeat=heartbeat,
                heartbeat_interval_s=self.process_heartbeat_interval_s,
                save_pool_descriptor=self.save_service.pool.descriptor, save_task_queue=self.save_service.task_queue,
                save_ack_queue=self.save_service.ack_queue, save_status_queue=self.save_service.status_queue,
                stop_event=self.save_service.stop_event,
            )
            self.lidar_acquisition.daemon = True
            self.lidar_acquisition.ui_status = UiStatusPublisher(self.ui_status_queue, "lidar")
            self.lidar_acquisition.stdout = SubprocessRedirect(self.log_queue)
            self.lidar_acquisition.stderr = SubprocessRedirect(self.log_queue, is_stderr=True)
            self.lidar_acquisition.start()
            self._register(self.lidar_acquisition, heartbeat)
        if is_complete_workpiece_mode(self.strategy_name):
            from control.DataProcessingProcess import DataProcessingProcess
            machine_data_queue = multiprocessing.Queue()
            heartbeat = self._heartbeat()
            processor = DataProcessingProcess(raw_data_queue, machine_data_queue, viz_queue, self.toml_path, heartbeat, self.process_heartbeat_interval_s)
            processor.daemon = True
            processor.stdout = SubprocessRedirect(self.log_queue)
            processor.stderr = SubprocessRedirect(self.log_queue, is_stderr=True)
            processor.start()
            self.data_processor = processor
            self._register(processor, heartbeat)
        heartbeat = self._heartbeat()
        plc = PlcCommunicationProcess.create(
            strategy_name=self.strategy_name, raw_data_queue=raw_data_queue, pulse_queue=pulse_queue,
            control_queue=self.control_queue, machine_data_queue=machine_data_queue, heartbeat=heartbeat,
            heartbeat_interval_s=self.process_heartbeat_interval_s,
        )
        plc.daemon = True
        plc.ui_status = UiStatusPublisher(self.ui_status_queue, "plc")
        plc.stdout = SubprocessRedirect(self.log_queue)
        plc.stderr = SubprocessRedirect(self.log_queue, is_stderr=True)
        plc.start()
        self.plc_handler = plc
        self._register(plc, heartbeat)
        logger.info("PyQt production pipeline started")

    def stop_pipeline(self) -> list[str]:
        if not self.running and not self.processes and self.save_service is None:
            return []
        self.running = False
        if self.save_service is not None:
            self.save_service.stop_event.set()
        errors = stop_pipeline(
            list(self.processes), self.lidar_acquisition, self.save_service,
            int(self.read_data_config.get("point_cloud_acquisition_stop_timeout_s", 15)),
            int(self.read_data_config.get("point_cloud_save_shutdown_timeout_s", 120)),
        )
        if self.has_live_workers():
            return list(errors or []) + ["部分进程未退出，共享资源已保留"]
        self.processes = []
        self.process_heartbeats = {}
        self.save_service = None
        self.lidar_acquisition = None
        self.plc_handler = None
        self.data_processor = None
        self.file_loader = None
        self._ui_feedback.clear()
        self.collector.set_visualization_queue(None)
        return errors

    def has_live_workers(self) -> bool:
        return any(process.is_alive() for process in self.processes)

    def poll(self) -> dict[str, Any]:
        snapshot = self.collector.poll()
        for _ in range(32):
            try:
                message = self.ui_status_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(message, dict) and message.get("source") in {"plc", "lidar", "files"}:
                self._ui_feedback[message["source"]] = message
                if message.get("device_enable_error") and message.get("device_enable_request_id") == self._enable_request_id:
                    self._requested_device_enable_mask = int(message.get("device_enable_mask", 0))
        fault = self.health_monitor.check(self.processes, self.process_heartbeats, self.save_service, now=time.monotonic()) if self.running else None
        if fault is not None:
            if not self._faults or self._faults[-1] != fault.detail:
                self._faults.append(fault.detail)
            snapshot["fault"] = fault.detail
        snapshot["chain_speed"] = self.chain_speed
        snapshot["chain_status"] = "运行中" if self.running else "待机"
        if self.control_type == 3:
            feedback = self._ui_feedback.get("files", {})
            detail = feedback.get("detail", "等待导入 TXT 点云" if self.running else "待机")
            if feedback.get("state") == "error":
                snapshot["fault"] = detail
                if detail not in self._faults:
                    self._faults.append(detail)
            snapshot["chain_status"] = detail
            snapshot["task"] = TaskState(name="TXT 点云查看", stage=detail)
            snapshot["devices"] = tuple(DeviceState(name, False, "文件查看 · 不启用") for name in ("PLC", "激光", "伺服"))
            snapshot["alarms"] = tuple(self._faults[-10:])
            return snapshot
        now = time.monotonic()

        def device_feedback(source, worker):
            feedback = self._ui_feedback.get(source, {})
            alive = worker is not None and worker.is_alive()
            fresh = bool(feedback) and 0 <= now - float(feedback.get("timestamp", 0)) <= 5
            online = bool(alive and fresh and feedback.get("connected"))
            detail = "通讯正常" if online else ("等待通讯反馈" if alive else "未连接")
            if alive and fresh and not feedback.get("connected"):
                detail = "仿真模式" if feedback.get("simulated") else "设备通讯异常"
            return online, detail
        plc_online, plc_detail = device_feedback("plc", self.plc_handler)
        lidar_online, lidar_detail = device_feedback("lidar", self.lidar_acquisition)
        if self.control_type == 1:
            lidar_online, lidar_detail = False, "TXT 联调 · 不启用激光"
        plc_feedback = self._ui_feedback.get("plc", {})
        snapshot["chain_speed_mm_s"] = float(plc_feedback["chain_speed_mm_s"]) if plc_online and "chain_speed_mm_s" in plc_feedback else None
        if not plc_online:
            self._requested_device_enable_mask = 0
        snapshot["device_enable_mask"] = self._requested_device_enable_mask
        feedback_task = plc_feedback.get("task")
        snapshot["task"] = feedback_task if plc_online and isinstance(feedback_task, TaskState) else TaskState(stage="等待 PLC 任务反馈" if self.running else "待机")
        if plc_online:
            snapshot["chain_position"] = int(plc_feedback.get("pulse", 0))
            if self.running:
                motion = plc_feedback.get("motion", "stopped")
                snapshot["chain_status"] = {"moving_forward": "链条前进", "moving_reverse": "链条后退", "stopped": "链条停止"}.get(motion, "运行中")
        plc_status = plc_feedback.get("plc_status") if plc_online else None
        snapshot["pc_auto_mode"] = bool(int(plc_status) & 2) if plc_status is not None else None
        snapshot["all_devices_safe"] = bool(plc_online and plc_feedback.get("all_devices_safe", False))
        servo_ready = plc_status is not None and bool(int(plc_status) & 1)
        servo_detail = "伺服状态待反馈" if plc_online else "等待 PLC"
        if plc_status is not None:
            servo_detail = "" if servo_ready else "异常"
            if self.strategy_name != "continuous_bidirectional":
                mode = "PC自动模式" if int(plc_status) & 2 else "PLC点动模式"
                servo_detail = f"{servo_detail} · {mode}" if servo_detail else mode
        snapshot["devices"] = (
            DeviceState("PLC", plc_online, plc_detail),
            DeviceState("激光", lidar_online, lidar_detail),
            DeviceState("伺服", servo_ready, servo_detail),
        )
        snapshot["alarms"] = tuple(self._faults[-10:])
        return snapshot

    def save_chain_speed(self, speed: int) -> None:
        if self.control_type == 3:
            raise RuntimeError("文件查看模式不能修改生产配置")
        self.configuration_service.save_chain_speed(speed)
        self.read_data_config["lidar_scan_speed"] = speed
        self.chain_speed = speed

    def send_control(self, command: dict[str, int]) -> None:
        if self.control_type == 3:
            raise RuntimeError("文件查看模式不能发送设备命令")
        if "device_enable_mask" in command:
            self._enable_request_id += 1
            command = {**command, "device_enable_request_id": self._enable_request_id}
        self.control_queue.put(command)
        if "device_enable_mask" in command:
            mask = int(command["device_enable_mask"]) & 0x7F
            self._requested_device_enable_mask = mask if mask & 1 else 0

    def is_password_required(self) -> bool:
        if self.control_type == 3:
            return False
        return self.configuration_service.is_password_required()

    def verify_password(self, password: str) -> bool:
        return password == self.configuration_service.get_configured_password()
