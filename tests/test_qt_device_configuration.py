import os
import queue
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class DeviceConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def make_page(self, preview=False, password_required=False):
        from view.qt.pages import DeviceConfigurationPage
        from control.MachineConfigSchema import PARAM_LABELS
        controller = SimpleNamespace(strategy_name="complete_workpiece", preview_mode=preview,
                                     is_password_required=lambda: password_required)
        config = {**dict.fromkeys(PARAM_LABELS, 100), "type": "xn_side", "spray_num": 6, "install_orietation": "left",
                  "x_pos_speed": 300, "out_front_x_offset": 100,
                  "flat": {"x_pos_speed": 200, "z_spray_position": 500}}
        with patch("control.MachineConfigFrameControl.list_machine_devices", return_value=[(1, "xn_side"), (7, "xn_side")]), \
             patch("control.MachineConfigFrameControl.load_machine_config_for_ui", return_value=config):
            return DeviceConfigurationPage(controller)

    def test_flat_changes_and_real_device_sn_are_in_save_payload(self):
        page = self.make_page()
        self.assertNotIn("install_orietation", page.fields)
        self.assertNotIn("spray_num", page.fields)
        page.fields["x_pos_speed"].setText("320")
        page.flat_fields["x_pos_speed"].setText("240")
        with patch("control.MachineConfigFrameControl.save_machine_config_from_ui") as save:
            page._save_device()
        self.assertEqual(1, save.call_args.args[0])
        self.assertEqual(320, save.call_args.args[1]["x_pos_speed"])
        self.assertEqual(240, save.call_args.args[1]["flat"]["x_pos_speed"])
        self.assertEqual("100", page.flat_fields["out_front_x_offset"].text())

    def test_preview_blocks_direct_save_calls_and_keeps_readonly_message(self):
        page = self.make_page(preview=True)
        with patch("control.MachineConfigFrameControl.save_machine_config_from_ui") as save:
            page._save_device()
        save.assert_not_called()
        self.assertFalse(page.save_button.isEnabled())
        self.assertIn("只读", page.save_result.text())

    def test_state_updates_do_not_replace_unsaved_speed_edits(self):
        from control.UiState import UiState
        from view.qt.pages import AcquisitionPage
        page = AcquisitionPage(SimpleNamespace())
        state = UiState(strategy_name="continuous_bidirectional", chain_speed=25)
        page.apply_state(state)
        page.speed_spin.setValue(32)
        page.apply_state(state)
        self.assertEqual(32, page.speed_spin.value())

    def test_both_tabs_persist_to_toml_and_notify_same_device(self):
        from model.utils.TomlLoader import TomlLoader
        page = self.make_page()
        page.fields["x_pos_speed"].setText("320")
        page.flat_fields["x_pos_speed"].setText("240")
        page.controller.control_queue = queue.Queue()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MachineConfig.toml"
            path.write_text('[1]\ntype = "xn_side"\nx_pos_speed = 300\n[1.flat]\nx_pos_speed = 200\n', encoding="utf-8")
            with patch("control.MachineConfigFrameControl._get_toml_path", return_value=str(path)), \
                 patch("control.MachineConfigFrameControl._get_param_range_rules", return_value={}):
                page._save_device()
            saved = TomlLoader.load(str(path))["1"]
        self.assertEqual(320, saved["x_pos_speed"])
        self.assertEqual(240, saved["flat"]["x_pos_speed"])
        message = page.controller.control_queue.get_nowait()["machine"]
        self.assertEqual(1, message["sn"])
        self.assertEqual(240, message["flat"]["x_pos_speed"])

    def test_device_list_uses_sn_from_toml_not_combobox_index(self):
        from control.MachineConfigFrameControl import list_machine_devices
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MachineConfig.toml"
            path.write_text('[7]\ntype = "xn_side"\n[1]\ntype = "out_lift"\n', encoding="utf-8")
            with patch("control.MachineConfigFrameControl._get_toml_path", return_value=str(path)):
                devices = list_machine_devices("frame_by_frame")
        self.assertEqual([(1, "out_lift"), (7, "xn_side")], devices)

    def test_preview_blocks_scan_speed_save(self):
        from unittest.mock import Mock
        from view.qt.pages import AcquisitionPage
        setter = Mock()
        page = AcquisitionPage(SimpleNamespace(preview_mode=True, set_chain_speed=setter))
        page._save_speed()
        setter.assert_not_called()
        self.assertFalse(page.save_speed_button.isEnabled())
        self.assertTrue(page.speed_spin.isReadOnly())

    def test_reload_recovers_device_list_after_configuration_is_repaired(self):
        from view.qt.pages import DeviceConfigurationPage
        controller = SimpleNamespace(strategy_name="frame_by_frame")
        with patch("control.MachineConfigFrameControl.list_machine_devices", side_effect=ValueError("duplicate key")):
            page = DeviceConfigurationPage(controller)
        self.assertEqual(0, page.device_selector.count())
        self.assertFalse(page.save_button.isEnabled())

        config = {"type": "out_lift", "out_z_front_offset": 150, "out_z_after_offset": 200}
        with patch("control.MachineConfigFrameControl.list_machine_devices", return_value=[(9, "out_lift")]), \
             patch("control.MachineConfigFrameControl.load_machine_config_for_ui", return_value=config):
            page.reload_button.click()
        self.assertEqual(9, page.device_selector.currentData())
        self.assertEqual("150", page.fields["out_z_front_offset"].text())
        self.assertTrue(page.save_button.isEnabled())

    def test_protected_configuration_stays_readonly_until_edit_is_authorized(self):
        page = self.make_page(password_required=True)
        self.assertTrue(page.fields["x_pos_speed"].isReadOnly())
        self.assertFalse(page.save_button.isEnabled())
        with patch("view.qt.pages.authorize", return_value=False):
            page.edit_button.click()
        self.assertTrue(page.fields["x_pos_speed"].isReadOnly())
        with patch("view.qt.pages.authorize", return_value=True):
            page.edit_button.click()
        self.assertFalse(page.fields["x_pos_speed"].isReadOnly())
        self.assertFalse(page.flat_fields["x_pos_speed"].isReadOnly())
        self.assertTrue(page.save_button.isEnabled())
        page.edit_button.click()
        self.assertTrue(page.fields["x_pos_speed"].isReadOnly())

    def test_locked_configuration_blocks_direct_save_call(self):
        page = self.make_page(password_required=True)
        with patch("control.MachineConfigFrameControl.save_machine_config_from_ui") as save, \
             patch("view.qt.pages.authorize", return_value=True):
            page._save_device()
        save.assert_not_called()

    def test_shutdown_during_authorization_does_not_unlock_or_save(self):
        from control.UiState import UiState
        page = self.make_page(password_required=True)
        def shutdown_during_prompt(*_):
            page.apply_state(UiState(strategy_name="complete_workpiece", stopping=True))
            return True
        with patch("view.qt.pages.authorize", side_effect=shutdown_during_prompt):
            page._toggle_edit()
        page.apply_state(UiState.empty("complete_workpiece"))
        self.assertTrue(page.fields["x_pos_speed"].isReadOnly())

    def test_unprotected_configuration_is_editable_again_after_stop(self):
        from control.UiState import UiState
        page = self.make_page()
        page.apply_state(UiState(strategy_name="complete_workpiece", stopping=True))
        self.assertTrue(page.fields["x_pos_speed"].isReadOnly())
        page.apply_state(UiState.empty("complete_workpiece"))
        self.assertFalse(page.fields["x_pos_speed"].isReadOnly())
