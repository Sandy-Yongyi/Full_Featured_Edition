import os
import queue
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class DeviceConfigurationTests(unittest.TestCase):
    def test_selecting_device_restores_white_parameter_hint_after_save(self):
        from view.qt import theme
        page = self.make_page()
        with patch("model.utils.MachineConfiguration.save_machine_config_from_ui"):
            page._save_device()
        self.assertIn(theme.GREEN, page.save_result.styleSheet())
        config = {key: int(field.text()) for key, field in page.fields.items()}
        config["type"] = "xn_side"
        with patch("model.utils.MachineConfiguration.load_machine_config_for_ui", return_value=config):
            page.device_buttons[7].click()
        self.assertEqual("参数可直接修改，点击保存才生效", page.save_result.text())
        self.assertIn("#ffffff", page.save_result.styleSheet())

    def test_parameter_inputs_resize_without_horizontal_scroll(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QLabel
        from view.qt.pages import DeviceConfigurationPage
        from view.qt.theme import build_industrial_stylesheet
        page = DeviceConfigurationPage(SimpleNamespace(strategy_name="frame_by_frame"))
        page.setStyleSheet(build_industrial_stylesheet())
        self.addCleanup(page.close)
        widths = []
        for width in (800, 1200, 1600):
            page.resize(width, 760)
            page.show()
            self.app.processEvents()
            area = page.tabs.widget(0)
            self.assertEqual(Qt.ScrollBarPolicy.ScrollBarAlwaysOff, area.horizontalScrollBarPolicy())
            self.assertEqual(0, area.horizontalScrollBar().maximum())
            for caption in area.widget().findChildren(QLabel):
                self.assertFalse(caption.wordWrap())
                self.assertGreaterEqual(caption.width(), caption.sizeHint().width())
            for field in page.fields.values():
                self.assertLessEqual(field.geometry().right(), area.viewport().width())
            widths.append(next(iter(page.fields.values())).width())
        self.assertLess(widths[0], widths[1])
        self.assertLess(widths[1], widths[2])
        self.assertEqual("参数可直接修改，点击保存才生效", page.save_result.text())

    def test_strategy_one_buttons_match_control_names_and_read_machineconfig_one(self):
        from view.qt.pages import DeviceConfigurationPage, DeviceControlPage
        from model.utils.MachineConfiguration import _get_toml_path
        from PyQt6.QtWidgets import QComboBox
        self.assertEqual('MachineConfig1.toml', Path(_get_toml_path('frame_by_frame')).name)
        page = DeviceConfigurationPage(SimpleNamespace(strategy_name='frame_by_frame'))
        self.assertEqual([], page.findChildren(QComboBox))
        self.assertEqual(list(range(6)), list(page.device_buttons))
        for sn, name in enumerate(DeviceControlPage.DEVICE_NAMES):
            self.assertEqual(name, page.device_buttons[sn].text())
            page.device_buttons[sn].click()
            self.assertEqual(sn, page._loaded_sn)
            self.assertEqual('frame_by_frame', page._loaded_strategy)
            common = ['out_front_x_offset', 'out_after_x_offset', 'in_front_x_offset', 'in_after_x_offset']
            tail = ['out_z_front_offset', 'out_z_after_offset', 'search_front_z_offset', 'search_after_z_offset', 'x_pos_speed', 'x_recip_speed', 'y_pos_speed', 'y_recip_speed']
            expected = (common + ['out_up_y_offset', 'in_up_y_offset'] + tail if sn % 3 == 0 else
                        common + ['out_down_y_offset', 'in_down_y_offset'] + tail if sn % 3 == 1 else
                        ['out_front_x_offset', 'out_up_y_offset', 'out_down_y_offset', 'out_z_front_offset',
                         'out_z_after_offset', 'x_pos_speed', 'y_recip_speed'])
            self.assertEqual(expected, list(page.fields))
            scroller = page.tabs.widget(0)
            self.assertEqual(len(expected) + 1, scroller.widget().layout().rowCount())
            self.assertIs(page.device_grid.itemAtPosition(sn, 0).widget(), page.device_buttons[sn])
            self.assertTrue(scroller.widgetResizable())
            self.assertEqual(1, sum(b.isChecked() for b in page.device_buttons.values()))
            self.assertEqual(f'{name}设备参数', page.parameter_title.text())
            self.assertIn('background: #0d6174', page.device_buttons[sn].styleSheet())
            self.assertTrue(all(not b.styleSheet() for key, b in page.device_buttons.items() if key != sn))
        with patch('model.utils.MachineConfiguration.save_machine_config_from_ui') as save:
            page._save_device()
        self.assertEqual(5, save.call_args.args[0])
        self.assertEqual('frame_by_frame', save.call_args.kwargs['strategy_name'])

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def make_page(self, preview=False, password_required=False):
        from view.qt.pages import DeviceConfigurationPage
        from view.qt.MachineConfigSchema import PARAM_LABELS
        controller = SimpleNamespace(strategy_name="complete_workpiece", preview_mode=preview, is_password_required=lambda: password_required)
        config = {**dict.fromkeys(PARAM_LABELS, 100), "type": "xn_side", "spray_num": 6, "install_orietation": "left",
                  "x_pos_speed": 300, "out_front_x_offset": 100,
                  "flat": {"x_pos_speed": 200, "z_spray_position": 500}}
        with patch("model.utils.MachineConfiguration.list_machine_devices", return_value=[(1, "xn_side"), (7, "xn_side")]), \
                patch("model.utils.MachineConfiguration.load_machine_config_for_ui", return_value=config):
            return DeviceConfigurationPage(controller)

    def test_flat_changes_and_real_device_sn_are_in_save_payload(self):
        page = self.make_page()
        self.assertNotIn("install_orietation", page.fields)
        self.assertNotIn("spray_num", page.fields)
        page.fields["x_pos_speed"].setText("320")
        page.flat_fields["x_pos_speed"].setText("240")
        with patch("model.utils.MachineConfiguration.save_machine_config_from_ui") as save:
            page._save_device()
        self.assertEqual(1, save.call_args.args[0])
        self.assertEqual(320, save.call_args.args[1]["x_pos_speed"])
        self.assertEqual(240, save.call_args.args[1]["flat"]["x_pos_speed"])
        self.assertEqual("100", page.flat_fields["out_front_x_offset"].text())

    def test_preview_blocks_direct_save_calls_and_keeps_readonly_message(self):
        page = self.make_page(preview=True)
        with patch("model.utils.MachineConfiguration.save_machine_config_from_ui") as save:
            page._save_device()
        save.assert_not_called()
        self.assertFalse(page.save_button.isEnabled())
        self.assertIn("只读", page.save_result.text())

    def test_both_tabs_persist_to_toml_and_notify_same_device(self):
        from model.utils.TomlLoader import TomlLoader
        page = self.make_page()
        page.fields["x_pos_speed"].setText("320")
        page.flat_fields["x_pos_speed"].setText("240")
        page.controller.control_queue = queue.Queue()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MachineConfig.toml"
            path.write_text('[1]\ntype = "xn_side"\nx_pos_speed = 300\n[1.flat]\nx_pos_speed = 200\n', encoding="utf-8")
            with patch("model.utils.MachineConfiguration._get_toml_path", return_value=str(path)), \
                    patch("model.utils.MachineConfiguration._get_param_range_rules", return_value={}):
                page._save_device()
            saved = TomlLoader.load(str(path))["1"]
        self.assertEqual(320, saved["x_pos_speed"])
        self.assertEqual(240, saved["flat"]["x_pos_speed"])
        message = page.controller.control_queue.get_nowait()["machine"]
        self.assertEqual(1, message["sn"])
        self.assertEqual(240, message["flat"]["x_pos_speed"])

    def test_device_list_uses_sn_from_toml_not_combobox_index(self):
        from model.utils.MachineConfiguration import list_machine_devices
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MachineConfig.toml"
            path.write_text('[7]\ntype = "xn_side"\n[1]\ntype = "out_lift"\n', encoding="utf-8")
            with patch("model.utils.MachineConfiguration._get_toml_path", return_value=str(path)):
                devices = list_machine_devices("frame_by_frame")
        self.assertEqual([(1, "out_lift"), (7, "xn_side")], devices)

    def test_reload_recovers_device_list_after_configuration_is_repaired(self):
        from view.qt.pages import DeviceConfigurationPage
        controller = SimpleNamespace(strategy_name="frame_by_frame")
        with patch("model.utils.MachineConfiguration.list_machine_devices", side_effect=ValueError("duplicate key")):
            page = DeviceConfigurationPage(controller)
        self.assertEqual({}, page.device_buttons)
        self.assertFalse(page.save_button.isEnabled())

        config = {"type": "out_lift", "out_z_front_offset": 150, "out_z_after_offset": 200}
        with patch("model.utils.MachineConfiguration.list_machine_devices", return_value=[(9, "out_lift")]), \
                patch("model.utils.MachineConfiguration.load_machine_config_for_ui", return_value=config):
            page._reload_devices()
        self.assertEqual(9, page.selected_device_sn)
        self.assertEqual("150", page.fields["out_z_front_offset"].text())
        self.assertTrue(page.save_button.isEnabled())

    def test_protected_configuration_authorizes_only_on_save(self):
        with patch("view.qt.pages.authorize") as auth:
            page = self.make_page(password_required=True)
            page.fields["x_pos_speed"].setText("350")
            auth.assert_not_called()
        self.assertFalse(page.fields["x_pos_speed"].isReadOnly())
        self.assertTrue(page.save_button.isEnabled())
        self.assertFalse(hasattr(page, "edit_button"))
        self.assertFalse(hasattr(page, "reload_button"))
        self.assertEqual("参数", page.tabs.tabText(0))
        with patch("model.utils.MachineConfiguration.save_machine_config_from_ui") as save, \
                patch("view.qt.pages.authorize", return_value=False) as auth:
            page.save_button.click()
            auth.assert_called_once()
            save.assert_not_called()
        self.assertEqual("350", page.fields["x_pos_speed"].text())
        with patch("model.utils.MachineConfiguration.save_machine_config_from_ui") as save, \
                patch("view.qt.pages.authorize", return_value=True):
            page.save_button.click()
            self.assertEqual(350, save.call_args.args[1]["x_pos_speed"])

    def test_shutdown_during_save_authorization_does_not_save(self):
        from model.telemetry.UiState import UiState
        page = self.make_page(password_required=True)

        def shutdown_during_prompt(*_):
            page.apply_state(UiState(strategy_name="complete_workpiece", stopping=True))
            return True
        with patch("view.qt.pages.authorize", side_effect=shutdown_during_prompt), \
                patch("model.utils.MachineConfiguration.save_machine_config_from_ui") as save:
            page._save_device()
            save.assert_not_called()
        self.assertTrue(page.fields["x_pos_speed"].isReadOnly())
        page.apply_state(UiState.empty("complete_workpiece"))
        self.assertFalse(page.fields["x_pos_speed"].isReadOnly())

    def test_unprotected_configuration_is_editable_again_after_stop(self):
        from model.telemetry.UiState import UiState
        page = self.make_page()
        page.apply_state(UiState(strategy_name="complete_workpiece", stopping=True))
        self.assertTrue(page.fields["x_pos_speed"].isReadOnly())
        page.apply_state(UiState.empty("complete_workpiece"))
        self.assertFalse(page.fields["x_pos_speed"].isReadOnly())
