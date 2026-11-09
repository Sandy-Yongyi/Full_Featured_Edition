"""Dark industrial color system shared by Qt views."""

import re

UI_SCALE = 1.25


def ui_px(value: int) -> int:
    """Scale interface dimensions, independent of the OpenGL scene."""
    return int(value * UI_SCALE + 0.5)


BACKGROUND = "#071220"
PANEL = "#0c1b30"
PANEL_ALT = "#10243f"
LINE = "#1a3656"
TEXT = "#dcecff"
MUTED = "#7f9fbe"
CYAN = "#24d5e6"
ORANGE = "#ffb351"
GREEN = "#2bd49d"
RED = "#f56b70"


def build_industrial_stylesheet() -> str:
    stylesheet = f"""
        QMainWindow, QWidget {{ background: {BACKGROUND}; color: {TEXT}; font-family: 'Microsoft YaHei'; font-size: 13px; }}
        QLabel, QCheckBox {{ background: transparent; }}
        QFrame#panel {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 8px; }}
        QPushButton {{ background: #12314b; border: 1px solid #245071; border-radius: 6px; color: {TEXT}; padding: 9px 12px; }}
        QPushButton:hover {{ border-color: {CYAN}; background: #164663; }}
        QPushButton:disabled {{ color: #66809b; background: #101e30; border-color: #19314a; }}
        QPushButton#primary {{ background: #0d6174; border-color: {CYAN}; }}
        QPushButton#danger {{ background: #3b202b; border-color: #7d3645; color: #ffd8da; }}
        QPushButton#primary:disabled, QPushButton#danger:disabled {{ color: #66809b; background: #101e30; border-color: #19314a; }}
        QLineEdit, QSpinBox, QPlainTextEdit, QTableView {{ background: #081728; border: 1px solid {LINE}; border-radius: 5px; color: {TEXT}; padding: 6px; }}
        QComboBox {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 5px; padding: 7px 12px; }}
        QComboBox QAbstractItemView {{ background: {PANEL}; color: {TEXT}; selection-background-color: #123c55; }}
        QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: 5px; }}
        QTabBar::tab {{ background: {PANEL}; color: {MUTED}; padding: 10px 18px; margin-right: 3px; }}
        QTabBar::tab:selected {{ background: {PANEL_ALT}; color: {CYAN}; border-bottom: 2px solid {CYAN}; }}
        QHeaderView::section {{ background: {PANEL_ALT}; color: {TEXT}; padding: 8px; border: none; border-bottom: 1px solid {LINE}; }}
        QListWidget {{ background: #09182a; border: none; outline: none; color: #9ebbd7; }}
        QListWidget::item {{ padding: 10px 12px; margin: 2px 4px; border-radius: 6px; }}
        QListWidget::item:selected {{ background: #123c55; border-left: 3px solid {CYAN}; color: #e9fbff; }}
        QProgressBar {{ background: #17314d; border: none; border-radius: 3px; height: 7px; text-align: center; }}
        QProgressBar::chunk {{ background: {CYAN}; border-radius: 3px; }}
    """
    return re.sub(r"\b(\d+)px\b", lambda match: f"{ui_px(int(match.group(1)))}px", stylesheet)
