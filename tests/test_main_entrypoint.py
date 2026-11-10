import unittest
import os
import tempfile
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


class MainEntrypointTests(unittest.TestCase):
    def test_code_settings_in_main_are_forwarded_to_qt_startup(self):
        import main
        with patch.multiple(main, CONTROL_TYPE=3, DATA_PATH=r"D:\clouds", DATA_NAME="sample.txt", create=True), \
                patch("model.runtime.qt_main.main", return_value=17) as start:
            self.assertEqual(17, main.qt_main())
        start.assert_called_once_with(control_type=3, data_path=r"D:\clouds", data_name="sample.txt")

    def test_qt_controller_uses_project_configuration_from_another_working_directory(self):
        from model.runtime.qt_main import build_controller
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                controller = build_controller()
                self.assertEqual(Path(__file__).resolve().parents[1] / "model" / "tomls", Path(controller._runtime.toml_path))
            finally:
                os.chdir(previous)

    def test_qt_public_entry_uses_the_same_guarded_launcher_as_main(self):
        from model.runtime import qt_main
        with patch("main.main", return_value=9), patch("main.multiprocessing.freeze_support"), \
                patch("main.multiprocessing.set_start_method"), patch("main.disable_console_interaction"):
            self.assertEqual(9, qt_main.launch())

    def test_cold_entrypoint_imports_do_not_create_logs_in_callers_directory(self):
        root = Path(__file__).resolve().parents[1]
        script = (
            "import sys; sys.path.insert(0, sys.argv[1]); import main; from model.runtime import qt_main; "
            "assert 'model.utils.LoggerUtil' not in sys.modules; "
            "assert 'control.PipelineRuntime' not in sys.modules"
        )
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-B", "-c", script, str(root)], cwd=directory, capture_output=True, text=True, timeout=15)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_main_delegates_to_qt_entrypoint_when_single_instance(self):
        import main

        with patch.object(main, "is_already_running", return_value=False), patch.object(main, "qt_main", return_value=17):
            self.assertEqual(17, main.main())
