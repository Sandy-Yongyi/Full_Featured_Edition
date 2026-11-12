"""UI-neutral state snapshots shared by the controller and PyQt6 views."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class LogEvent:
    level: str
    message: str
    source: str = "system"
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DeviceState:
    name: str
    online: bool = False
    detail: str = "未连接"


@dataclass(frozen=True, slots=True)
class GunPlanState:
    machine_id: int
    gun_id: int
    group: str
    selected: bool
    stage: str
    group_id: int | None = None
    y_upper: int | None = None
    y_lower: int | None = None
    angle: int | None = None


@dataclass(frozen=True, slots=True)
class TaskDetailState:
    name: str
    status: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class TaskState:
    name: str = "等待任务"
    stage: str = "待机"
    progress: int | None = None
    active_guns: int = 0
    total_guns: int = 0
    gun_plans: tuple[GunPlanState, ...] = ()
    details: tuple[TaskDetailState, ...] = ()


@dataclass(frozen=True, slots=True)
class UiState:
    strategy_name: str
    running: bool = False
    stopping: bool = False
    chain_position: int = 0
    chain_speed: int = 25
    chain_speed_mm_s: float | None = None
    device_enable_mask: int = 0
    pc_auto_mode: bool | None = None
    all_devices_safe: bool = False
    chain_status: str = "待机"
    points: Any | None = None
    boxes: Any | None = None
    devices: tuple[DeviceState, ...] = ()
    task: TaskState = TaskState()
    alarms: tuple[str, ...] = ()
    logs: tuple[LogEvent, ...] = ()

    @classmethod
    def empty(cls, strategy_name: str) -> "UiState":
        return cls(strategy_name=strategy_name)

    def with_log(self, event: LogEvent, limit: int = 500) -> "UiState":
        if limit < 1:
            raise ValueError("limit must be a positive integer")
        return replace(self, logs=(self.logs + (event,))[-limit:])
