import ast
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.package_sdk import generate_stub, used_sdk_exports


ROOT = Path(__file__).resolve().parents[1]


class DeveloperStubTests(unittest.TestCase):
    def test_only_upper_layer_imports_are_public(self):
        full, _ = generate_stub()
        reduced, count = generate_stub(upper_layer_only=True)
        used = used_sdk_exports(ROOT)
        names = {node.name for node in ast.parse(reduced).body
                 if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and not node.name.startswith('_')}
        self.assertEqual(used, names)
        self.assertEqual(len(used), count)
        self.assertLess(len(reduced), len(full))
        self.assertNotIn('class PointCloudSaveBuffer', reduced)
        self.assertNotIn('_internal', reduced)
        self.assertNotIn('def _read_data(', reduced)
        self.assertIn('def scan(', reduced)

    def test_required_return_types_stay_declared(self):
        reduced, _ = generate_stub(upper_layer_only=True)
        tree = ast.parse(reduced)
        definitions = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
        self.assertIn('_BasePlc', definitions)
        self.assertIn('PlcManager', definitions)
        self.assertIn('_FrameAxisData', definitions)

    def test_new_upper_import_does_not_expand_approved_api(self):
        with patch('tools.package_sdk.used_sdk_exports', return_value={'UInt16'}):
            with self.assertRaisesRegex(ValueError, 'approved'):
                generate_stub(upper_layer_only=True)

    def test_method_declarations_stay_within_frozen_contract(self):
        reduced, _ = generate_stub(upper_layer_only=True)
        contract = json.loads((ROOT / 'tools/sdk_public_api.json').read_text())
        self.assertEqual(21, len(contract['exports']))
        for node in ast.parse(reduced).body:
            if isinstance(node, ast.ClassDef):
                methods = {item.name for item in node.body if isinstance(item, ast.FunctionDef)}
                self.assertLessEqual(methods, set(contract['methods'].get(node.name, ())) | {'__init__'})


if __name__ == '__main__':
    unittest.main()
