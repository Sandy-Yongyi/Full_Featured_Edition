"""Supported SDK boundary, independent of the private source layout."""
import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SdkContractTests(unittest.TestCase):
    def test_build_inventory_rejects_extra_root_or_package_modules(self):
        from tools.build_sdk import PRIVATE_SOURCES, get_private_sources
        for extra in ('extra.py', 'extra_package/__init__.py'):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for relative in PRIVATE_SOURCES:
                    path = root / 'acquisition_sdk/_internal' / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
                    parent = path.parent
                    while parent.is_relative_to(root / 'acquisition_sdk'):
                        (parent / '__init__.py').touch()
                        parent = parent.parent
                path = root / 'acquisition_sdk' / extra
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
                with self.assertRaises(ValueError):
                    get_private_sources(root)

    def test_sdk_imports_without_runtime_side_effects(self):
        code = """
import sys, multiprocessing
import acquisition_sdk as sdk
assert (sdk.__version__, sdk.SDK_API_VERSION) == ('0.1.0', 1)
from acquisition_sdk import BlockData, AxisFrameData, PlcFrame, Int16
assert 'model.utils.LoggerUtil' not in sys.modules
assert 'open3d' not in sys.modules
assert not multiprocessing.active_children()
"""
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_open_packet_and_sdk_frame_types_are_distinct(self):
        from acquisition_sdk import PlcFrame, FrameAxisData, AxisFrameData
        from model.MovingFrameData import AxisData, SendMovingFrameData, ReceiveMovingFrameData
        self.assertTrue(issubclass(AxisData, PlcFrame))
        self.assertIsNot(AxisData, FrameAxisData)
        self.assertIsInstance(AxisFrameData([FrameAxisData(10, 20, 5)]).FrameData[0], FrameAxisData)
        self.assertEqual(134, len(SendMovingFrameData().to_bytes()))
        self.assertEqual(134, len(ReceiveMovingFrameData().to_bytes()))

    def test_open_project_code_uses_only_supported_sdk_imports(self):
        offenders = []
        for folder in ('control', 'view', 'model'):
            for path in (ROOT / folder).rglob('*.py'):
                tree = ast.parse(path.read_text(encoding='utf-8-sig'))
                for node in ast.walk(tree):
                    names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) else []
                    if any(n.startswith('acquisition_sdk._internal') for n in names):
                        offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual([], offenders)

    def test_private_inventory_has_exactly_the_confirmed_22_modules(self):
        from tools.build_sdk import get_private_sources
        sources = get_private_sources()
        self.assertEqual(22, len(sources))
        counts = {name: 0 for name in ('lidar', 'plc', 'dataprocess', 'formats', 'pointcloud')}
        for source in sources:
            counts[source.relative_to(ROOT / 'acquisition_sdk/_internal').parts[0]] += 1
            self.assertNotEqual('MovingFrameData.py', source.name)
            self.assertNotIn('GunDistributor', source.name)
        self.assertEqual(dict(lidar=4, plc=2, dataprocess=7, formats=4, pointcloud=5), counts)

    def test_no_original_private_source_directories_are_required(self):
        for name in ('lidar', 'plc', 'dataprocess', 'formats', 'pointcloud'):
            self.assertEqual([], list((ROOT / 'model' / name).rglob('*.py')), name)
        self.assertTrue((ROOT / 'model/MovingFrameData.py').is_file())
        self.assertTrue((ROOT / 'model/gun_distributors/GunDistributor.py').is_file())
        self.assertFalse((ROOT / 'model/utils/FrameQueueManager.py').exists())
        self.assertFalse((ROOT / 'model/utils/PointsFileUtil.py').exists())

    def test_three_acquisition_strategies_remain_registered(self):
        from acquisition_sdk._internal.lidar.LidarAcquisitionStrategies import AcquisitionStrategyFactory
        from model.utils.StrategyUtil import STRATEGY_CODE_MAP
        self.assertEqual({1: 'frame_by_frame', 2: 'complete_workpiece', 3: 'continuous_bidirectional'}, STRATEGY_CODE_MAP)
        self.assertEqual({'frame_by_frame', 'complete_workpiece', 'continuous_bidirectional'}, set(AcquisitionStrategyFactory.STRATEGIES))


if __name__ == '__main__':
    unittest.main()
