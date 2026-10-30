"""Best-effort, rate-limited worker feedback for the desktop UI."""

import queue
import time


class UiStatusPublisher:
    def __init__(self, output_queue, source: str, interval_s: float = 0.2):
        self.output_queue = output_queue
        self.source = source
        self.interval_s = interval_s
        self._last_sent = float("-inf")

    def is_due(self, force: bool = False) -> bool:
        return self.output_queue is not None and (force or time.monotonic() - self._last_sent >= self.interval_s)

    def publish(self, *, force: bool = False, **fields) -> None:
        if self.output_queue is None:
            return
        now = time.monotonic()
        if not force and now - self._last_sent < self.interval_s:
            return
        try:
            self.output_queue.put_nowait({**fields, "source": self.source, "timestamp": now})
        except (queue.Full, OSError, ValueError):
            return
        self._last_sent = now
