import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class QtPreviewTests(unittest.TestCase):
    def test_preview_controller_starts_with_empty_scene_and_offline_devices(self):
        from model.runtime.qt_preview import PreviewController

        state = PreviewController().build_ui_state()

        self.assertFalse(state.running)
        self.assertEqual("complete_workpiece", state.strategy_name)
        self.assertGreater(len(state.devices), 0)
        self.assertIsNone(state.points)
        self.assertFalse(any(device.online for device in state.devices))
        self.assertTrue(PreviewController().preview_mode)
