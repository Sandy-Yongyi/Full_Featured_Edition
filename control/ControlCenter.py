"""UI-independent orchestration for the industrial control center.

The runtime object owns hardware processes.  This class owns the small,
deterministic state machine that a UI needs: start/stop commands, periodic
status collection, and a snapshot consumable by either wx or PyQt.
"""

from __future__ import annotations

from collections.abc import Callable
from queue import Empty, SimpleQueue
from typing import Any, Protocol

from model.telemetry.UiState import LogEvent, UiState, TaskState
from model.motionplan.motionutil.DeviceEnableHelper import validate_enable_transition
from model.runtime.ShutdownCoordinator import ShutdownCoordinator


class RuntimePort(Protocol):
    def start_pipeline(self) -> None: ...

    def stop_pipeline(self) -> list[str] | None: ...

    def poll(self) -> dict[str, Any] | None: ...


class ControlCenter:
    """Expose a hardware runtime through UI-neutral commands and snapshots."""

    def __init__(
        self,
        runtime: RuntimePort,
        strategy_name: str,
        chain_speed: int = 25,
        save_chain_speed: Callable[[int], None] | None = None,
        send_control: Callable[[dict[str, int]], None] | None = None,
        async_stop: bool = False,
    ):
        self._runtime = runtime
        self._save_chain_speed = save_chain_speed
        self._send_control = send_control
        self._async_stop = async_stop
        self._stop_results = SimpleQueue()
        self._startup_failed = False
        self._local_alarms: tuple[str, ...] = ()
        self._shutdown = ShutdownCoordinator(self._runtime.stop_pipeline, self._stop_results.put) if async_stop else None
        self._state = UiState.empty(strategy_name)
        self._state = self._replace_state(chain_speed=chain_speed)

    @property
    def running(self) -> bool:
        return self._state.running

    @property
    def stopping(self) -> bool:
        return self._state.stopping

    @property
    def strategy_name(self) -> str:
        return self._state.strategy_name

    @property
    def control_type(self) -> int:
        return getattr(self._runtime, "control_type", 2)

    @property
    def preview_mode(self) -> bool:
        return self.control_type == 3

    @property
    def control_queue(self):
        return getattr(self._runtime, "control_queue", None)

    def is_password_required(self) -> bool:
        checker = getattr(self._runtime, "is_password_required", None)
        return bool(checker()) if callable(checker) else False

    def verify_password(self, password: str) -> bool:
        verifier = getattr(self._runtime, "verify_password", None)
        return bool(verifier(password)) if callable(verifier) else True

    def start(self) -> bool:
        if self.running or self.stopping:
            return False
        self._startup_failed = False
        self._local_alarms = ()
        self._state = self._replace_state(running=True, chain_status="启动中", alarms=())
        try:
            self._runtime.start_pipeline()
        except Exception as exc:
            self._startup_failed = True
            self._local_alarms = (f"启动失败：{exc}",)
            self._state = self._replace_state(alarms=self._local_alarms)
            self._state = self._state.with_log(LogEvent("ERROR", f"启动失败：{exc}", "startup"))
            self.stop()
            raise
        self._state = self._replace_state(chain_status="运行中")
        return True

    def stop(self) -> bool:
        if not self.running or self.stopping:
            return False
        self._state = self._replace_state(running=False, stopping=True, chain_status="停止中")
        if self._shutdown is not None:
            self._shutdown.request_stop()
            return True
        try:
            errors = self._runtime.stop_pipeline() or []
        except Exception as exc:
            errors = [str(exc)]
        self._finish_async_stop(errors)
        return True

    def _finish_async_stop(self, errors: list[str]) -> None:
        live_workers = getattr(self._runtime, "has_live_workers", lambda: False)()
        if live_workers:
            errors = list(errors) + ["部分进程未退出，禁止重新启动；请检查日志。"]
        self._local_alarms = tuple(dict.fromkeys(self._local_alarms + tuple(map(str, errors))))
        status = "停止失败" if live_workers else ("启动失败" if self._startup_failed else ("停止完成" if not errors else "停止完成（有告警）"))
        self._state = self._replace_state(stopping=live_workers, chain_status=status, alarms=tuple(dict.fromkeys(self._state.alarms + self._local_alarms)))
        if not live_workers:
            self._state = self._replace_state(points=None, boxes=None, task=TaskState())
        for error in errors:
            self._state = self._state.with_log(LogEvent(level="ERROR", message=str(error), source="shutdown"))

    def poll_once(self) -> None:
        try:
            errors = self._stop_results.get_nowait()
        except Empty:
            pass
        else:
            self._finish_async_stop(errors)
        # Shutdown owns the save service and processes until its completion.
        if self.stopping:
            return
        data = self._runtime.poll() or {}
        allowed = {"chain_position", "chain_status", "chain_speed", "chain_speed_mm_s", "device_enable_mask", "pc_auto_mode", "all_devices_safe",
                   "points", "boxes", "devices", "task", "alarms"}
        changes = {key: value for key, value in data.items() if key in allowed}
        if "updated" in data:
            if not data["updated"]:
                changes.pop("points", None)
                changes.pop("boxes", None)
            elif not data.get("points_updated", data.get("points") is not None):
                changes.pop("points", None)
        if "alarms" in changes:
            changes["alarms"] = tuple(dict.fromkeys(tuple(changes["alarms"]) + self._local_alarms))
        if not self.running:
            changes.pop("chain_status", None)
        if changes:
            self._state = self._replace_state(**changes)
        for event in data.get("logs", ()):
            self._state = self._state.with_log(self._coerce_log(event))
        if self.running and data.get("fault"):
            self._state = self._state.with_log(LogEvent("ERROR", str(data["fault"]), "watchdog"))
            self.stop()

    def build_ui_state(self) -> UiState:
        return self._state

    def record_ui_event(self, event: LogEvent) -> None:
        self._state = self._state.with_log(event)

    def set_chain_speed(self, speed: int) -> None:
        """Persist the scan speed before notifying an active runtime."""
        if not isinstance(speed, int) or isinstance(speed, bool) or not 1 <= speed <= 50:
            raise ValueError("速度必须为1～50的整数，单位mm/s")
        if self._save_chain_speed is not None:
            self._save_chain_speed(speed)
        self._state = self._replace_state(chain_speed=speed)
        if self.running and self._send_control is not None:
            self._send_control({"lidar_scan_speed": speed})

    def set_device_enable_mask(self, mask: int) -> None:
        if type(mask) is not int or not 0 <= mask <= 127:
            raise ValueError("设备使能位必须为 0～127 的整数")
        if not self.running or self.stopping or self.preview_mode:
            raise RuntimeError("请先启动 PLC 通讯")
        if not any(d.name == "PLC" and d.online for d in self._state.devices):
            raise RuntimeError("PLC 未连接")
        if self._send_control is None:
            raise RuntimeError("设备控制未接入")
        mask = mask if mask & 1 else 0
        validate_enable_transition(self._state.device_enable_mask, mask, self._state.pc_auto_mode, self._state.all_devices_safe)
        self._send_control({"device_enable_mask": mask})
        self._state = self._replace_state(device_enable_mask=mask)

    def _replace_state(self, **changes: Any) -> UiState:
        return UiState(**{field: changes.get(field, getattr(self._state, field)) for field in UiState.__dataclass_fields__})

    @staticmethod
    def _coerce_log(event: LogEvent | str) -> LogEvent:
        return event if isinstance(event, LogEvent) else LogEvent(level="INFO", message=str(event))
