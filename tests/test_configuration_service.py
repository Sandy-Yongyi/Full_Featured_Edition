import tempfile
import unittest
from pathlib import Path

from model.utils.ConfigurationService import ConfigurationService


class ConfigurationServiceTests(unittest.TestCase):
    def test_save_chain_speed_validates_and_persists_value(self):
        with tempfile.TemporaryDirectory() as directory:
            read_data_path = Path(directory) / "ReadDataConfig.toml"
            read_data_path.write_text("lidar_scan_speed = 25\n", encoding="utf-8")
            mode_path = Path(directory) / "ModeConfig.toml"
            mode_path.write_text("require_password = false\n", encoding="utf-8")
            service = ConfigurationService(read_data_path, mode_path)

            saved_speed = service.save_chain_speed("32")

            self.assertEqual(32, saved_speed)
            self.assertEqual(32, service.load_read_data()["lidar_scan_speed"])
            with self.assertRaisesRegex(ValueError, "1～50"):
                service.save_chain_speed("51")

    def test_password_helpers_create_default_and_honor_password_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            read_data_path = Path(directory) / "ReadDataConfig.toml"
            read_data_path.write_text("lidar_scan_speed = 25\n", encoding="utf-8")
            mode_path = Path(directory) / "ModeConfig.toml"
            mode_path.write_text("require_password = false\n", encoding="utf-8")
            service = ConfigurationService(read_data_path, mode_path)

            service.ensure_password_config()

            self.assertEqual("123456", service.get_configured_password())
            self.assertFalse(service.is_password_required())
