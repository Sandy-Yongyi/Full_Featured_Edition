"""Run only the saving/compatibility suite from a real file (Windows spawn)."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


if __name__ == "__main__":
    names = ["test_point_cloud_saving", "test_lidar_save_integration", "test_save_lifecycle",
             "test_save_stress", "test_full_saving_ui", "test_save_config_loading"]
    suite = unittest.TestLoader().loadTestsFromNames(names)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
