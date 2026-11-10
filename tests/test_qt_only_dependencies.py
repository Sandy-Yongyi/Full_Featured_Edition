"""Prevent reintroducing the retired GUI framework into the application."""

import ast
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class QtOnlyDependencyTests(unittest.TestCase):
    def test_application_sources_have_no_retired_gui_imports(self):
        files = [ROOT / "main.py"]
        for package in ("control", "model", "view"):
            files.extend((ROOT / package).rglob("*.py"))
        offenders = []
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                names = [entry.name for entry in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                if any(name.split(".")[0] in {"wx", "wxgl"} for name in names):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual([], offenders)

    def test_qt_application_can_build_when_retired_framework_is_unavailable(self):
        script = '''
import importlib.abc, sys
class BlockLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'wx', 'wxgl'}:
            raise ImportError('Retired framework is unavailable')
sys.meta_path.insert(0, BlockLegacy())
from model.runtime.qt_main import build_controller
from PyQt6.QtWidgets import QApplication
from view.qt.main_window import IndustrialMainWindow
app = QApplication([])
controller = build_controller()
window = IndustrialMainWindow(controller)
window.apply_state(controller.build_ui_state())
assert not controller.running
assert 'wx' not in sys.modules
'''
        environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
        result = subprocess.run([sys.executable, "-B", "-c", script], cwd=ROOT, env=environment,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)
