from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from view.qt import theme


class Panel(QFrame):
    def __init__(self, title: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(*(theme.ui_px(14),) * 4)
        self.content_layout.setSpacing(theme.ui_px(10))
        if title:
            label = QLabel(title)
            label.setStyleSheet(f"font-weight: 700; color: {theme.TEXT};")
            self.content_layout.addWidget(label)


class StatusBadge(QLabel):
    def __init__(self, text: str = "离线", online: bool = False, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_status(text, online)

    def set_status(self, text: str, online: bool) -> None:
        color = theme.GREEN if online else theme.MUTED
        self.setText(f"● {text}")
        self.setStyleSheet(f"color: {color}; font-size: {theme.ui_px(12)}px;")


class ControlButton(QPushButton):
    def __init__(self, text: str, role: str = "default", parent=None):
        super().__init__(text, parent)
        if role == "primary":
            self.setObjectName("primary")
        elif role == "danger":
            self.setObjectName("danger")


class RuntimeLogView(QPlainTextEdit):
    """Update a bounded event snapshot while preserving unchanged text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self._logs = ()

    def apply_events(self, entries) -> None:
        from PyQt6.QtGui import QTextCursor

        if entries == self._logs:
            return
        scrollbar = self.verticalScrollBar()
        if scrollbar is None:
            return
        old_scroll = scrollbar.value()
        follow_tail = old_scroll >= scrollbar.maximum()
        old = self._logs
        overlap = min(len(old), len(entries))
        while overlap and old[-overlap:] != entries[:overlap]:
            overlap -= 1

        def format_event(event):
            return f"[{event.level}] {event.message}"
        editor = QTextCursor(self.document())
        editor.beginEditBlock()
        removed = old[:len(old) - overlap] if overlap else old
        if removed:
            prefix = "\n".join(map(format_event, removed))
            if overlap:
                prefix += "\n"
            editor.setPosition(0)
            editor.setPosition(len(prefix.encode("utf-16-le")) // 2, QTextCursor.MoveMode.KeepAnchor)
            editor.removeSelectedText()
        additions = entries[overlap:]
        if additions:
            editor.movePosition(QTextCursor.MoveOperation.End)
            editor.insertText(("\n" if overlap else "") + "\n".join(map(format_event, additions)))
        editor.endEditBlock()
        self._logs = entries
        scrollbar.setValue(scrollbar.maximum() if follow_tail else old_scroll)
