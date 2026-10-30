import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class AuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_incorrect_password_shows_error_then_correct_password_can_retry(self):
        from view.qt.auth import PasswordAuthorizationDialog
        events = []
        controller = SimpleNamespace(verify_password=lambda value: value == "correct-secret",
                                     record_ui_event=events.append)
        dialog = PasswordAuthorizationDialog(None, controller)
        dialog.password_input.setText("wrong-secret")
        dialog.accept()
        self.assertFalse(dialog.verified)
        self.assertIn("密码错误", dialog.error_label.text())
        dialog.password_input.setText("correct-secret")
        dialog.accept()
        self.assertTrue(dialog.verified)
        self.assertEqual("", dialog.password_input.text())
        self.assertEqual("WARNING", events[0].level)
        self.assertNotIn("secret", events[0].message)

    def test_cancel_records_warning_without_password_text(self):
        from view.qt.auth import PasswordAuthorizationDialog
        events = []
        dialog = PasswordAuthorizationDialog(None, SimpleNamespace(record_ui_event=events.append))
        dialog.password_input.setText("private-value")
        dialog.reject()
        self.assertFalse(dialog.verified)
        self.assertEqual("", dialog.password_input.text())
        self.assertEqual("WARNING", events[0].level)
        self.assertNotIn("private-value", events[0].message)
