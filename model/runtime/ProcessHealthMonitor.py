"""Pure process-health checks used by both wx and PyQt control surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProcessFault:
    kind: str
    detail: str


class ProcessHealthMonitor:
    def __init__(self, unresponsive_timeout_s: int):
        if unresponsive_timeout_s <= 0:
            raise ValueError("unresponsive_timeout_s must be positive")
        self._unresponsive_timeout_s = int(unresponsive_timeout_s)

    def check(
        self,
        processes: list[Any],
        heartbeats: dict[Any, Any],
        save_service: Any | None,
        *,
        now: float,
    ) -> ProcessFault | None:
        if save_service is not None:
            for message in save_service.poll_status():
                if message.get("type") == "error":
                    return ProcessFault("save_error", str(message.get("message", "Unknown save error")))

        dead_processes = [process for process in processes if not process.is_alive()]
        if dead_processes:
            return ProcessFault("dead_process", ", ".join(type(process).__name__ for process in dead_processes))

        stale_processes = []
        for process, heartbeat in heartbeats.items():
            elapsed = now - float(heartbeat.value)
            if elapsed > self._unresponsive_timeout_s:
                stale_processes.append(f"{type(process).__name__} ({elapsed:.1f}s)")
        if stale_processes:
            return ProcessFault("stale_process", ", ".join(stale_processes))
        return None
