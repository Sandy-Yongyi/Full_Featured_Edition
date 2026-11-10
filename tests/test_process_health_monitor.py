import unittest

from model.runtime.ProcessHealthMonitor import ProcessHealthMonitor


class _Process:
    def __init__(self, alive=True):
        self.alive = alive

    def is_alive(self):
        return self.alive


class _Heartbeat:
    def __init__(self, value):
        self.value = value


class _SaveService:
    def __init__(self, messages):
        self.messages = messages

    def poll_status(self):
        return self.messages


class ProcessHealthMonitorTests(unittest.TestCase):
    def test_save_service_error_has_priority(self):
        monitor = ProcessHealthMonitor(unresponsive_timeout_s=60)
        process = _Process(alive=False)

        fault = monitor.check([process], {process: _Heartbeat(90)}, _SaveService([{"type": "error", "message": "disk full"}]), now=100)

        self.assertEqual("save_error", fault.kind)
        self.assertEqual("disk full", fault.detail)

    def test_dead_process_is_reported(self):
        monitor = ProcessHealthMonitor(unresponsive_timeout_s=60)
        process = _Process(alive=False)

        fault = monitor.check([process], {}, None, now=100)

        self.assertEqual("dead_process", fault.kind)
        self.assertIn("_Process", fault.detail)

    def test_stale_heartbeat_is_reported(self):
        monitor = ProcessHealthMonitor(unresponsive_timeout_s=5)
        process = _Process()

        fault = monitor.check([process], {process: _Heartbeat(90)}, None, now=100)

        self.assertEqual("stale_process", fault.kind)
        self.assertIn("10.0", fault.detail)
