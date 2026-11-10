"""Shared password prompt for safety-sensitive PyQt control actions."""

from datetime import datetime
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit
from model.telemetry.UiState import LogEvent


class PasswordAuthorizationDialog(QDialog):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.verified = False
        self.english = getattr(controller, "strategy_name", "") == "continuous_bidirectional"
        self.setWindowTitle("Operator Authorization" if self.english else "操作授权")
        layout = QFormLayout(self)
        layout.addRow("Account" if self.english else "账户", QLabel("Operator" if self.english else "河村电器"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("Password" if self.english else "操作密码", self.password_input)
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #f56b70;")
        layout.addRow(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        for role, text in ((QDialogButtonBox.StandardButton.Ok, "Confirm" if self.english else "确认"), (QDialogButtonBox.StandardButton.Cancel, "Cancel" if self.english else "取消")):
            button = buttons.button(role)
            if button is not None:
                button.setText(text)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.rejected.connect(self._on_rejected)
        layout.addRow(buttons)

    def _record_warning(self, message: str) -> None:
        record = getattr(self.controller, "record_ui_event", None)
        if callable(record):
            record(LogEvent("WARNING", message, "authorization", datetime.now()))

    def accept(self) -> None:
        try:
            correct = self.controller.verify_password(self.password_input.text())
        except Exception:
            self.error_label.setText("Authorization failed; check configuration." if self.english else "授权校验失败，请检查配置。")
            self._record_warning("操作授权失败：无法校验密码配置")
            self.password_input.clear()
            return
        self.password_input.clear()
        if not correct:
            self.error_label.setText("Incorrect password. Please retry." if self.english else "密码错误，请重试。")
            self._record_warning("操作授权失败：密码错误")
            self.password_input.setFocus()
            return
        self.verified = True
        super().accept()

    def _on_rejected(self) -> None:
        self.password_input.clear()
        self.verified = False
        self._record_warning("操作授权已取消")


def authorize(parent, controller) -> bool:
    if not getattr(controller, "is_password_required", lambda: False)():
        return True
    dialog = PasswordAuthorizationDialog(parent, controller)
    return dialog.exec() == QDialog.DialogCode.Accepted and dialog.verified
