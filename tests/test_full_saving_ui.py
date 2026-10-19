"""Exercise close/preview routing without creating a window or commanding hardware."""

import queue
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from control.MainFrameControl import MainFrameController


class FullEditionUiTests(unittest.TestCase):
    def event(self):
        event = SimpleNamespace(vetoed=False)
        event.CanVeto = lambda: True
        event.Veto = lambda: setattr(event, "vetoed", True)
        return event

    def test_close_keeps_password_gate(self):
        destroyed = []
        controller = SimpleNamespace(_verify_button_password=lambda: False,
                                     Destroy=lambda: destroyed.append(True))
        event = self.event()
        MainFrameController.on_close(controller, event)
        self.assertTrue(event.vetoed)
        self.assertEqual(destroyed, [])

    def test_authorized_close_waits_for_saving_before_destroy(self):
        stopped, destroyed = [], []
        controller = SimpleNamespace(_verify_button_password=lambda: True, running=True,
                                     stopping=False, _close_pending=False,
                                     on_stop=lambda event: stopped.append(True),
                                     Destroy=lambda: destroyed.append(True))
        event = self.event()
        MainFrameController.on_close(controller, event)
        self.assertTrue(event.vetoed)
        self.assertTrue(controller._close_pending)
        self.assertEqual(stopped, [True])
        self.assertEqual(destroyed, [])

    def test_saved_preview_is_not_downsampled_twice_and_preserves_boxes(self):
        displayed = []
        cloud = np.zeros((210001, 3))
        boxes = object()
        controller = SimpleNamespace(
            read_data_config={"point_cloud_preview_voxel_mm": 10},
            gl_canvas=SimpleNamespace(set_points=lambda points: displayed.append(points),
                                      set_boxes=lambda value: displayed.append(value)),
            filter=SimpleNamespace(voxelReductionFilter=lambda *args, **kwargs: self.fail("preview processed twice")))
        messages = queue.Queue()
        messages.put({"points": cloud, "boxes": boxes, "preview_processed": True})
        with patch("control.MainFrameControl.wx.CallAfter", side_effect=lambda func, *args: func(*args)):
            MainFrameController.update_visualization(controller, messages)
        self.assertIs(displayed[0], cloud)
        self.assertEqual(len(displayed[0]), 210001)
        self.assertIs(displayed[1], boxes)


if __name__ == "__main__":
    unittest.main()
