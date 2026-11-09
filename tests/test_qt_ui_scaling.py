import unittest

from view.qt import theme


class UiScalingTests(unittest.TestCase):
    def test_scaled_dimensions_and_stylesheet(self):
        self.assertEqual(theme.ui_px(190), 238)
        self.assertEqual(theme.ui_px(12), 15)
        stylesheet = theme.build_industrial_stylesheet()
        self.assertIn('font-size: 16px', stylesheet)
        self.assertIn('padding: 11px 15px', stylesheet)
