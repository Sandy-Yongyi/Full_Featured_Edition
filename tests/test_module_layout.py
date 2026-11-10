"""Ensure public control code and private packages keep their agreed locations."""

import importlib
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ModuleLayoutTests(unittest.TestCase):
    def test_root_only_has_main_python_entry(self):
        self.assertEqual(['main.py'], sorted(p.name for p in ROOT.glob('*.py')))
        self.assertEqual(
            ['ControlCenter.py', 'DataProcessWorker.py', 'DataProcessingProcess.py', 'PipelineRuntime.py', 'PlcCommunicationProcess.py', '__init__.py'],
            sorted(p.name for p in (ROOT / 'control').glob('*.py')))

    def test_moved_process_types_import_from_canonical_modules(self):
        for module, name in (
            ('model.lidar.LidarAcquisitionProcess', 'LidarAcquisitionProcess'),
            ('model.pointcloud.PointCloudFileProcess', 'PointCloudFileProcess'),
            ('model.pointcloud.PointCloudSaveProcess', 'PointCloudSaveProcess'),
            ('control.PipelineRuntime', 'PipelineRuntime'),
        ):
            self.assertEqual(module, getattr(importlib.import_module(module), name).__module__)

    def test_build_manifest_only_compiles_five_private_packages(self):
        from model.build_extensions import PRIVATE_PACKAGES, get_extensions
        extensions = get_extensions()
        self.assertTrue(extensions)
        for extension in extensions:
            self.assertIn(extension.name.split('.')[1], PRIVATE_PACKAGES)
            for source in extension.sources:
                self.assertTrue((ROOT / source).is_file(), source)
        self.assertFalse((ROOT / 'model' / 'plot').exists())

    def test_source_environment_root_is_project_root(self):
        from model.runtime.app_bootstrap import application_directory
        self.assertEqual(ROOT, application_directory())
