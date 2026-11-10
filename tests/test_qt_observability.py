import os
import queue
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ObservabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_many_alarms_do_not_force_controls_outside_minimum_window_height(self):
        from model.telemetry.UiState import UiState
        from view.qt.main_window import IndustrialMainWindow
        window = IndustrialMainWindow(SimpleNamespace())
        alarms = tuple(f"PLC alarm {index}: " + "details " * 8 for index in range(100))
        window.apply_state(UiState(strategy_name="complete_workpiece", alarms=alarms))
        window.centralWidget().layout().activate()

        self.assertLessEqual(window.minimumSizeHint().height(), 760)
        self.assertEqual("\n".join(alarms), window.alarm_banner.text())
        self.assertIs(window.alarm_scroll.widget(), window.alarm_banner)
        self.assertFalse(window.alarm_scroll.isHidden())
        # Exercise only the alert widget on the offscreen platform; the 3D
        # window and its native context are outside this layout regression.
        window.alarm_scroll.setParent(None)
        window.alarm_scroll.resize(1000, 120)
        self.addCleanup(window.alarm_scroll.close)
        window.alarm_scroll.show()
        self.app.processEvents()
        scrollbar = window.alarm_scroll.verticalScrollBar()
        self.assertGreater(scrollbar.maximum(), 0)
        scrollbar.setValue(scrollbar.maximum())
        self.assertGreater(scrollbar.value(), 0)
        window.apply_state(UiState.empty("complete_workpiece"))
        self.assertTrue(window.alarm_scroll.isHidden())
        self.assertTrue(window.alarm_banner.isHidden())

    def test_runtime_and_bridge_errors_are_visible_and_clear_on_recovery(self):
        from view.qt.QtUiBridge import QtUiBridge
        from model.telemetry.UiState import UiState
        from view.qt.main_window import IndustrialMainWindow
        bridge = QtUiBridge(SimpleNamespace())
        window = IndustrialMainWindow(SimpleNamespace(), bridge)
        state = UiState(strategy_name="complete_workpiece", alarms=("点云保存失败",))
        window.apply_state(state)
        self.assertFalse(window.alarm_banner.isHidden())
        self.assertIn("点云保存失败", window.alarm_banner.text())
        bridge.error_raised.emit("状态更新失败", "queue closed")
        self.assertIn("queue closed", window.alarm_banner.text())
        window.apply_state(UiState.empty("complete_workpiece"))
        self.assertTrue(window.alarm_banner.isHidden())

    def test_log_polling_preserves_selection_and_tracks_bounded_snapshot(self):
        from PyQt6.QtGui import QTextCursor
        from model.telemetry.UiState import LogEvent
        from view.qt.widgets import RuntimeLogView
        page = RuntimeLogView()
        entries = tuple(LogEvent("INFO", f"event {i}") for i in range(3))
        page.apply_events(entries)
        cursor = page.textCursor()
        cursor.setPosition(0)
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        page.setTextCursor(cursor)
        selection = cursor.selectedText()
        revision = page.document().revision()
        page.apply_events(entries)
        self.assertEqual(revision, page.document().revision())
        self.assertEqual(selection, page.textCursor().selectedText())
        extra = LogEvent("ERROR", "save failed")
        page.apply_events(entries + (extra,))
        self.assertEqual(selection, page.textCursor().selectedText())
        page.apply_events((entries[-1], extra))
        text = page.toPlainText()
        self.assertNotIn("event 0", text)
        self.assertIn("event 2", text)
        self.assertIn("save failed", text)

    def test_subprocess_stderr_reaches_ui_as_error_event(self):
        from model.telemetry.RuntimeStateCollector import RuntimeStateCollector
        records = queue.Queue()
        records.put(("stderr", "laser disconnected"))
        collector = RuntimeStateCollector(records, None)
        events = collector.poll()["logs"]
        self.assertEqual(1, len(events))
        self.assertEqual("ERROR", events[0].level)
        self.assertEqual("laser disconnected", events[0].message)

    def test_rolling_multiline_unicode_logs_match_the_latest_snapshot(self):
        from model.telemetry.UiState import LogEvent
        from view.qt.widgets import RuntimeLogView
        page = RuntimeLogView()
        first = LogEvent("INFO", "开始 🟢\n采集就绪")
        second = LogEvent("ERROR", "保存故障")
        third = LogEvent("INFO", "停止完成")
        page.apply_events((first, second))
        page.apply_events((second, third))
        self.assertEqual("[ERROR] 保存故障\n[INFO] 停止完成", page.toPlainText())

    def test_realtime_page_only_shows_recent_events(self):
        from model.telemetry.UiState import LogEvent, UiState
        from view.qt.pages import RealtimeControlPage
        page = RealtimeControlPage(SimpleNamespace())
        logs = tuple(LogEvent("INFO", f"event {i}", "stdout") for i in range(8))
        page.apply_state(UiState(strategy_name="complete_workpiece", logs=logs))
        text = page.recent_events.toPlainText()
        self.assertNotIn("event 0", text)
        self.assertIn("event 7", text)

    def test_recent_prints_are_not_displaced_by_logger_or_system_events(self):
        from model.telemetry.UiState import LogEvent, UiState
        from view.qt.pages import RealtimeControlPage
        page = RealtimeControlPage(SimpleNamespace())
        printed = tuple(LogEvent("INFO", f"print {i}", "stdout") for i in range(8))
        others = (LogEvent("INFO", "logger message", "logger"), LogEvent("WARNING", "authorization message", "authorization"), LogEvent("ERROR", "stderr message", "stderr")) * 4
        state = UiState(strategy_name="complete_workpiece", logs=printed + others)
        page.apply_state(state)
        text = page.recent_events.toPlainText()
        self.assertIn("print 3", text)
        self.assertIn("print 7", text)
        self.assertNotIn("print 2", text)
        self.assertNotIn("logger message", text)
        self.assertNotIn("authorization message", text)
        self.assertNotIn("stderr message", text)

    def test_print_fragments_form_one_line_instead_of_several_recent_events(self):
        from control.PipelineRuntime import SubprocessRedirect
        from model.telemetry.RuntimeStateCollector import RuntimeStateCollector
        output = queue.Queue()
        stream = SubprocessRedirect(output)
        print("point cloud", 123, file=stream)
        events = RuntimeStateCollector(output, None).poll()["logs"]
        self.assertEqual(["point cloud 123"], [event.message for event in events])
        self.assertEqual("stdout", events[0].source)
        stream.write("pending")
        stream.flush()
        self.assertEqual(("stdout", "pending"), output.get_nowait())
