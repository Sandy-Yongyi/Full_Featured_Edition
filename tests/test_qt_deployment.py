import os
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


CONFIG_NAMES = (
    "ModeConfig.toml", "ReadDataConfig.toml", "SystemConfig.toml", "PlcConfig.toml",
    "SprayConfig.toml", "ProcessConfig.toml", "LidarConfig.toml",
    "MachineConfig1.toml", "MachineConfig2.toml", "MachineConfig3.toml",
)


class DeploymentTests(unittest.TestCase):
    def make_configs(self, root):
        directory = root / "model" / "tomls"
        directory.mkdir(parents=True)
        for name in CONFIG_NAMES:
            (directory / name).write_text("strategy_name = 2\n" if name == "ModeConfig.toml" else "", encoding="utf-8")
        return directory

    def test_deployment_argument_bypasses_normal_startup(self):
        import main
        checker = Mock(return_value=23)
        previous = Path.cwd()
        try:
            with patch.dict(sys.modules, {"model.runtime.deployment_check": type("Checker", (), {"main": checker})}), \
                    patch.object(sys, "argv", ["main.py", "--check-deployment"]), \
                    patch("main.multiprocessing.freeze_support"), \
                    patch("main.disable_console_interaction"), \
                    patch("main.multiprocessing.set_start_method"), \
                    patch("main.main", return_value=97) as normal_startup:
                self.assertEqual(23, main.launch())
                normal_startup.assert_not_called()
        finally:
            os.chdir(previous)

    def test_config_check_collects_missing_and_invalid_files_without_rewriting_them(self):
        from model.runtime.deployment_check import check_configurations
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configs = self.make_configs(root)
            (configs / "MachineConfig1.toml").write_text("[3]\ntop_chain_hold_enabled = true\ntop_chain_hold_enabled = false\n", encoding="utf-8")
            (configs / "MachineConfig3.toml").unlink()
            before = {path.name: path.read_bytes() for path in configs.iterdir()}

            results = {result.name: result for result in check_configurations(root)}

            self.assertFalse(results["MachineConfig1.toml"].ok)
            self.assertFalse(results["MachineConfig3.toml"].ok)
            self.assertTrue(results["MachineConfig2.toml"].ok)
            self.assertEqual(set(CONFIG_NAMES), set(results))
            self.assertEqual(before, {path.name: path.read_bytes() for path in configs.iterdir()})

    def test_invalid_strategy_is_reported_even_when_toml_syntax_is_valid(self):
        from model.runtime.deployment_check import check_configurations
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configs = self.make_configs(root)
            (configs / "ModeConfig.toml").write_text("strategy_name = true\n", encoding="utf-8")
            results = {result.name: result for result in check_configurations(root)}
            self.assertFalse(results["ModeConfig.toml"].ok)

    def test_failed_configuration_produces_nonzero_exit_without_dumping_config_values(self):
        from model.runtime import deployment_check
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configs = self.make_configs(root)
            (configs / "MachineConfig1.toml").write_text(
                'auth_password = "fixture-secret-value"\nx = 1\nx = 2\n', encoding="utf-8")
            output = io.StringIO()
            with patch("model.runtime.deployment_check.application_directory", return_value=root), contextlib.redirect_stdout(output):
                self.assertEqual(1, deployment_check.main())
            self.assertIn("[FAIL] MachineConfig1.toml", output.getvalue())
            self.assertNotIn("fixture-secret-value", output.getvalue())

    def test_repository_configurations_all_parse_after_confirmed_sn3_conflict_resolution(self):
        from model.runtime.deployment_check import check_configurations
        from model.utils.TomlLoader import TomlLoader
        root = Path(__file__).resolve().parents[1]
        results = check_configurations(root)
        self.assertTrue(all(result.ok for result in results), results)
        config = TomlLoader.load(str(root / "model" / "tomls" / "MachineConfig1.toml"))
        self.assertFalse(config["3"]["top_chain_hold_enabled"])

    def test_platform_plugin_check_reports_missing_qwindows(self):
        from model.runtime.deployment_check import check_windows_plugin
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(check_windows_plugin(root).ok)
            (root / "platforms").mkdir()
            (root / "platforms" / "qwindows.dll").write_bytes(b"fixture")
            self.assertTrue(check_windows_plugin(root).ok)

    def test_cold_deployment_check_from_foreign_directory_never_starts_devices_or_ui(self):
        root = Path(__file__).resolve().parents[1]
        script = """
import sys, socket, multiprocessing
sys.path.insert(0, sys.argv[1])
import main
def forbidden(*args, **kwargs):
    raise AssertionError('Deployment check attempted normal startup or device access')
multiprocessing.Process.start = forbidden
socket.socket.connect = forbidden
main.qt_main = forbidden
main.is_already_running = forbidden
sys.argv = ['main.py', '--check-deployment']
result = main.launch()
from PyQt6.QtWidgets import QApplication
assert QApplication.instance() is None
assert 'control.PipelineRuntime' not in sys.modules
assert 'model.utils.LoggerUtil' not in sys.modules
raise SystemExit(result)
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-B", "-c", script, str(root)], cwd=directory,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                                    env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("[FAIL]", result.stdout)
            self.assertEqual([], list(Path(directory).iterdir()))


if __name__ == "__main__":
    unittest.main()
