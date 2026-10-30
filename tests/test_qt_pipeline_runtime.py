import unittest
from unittest.mock import patch


class QtPipelineRuntimeTests(unittest.TestCase):
    def test_invalid_machine_configuration_is_rejected_before_any_worker_starts(self):
        import tempfile
        from pathlib import Path
        from control.QtPipelineRuntime import QtPipelineRuntime

        runtime = QtPipelineRuntime()
        with tempfile.TemporaryDirectory() as directory:
            config_dir = Path(directory)
            (config_dir / "ModeConfig.toml").write_text('strategy_name = 2\nspray_mode = 0\n', encoding="utf-8")
            (config_dir / "MachineConfig2.toml").write_text('[1]\nx_pos_speed = 300\nx_pos_speed = 500\n', encoding="utf-8")
            runtime.toml_path = str(config_dir)
            runtime.mode_config_path = str(config_dir / "ModeConfig.toml")
            runtime.strategy_name = "complete_workpiece"
            with patch("control.DataProcessingProcess.DataProcessingProcess"), \
                 patch("control.QtPipelineRuntime.manage_log_files"), \
                 patch("control.QtPipelineRuntime.PointCloudSaveService.from_config_file") as create_saver, \
                 patch("control.QtPipelineRuntime.LidarAcquisitionProcess") as create_lidar, \
                 patch("control.QtPipelineRuntime.PlcCommunicationProcess.create") as create_plc:
                with self.assertRaisesRegex(ValueError, "MachineConfig2.toml"):
                    runtime.start_pipeline()
            create_saver.assert_not_called()
            create_lidar.assert_not_called()
            create_plc.assert_not_called()
        self.assertFalse(runtime.running)
        self.assertEqual([], runtime.processes)

    def test_shutdown_retains_live_workers_and_shared_service(self):
        from control.QtPipelineRuntime import QtPipelineRuntime

        class StuckProcess:
            def is_alive(self):
                return True

        runtime = QtPipelineRuntime()
        process = StuckProcess()
        runtime.processes = [process]
        runtime.running = True
        with patch("control.QtPipelineRuntime.stop_pipeline", return_value=[]):
            errors = runtime.stop_pipeline()
        self.assertTrue(errors)
        self.assertEqual([process], runtime.processes)
        with self.assertRaisesRegex(RuntimeError, "禁止重新启动"):
            runtime.start_pipeline()

    def test_runtime_loads_existing_production_configuration_without_starting_workers(self):
        from control.QtPipelineRuntime import QtPipelineRuntime

        runtime = QtPipelineRuntime()

        self.assertIn(runtime.strategy_name, {"continuous_bidirectional", "frame_by_frame", "complete_workpiece"})
        self.assertGreater(runtime.chain_speed, 0)
        self.assertEqual([], runtime.processes)
        self.assertIsNotNone(runtime.control_queue)
        devices = runtime.poll()["devices"]
        self.assertEqual(("PLC", "激光", "伺服"), tuple(device.name for device in devices))
        self.assertFalse(any(device.online for device in devices))

    def test_qt_application_builder_connects_runtime_to_control_center(self):
        from qt_main import build_controller

        controller = build_controller()

        self.assertEqual(controller.build_ui_state().chain_speed, controller._runtime.chain_speed)

    def test_control_center_exposes_existing_password_policy(self):
        from qt_main import build_controller

        controller = build_controller()

        self.assertIsInstance(controller.is_password_required(), bool)
        self.assertFalse(controller.verify_password("definitely-not-the-password"))

