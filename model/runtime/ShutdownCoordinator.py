"""UI-independent, single-flight coordination for safe pipeline shutdown."""

from __future__ import annotations

import threading
from collections.abc import Callable


class ShutdownCoordinator:
    """Run a blocking worker shutdown once without blocking a UI event loop."""

    def __init__(
        self,
        stop_workers: Callable[[], list[str] | None],
        on_complete: Callable[[list[str]], None],
    ):
        self._stop_workers = stop_workers
        self._on_complete = on_complete
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def request_stop(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._thread = threading.Thread(target=self._run, name="PointCloudShutdown", daemon=False)
            self._thread.start()
            return True

    def _run(self) -> None:
        try:
            errors = list(self._stop_workers() or [])
        except Exception as exc:
            errors = [str(exc)]
        self._on_complete(errors)
