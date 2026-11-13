import codecs
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acquisition_sdk._internal.pointcloud.PointCloudSaveService import PointCloudSaveService


class SaveConfigLoadingTests(unittest.TestCase):
    def test_service_reads_bom_configuration_through_existing_toml_loader(self):
        self.assertTrue(hasattr(PointCloudSaveService, "from_config_file"),
                        "saving service needs a TomlLoader-backed file entry point")
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "ReadDataConfig.toml"
            path.write_bytes(codecs.BOM_UTF8 + (
                '# 保存参数\r\npoint_cloud_save_block_mb = 0.01\r\n'
                'point_cloud_save_block_count = 8\r\npoint_cloud_save_format = "npy"\r\n').encode("utf-8"))
            before = path.read_bytes()
            service = PointCloudSaveService.from_config_file(path, directory)
            try:
                self.assertEqual(service.pool.descriptor["block_count"], 8)
                self.assertEqual(service.worker.config["point_cloud_save_format"], "npy")
                self.assertEqual(path.read_bytes(), before)
            finally:
                service.abort()

    def test_new_service_rereads_changed_file_instead_of_cached_ui_values(self):
        self.assertTrue(hasattr(PointCloudSaveService, "from_config_file"))
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "ReadDataConfig.toml"
            for count in (4, 8):
                path.write_bytes(f'point_cloud_save_block_mb = 0.01\npoint_cloud_save_block_count = {count}\n'.encode())
                service = PointCloudSaveService.from_config_file(path, directory)
                try:
                    self.assertEqual(service.pool.descriptor["block_count"], count)
                finally:
                    service.abort()

    def test_invalid_file_is_not_rewritten_and_does_not_allocate_pool(self):
        self.assertTrue(hasattr(PointCloudSaveService, "from_config_file"))
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "ReadDataConfig.toml"
            original = b'point_cloud_save_block_count = 32\npoint_cloud_save_block_count = 64\n'
            path.write_bytes(original)
            with patch("acquisition_sdk._internal.pointcloud.PointCloudSaveService.SharedPointCloudPool.create") as create:
                with self.assertRaises(ValueError):
                    PointCloudSaveService.from_config_file(path, directory)
                create.assert_not_called()
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
