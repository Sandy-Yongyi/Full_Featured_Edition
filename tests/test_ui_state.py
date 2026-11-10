import unittest


class UiStateTests(unittest.TestCase):
    def test_empty_state_uses_safe_offline_defaults(self):
        from model.telemetry.UiState import UiState

        state = UiState.empty("complete_workpiece")

        self.assertFalse(state.running)
        self.assertFalse(state.stopping)
        self.assertEqual(state.strategy_name, "complete_workpiece")
        self.assertEqual(state.devices, ())
        self.assertEqual(state.logs, ())

    def test_log_history_keeps_only_latest_events(self):
        from model.telemetry.UiState import LogEvent, UiState

        state = UiState.empty("frame_by_frame")
        for index in range(3):
            state = state.with_log(LogEvent(level="info", message=str(index)), limit=2)

        self.assertEqual([event.message for event in state.logs], ["1", "2"])
