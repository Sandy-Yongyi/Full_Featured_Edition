import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]


class DeveloperModesTests(unittest.TestCase):
    def wait_for(self, center, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            center.poll_once()
            if predicate(center.build_ui_state()):
                return center.build_ui_state()
            time.sleep(0.02)
        self.fail(f"Timeout waiting for developer runtime: {center.build_ui_state().alarms}")

    def stop_center(self, center):
        center.stop()
        self.wait_for(center, lambda state: not state.stopping)
        self.assertFalse(center._runtime.has_live_workers())

    def test_default_runtime_keeps_delivery_mode_two(self):
        from control.PipelineRuntime import PipelineRuntime
        self.assertEqual(2, getattr(PipelineRuntime(), "control_type", None))

    def configure(self, root, strategy=2):
        config = root / "config"
        shutil.copytree(ROOT / "model" / "tomls", config)
        (config / "ModeConfig.toml").write_text(f"strategy_name = {strategy}\nspray_mode = 0\nrequire_password = false\n", encoding="utf-8")
        from model.utils.TomlLoader import TomlLoader
        TomlLoader.save({"translate_data_origin": 1}, str(config / "ReadDataConfig.toml"))
        return str(config)

    def test_view_mode_loads_real_txt_into_qt_scene_without_device_or_save_workers(self):
        from PyQt6.QtWidgets import QApplication
        from model.runtime.qt_main import build_controller
        from view.qt.pages import RealtimeControlPage
        qt_app = QApplication.instance() or QApplication([])
        self.addCleanup(lambda: qt_app.processEvents())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.txt"
            path.write_text("0 0 0 255 0 0\n100 200 300 0 255 0\n", encoding="utf-8")
            with patch("control.PipelineRuntime.PlcCommunicationProcess.create") as plc, \
                    patch("control.PipelineRuntime.LidarAcquisitionProcess") as lidar, \
                    patch("control.PipelineRuntime.PointCloudSaveService.from_config_file") as saving:
                center = build_controller(control_type=3, data_path=str(path))
                center._runtime.read_data_config["workpiece_origin_side"] = "left"
                center.start()
                try:
                    state = self.wait_for(center, lambda state: state.points is not None)
                    self.assertIsNotNone(state.points, state.alarms)
                    page = RealtimeControlPage(center)
                    page.apply_state(state)
                    np.testing.assert_array_equal([[0, 0, 0], [100, 200, 300]], page.point_cloud_view.points)
                    self.assertTrue(np.all(page.point_cloud_view.colors.max(axis=1) >= 0.8))
                    self.assertTrue(np.all(page.point_cloud_view.colors[:, 0] < 0.35))
                    self.assertFalse(any(device.online for device in state.devices))
                    self.assertTrue(center.preview_mode)
                    self.assertEqual(1, len(center._runtime.processes))
                    plc.assert_not_called()
                    lidar.assert_not_called()
                    saving.assert_not_called()
                finally:
                    self.stop_center(center)
                self.assertFalse(center._runtime.has_live_workers())
                self.assertIsNone(center.build_ui_state().points)
                path.write_text("9 8 7\n", encoding="utf-8")
                center.start()
                try:
                    state = self.wait_for(center, lambda state: state.points is not None)
                    np.testing.assert_array_equal([[9, 8, 7]], state.points)
                finally:
                    self.stop_center(center)

    def test_missing_file_is_rejected_before_plc_can_start(self):
        from control.PipelineRuntime import PipelineRuntime
        with tempfile.TemporaryDirectory() as directory:
            for control_type in (1, 3):
                with self.subTest(control_type=control_type), patch("control.PipelineRuntime.PlcCommunicationProcess.create") as plc:
                    runtime = PipelineRuntime(control_type=control_type, data_path=str(Path(directory) / "missing.txt"))
                    with self.assertRaises((ValueError, FileNotFoundError)):
                        runtime.start_pipeline()
                    self.assertFalse(runtime.running)
                    self.assertFalse(runtime.processes)
                    plc.assert_not_called()

    def test_file_view_worker_uses_the_same_right_origin_as_live_and_txt_replay(self):
        from control.PipelineRuntime import PipelineRuntime
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "sample.txt"
            contents = "100 10 0\n200 20 100\n"
            path.write_text(contents, encoding="utf-8")
            runtime = PipelineRuntime(self.configure(root), control_type=3, data_path=str(path))
            runtime.read_data_config.update(translate_data_origin=1, workpiece_origin_side="right", workpiece_origin_reference_x=1000)
            runtime.start_pipeline()
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    snapshot = runtime.poll()
                    if snapshot.get("points") is not None:
                        break
                    time.sleep(0.02)
                self.assertIsNotNone(snapshot.get("points"), snapshot.get("alarms"))
                np.testing.assert_array_equal([[900, 10, 0], [800, 20, 100]], snapshot["points"])
                self.assertEqual(contents, path.read_text(encoding="utf-8"))
                self.assertFalse(any(device.online for device in snapshot["devices"]))
            finally:
                runtime.stop_pipeline()

    def test_txt_plc_mode_restores_strategy_specific_workers_without_lidar_or_saving(self):
        from control.PipelineRuntime import PipelineRuntime
        for strategy, expected in ((1, 2), (2, 3)):
            with self.subTest(strategy=strategy), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "combined_sample.txt"
                path.write_text("0 0 0\n1 1 1\n", encoding="utf-8")
                runtime = PipelineRuntime(self.configure(root, strategy), control_type=1, data_path=str(path))
                with patch("multiprocessing.Process.start"), \
                        patch("control.PipelineRuntime.LidarAcquisitionProcess") as lidar, \
                        patch("control.PipelineRuntime.PointCloudSaveService.from_config_file") as saving:
                    runtime.start_pipeline()
                self.assertEqual(expected, len(runtime.processes))
                self.assertEqual("DataProcessWorker", type(runtime.processes[0]).__name__)
                self.assertEqual("PlcCommunicationProcess", type(runtime.processes[-1]).__name__)
                loader, plc = runtime.processes[0], runtime.processes[-1]
                self.assertIs(loader.machine_data_queue, plc.raw_data_queue)
                self.assertIs(loader.pulse_queue, plc.pulse_queue)
                if strategy == 2:
                    processing = runtime.processes[1]
                    self.assertIs(processing.raw_data_queue, plc.raw_data_queue)
                    self.assertIs(processing.machine_data_queue, plc.machine_data_queue)
                self.assertIsNone(runtime.save_service)
                lidar.assert_not_called()
                saving.assert_not_called()

    def test_txt_plc_unsupported_strategy_is_rejected_before_any_worker_starts(self):
        from control.PipelineRuntime import PipelineRuntime
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "combined_sample.txt"
            path.write_text("0 0 0\n", encoding="utf-8")
            runtime = PipelineRuntime(self.configure(root, 3), control_type=1, data_path=str(path))
            with patch("multiprocessing.Process.start") as start:
                with self.assertRaisesRegex(ValueError, "TXT.*1.*2"):
                    runtime.start_pipeline()
                start.assert_not_called()
            self.assertFalse(runtime.running)

    def test_view_mode_cannot_write_production_settings_or_send_control(self):
        from control.PipelineRuntime import PipelineRuntime
        runtime = PipelineRuntime(control_type=3, data_path="unused.txt")
        with patch.object(runtime.configuration_service, "save_chain_speed") as save:
            with self.assertRaises(RuntimeError):
                runtime.save_chain_speed(30)
            with self.assertRaises(RuntimeError):
                runtime.send_control({"lidar_scan_speed": 30})
            save.assert_not_called()

    def test_malformed_txt_reports_error_and_stops_file_worker(self):
        from model.runtime.qt_main import build_controller
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.txt"
            path.write_text("1 2\n", encoding="utf-8")
            center = build_controller(control_type=3, data_path=str(path))
            center.start()
            try:
                state = self.wait_for(center, lambda state: bool(state.alarms) and not state.stopping)
                self.assertFalse(state.running)
                self.assertIsNone(state.points)
                self.assertIn("XYZ", " ".join(state.alarms))
                self.assertFalse(center._runtime.has_live_workers())
            finally:
                if center.running or center.stopping:
                    self.stop_center(center)

    def test_directory_dataset_selection_and_mixed_rgb_inputs(self):
        from acquisition_sdk._internal.pointcloud.PointCloudFileProcess import resolve_txt_files, load_txt_cloud
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "left_a.txt").write_text("1 2 3 255 0 0\n", encoding="utf-8")
            (root / "right_a.txt").write_text("4 5 6\n", encoding="utf-8")
            (root / "combined_b.txt").write_text("10 20 30\n", encoding="utf-8")
            files = resolve_txt_files(root, "left_a.txt")
            self.assertEqual(["left_a.txt", "right_a.txt"], [Path(p).name for p in files])
            cloud = load_txt_cloud(files)
            np.testing.assert_array_equal([[1, 2, 3], [4, 5, 6]], cloud[:, :3])
            np.testing.assert_allclose(cloud[:, 3:], [[1, 0, 0], [0.14, 0.84, 0.9]])

    def test_plain_single_txt_is_accepted_by_same_origin_legacy_replay(self):
        import queue
        from control.DataProcessWorker import DataProcessWorker
        from model.utils.TomlLoader import TomlLoader
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.configure(root, 1)
            TomlLoader.save({"z_threshold": 10}, str(Path(config) / "ReadDataConfig.toml"))
            path = root / "ordinary.txt"
            path.write_text("1 2 0\n3 4 20\n", encoding="utf-8")
            frames = queue.Queue()
            worker = DataProcessWorker(queue.Queue(), queue.Queue(), frames, str(path), config_dir=config)
            worker._load_all_frames()
            for stack in worker.all_frames.values():
                self.assertEqual(3, len(stack))
                self.assertEqual(0, len(stack[1]))
            self.assertEqual(2, len(frames.get_nowait()["points"]))

    def test_delivery_process_combinations_for_all_three_strategies_are_preserved(self):
        from control.PipelineRuntime import PipelineRuntime
        for strategy, expected in ((1, 3), (2, 4), (3, 3)):
            with self.subTest(strategy=strategy), tempfile.TemporaryDirectory() as directory:
                runtime = PipelineRuntime(self.configure(Path(directory), strategy))
                saver = Mock()
                saver.pool.descriptor = {}
                with patch("multiprocessing.Process.start"), \
                        patch("control.PipelineRuntime.PointCloudSaveService.from_config_file", return_value=saver):
                    runtime.start_pipeline()
                self.assertEqual(expected, len(runtime.processes))
                self.assertIs(saver.worker, runtime.processes[0])
                self.assertEqual("LidarAcquisitionProcess", type(runtime.processes[1]).__name__)
                self.assertEqual("PlcCommunicationProcess", type(runtime.processes[-1]).__name__)
                self.assertEqual(expected, len(runtime.process_heartbeats))
                self.assertIsNone(runtime.file_loader)

    def test_developer_arguments_default_to_delivery_and_require_explicit_input(self):
        import contextlib
        import io
        from model.runtime.qt_main import parse_launch_arguments
        self.assertEqual(2, parse_launch_arguments([]).control_type)
        args = parse_launch_arguments(["--control-type", "3", "--data-path", "cloud.txt"])
        self.assertEqual(3, args.control_type)
        self.assertEqual("cloud.txt", args.data_path)
        for arguments in (["--control-type", "1"], ["--control-type", "3"], ["--data-path", "cloud.txt"], ["--control-type", "4"]):
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    parse_launch_arguments(arguments)
                self.assertEqual(2, error.exception.code)

    def test_code_defaults_work_without_arguments_and_explicit_cli_can_override_them(self):
        from model.runtime.qt_main import parse_launch_arguments
        for mode in (1, 3):
            with self.subTest(mode=mode):
                args = parse_launch_arguments([], control_type=mode, data_path=r"D:\clouds", data_name="sample.txt")
                self.assertEqual(mode, args.control_type)
                self.assertEqual(r"D:\clouds", args.data_path)
                self.assertEqual("sample.txt", args.data_name)
        args = parse_launch_arguments([], control_type=2, data_path=r"D:\clouds", data_name="sample.txt")
        self.assertEqual(2, args.control_type)
        self.assertIsNone(args.data_path)
        self.assertIsNone(args.data_name)
        args = parse_launch_arguments(["--control-type", "3", "--data-path", "other.txt"],
                                      control_type=2, data_path=r"D:\clouds")
        self.assertEqual(3, args.control_type)
        self.assertEqual("other.txt", args.data_path)
        args = parse_launch_arguments(["--control-type", "2"], control_type=3, data_path=r"D:\clouds")
        self.assertEqual(2, args.control_type)
        self.assertIsNone(args.data_path)

    def test_view_window_uses_import_controls_and_readonly_configuration(self):
        from PyQt6.QtWidgets import QApplication
        from model.runtime.qt_main import build_controller
        from view.qt.main_window import IndustrialMainWindow
        qt_app = QApplication.instance() or QApplication([])
        self.addCleanup(lambda: qt_app.processEvents())
        center = build_controller(control_type=3, data_path="unused.txt")
        window = IndustrialMainWindow(center)
        self.assertIn("只画图", window.windowTitle())
        self.assertIn("导入 TXT", window.realtime_page.start_button.text())
        self.assertIn("停止查看", window.realtime_page.stop_button.text())
        self.assertFalse(window.configuration_page.save_button.isEnabled())
        self.assertFalse(center.is_password_required())

    def test_all_modes_wait_for_manual_start_or_import(self):
        from model.runtime import qt_main
        __import__("view.qt.QtUiBridge")
        for control_type in (1, 2, 3):
            arguments = ["main.py"]
            if control_type != 2:
                arguments += ["--control-type", str(control_type), "--data-path", "cloud.txt"]
            with self.subTest(control_type=control_type), \
                    patch("sys.argv", arguments), \
                    patch("model.runtime.qt_main.build_controller"), \
                    patch("PyQt6.QtWidgets.QApplication") as application, \
                    patch("PyQt6.QtCore.QTimer") as timer, \
                    patch("view.qt.QtUiBridge.QtUiBridge"), \
                    patch("view.qt.main_window.IndustrialMainWindow") as window:
                application.instance.return_value.exec.return_value = 17
                self.assertEqual(17, qt_main.main())
                timer.singleShot.assert_not_called()
                window.return_value.realtime_page._start.assert_not_called()
