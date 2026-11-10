import threading
import unittest

from model.runtime.ShutdownCoordinator import ShutdownCoordinator


class ShutdownCoordinatorTests(unittest.TestCase):
    def test_request_stop_runs_worker_once_and_reports_its_errors(self):
        started = threading.Event()
        release = threading.Event()
        completed = threading.Event()
        results = []

        def stop_workers():
            started.set()
            release.wait(timeout=1)
            return ["point cloud save timeout"]

        coordinator = ShutdownCoordinator(stop_workers, lambda errors: (results.append(errors), completed.set()))

        self.assertTrue(coordinator.request_stop())
        self.assertTrue(started.wait(timeout=1))
        self.assertFalse(coordinator.request_stop())
        release.set()
        self.assertTrue(completed.wait(timeout=1))
        self.assertEqual([["point cloud save timeout"]], results)

    def test_worker_exception_is_reported_as_an_error(self):
        completed = threading.Event()
        results = []

        def stop_workers():
            raise RuntimeError("PLC did not stop")

        coordinator = ShutdownCoordinator(stop_workers, lambda errors: (results.append(errors), completed.set()))

        self.assertTrue(coordinator.request_stop())
        self.assertTrue(completed.wait(timeout=1))
        self.assertEqual([["PLC did not stop"]], results)
