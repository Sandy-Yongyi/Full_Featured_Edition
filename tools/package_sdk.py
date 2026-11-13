"""Create a source-free, versioned SDK/application distribution and stubs."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def _instance_attributes(node):
    attributes = {}
    for method in node.body:
        if isinstance(method, ast.FunctionDef) and method.name == '__init__':
            for assignment in ast.walk(method):
                targets = assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target] if isinstance(assignment, ast.AnnAssign) else []
                for target in targets:
                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
                        attributes[target.attr] = assignment.annotation if isinstance(assignment, ast.AnnAssign) else ast.Name('Any', ast.Load())
    return attributes


def used_sdk_exports(root):
    used = set()
    paths = [root / 'main.py']
    for folder in ('control', 'view', 'model'):
        paths.extend((root / folder).rglob('*.py'))
    for path in paths:
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        module_aliases = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'acquisition_sdk':
                if any(alias.name == '*' for alias in node.names):
                    raise ValueError(f'Explicit SDK imports required: {path}')
                used.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                module_aliases.update(alias.asname or alias.name for alias in node.names if alias.name == 'acquisition_sdk')
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in module_aliases:
                used.add(node.attr)
    return used - {'__version__', 'SDK_API_VERSION'}


def _approved_stub(text, exports):
    used = used_sdk_exports(ROOT)
    if not used <= exports.keys():
        raise ValueError(f'Unknown SDK imports: {used - exports.keys()}')
    contract = json.loads((ROOT / 'tools/sdk_public_api.json').read_text(encoding='utf-8'))
    if not used <= set(contract['exports']):
        raise ValueError(f'SDK imports outside approved delivery API: {sorted(used - set(contract["exports"]))}')
    return _reduce_stub(text, used, contract['methods']), len(used)


def _reduce_stub(text, used, approved_methods):
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            declared_name = node.name if node.name in used or node.name.startswith('_') else '_' + node.name
            members = approved_methods.get(declared_name, ())
            node.body = [item for item in node.body if not isinstance(item, ast.FunctionDef)
                         or item.name == '__init__' or item.name in members] or [ast.Expr(ast.Constant(Ellipsis))]
    declarations = {node.name: node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    required = set(used)
    while True:
        references = {node.id for name in required for node in ast.walk(declarations[name]) if isinstance(node, ast.Name)}
        expanded = required | (references & declarations.keys())
        if expanded == required:
            break
        required = expanded
    renamed = {name: '_' + name for name in required - used if not name.startswith('_')}

    class Rename(ast.NodeTransformer):
        def visit_Name(self, node):
            node.id = renamed.get(node.id, node.id)
            return node

        def visit_ClassDef(self, node):
            node.name = renamed.get(node.name, node.name)
            return self.generic_visit(node)

    tree.body = [node for node in tree.body if not isinstance(node, (ast.ClassDef, ast.FunctionDef)) or node.name in required]
    tree = Rename().visit(tree)
    return ast.unparse(ast.fix_missing_locations(tree)) + '\n'


def generate_stub(upper_layer_only=False):
    exports = runpy.run_path(str(ROOT / 'acquisition_sdk/__init__.py'))['_EXPORTS']
    declarations = dict(exports)
    declarations['_BasePlc'] = ('acquisition_sdk._internal.plc.PlcCommon', 'BasePlc')
    chunks = ['from typing import *', 'from dataclasses import dataclass, field', 'from abc import ABC, abstractmethod',
              'import multiprocessing', 'import socket', 'import numpy as np', 'from pathlib import Path',
              'from model.MovingFrameData import AxisData as PlcAxisData',
              '__version__: str', 'SDK_API_VERSION: int', '_BeamType = Literal["upper", "lower"]', '_BeamBounds = tuple[int, int]']

    class Stub(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id == 'AxisData':
                node.id = 'FrameAxisData'
            elif node.id in ('BasePlc', 'BeamType', 'BeamBounds'):
                node.id = '_' + node.id
            return node

        def visit_FunctionDef(self, node):
            node.body = [ast.Expr(ast.Constant(Ellipsis))]
            for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                if arg.arg not in ('self', 'cls') and arg.annotation is None:
                    arg.annotation = ast.Name('Any', ast.Load())
            if node.returns is None and node.name == '__init__':
                node.returns = ast.Constant(None)
            elif node.returns is None:
                node.returns = ast.Name('Any', ast.Load())
            return self.generic_visit(node)

        def visit_ClassDef(self, node):
            body = []
            attributes = _instance_attributes(node)
            body.extend(ast.AnnAssign(ast.Name(name, ast.Store()), annotation, None, 1) for name, annotation in attributes.items())
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AnnAssign)):
                    body.append(item)
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            body.append(ast.AnnAssign(target, ast.Name('Any', ast.Load()), ast.Constant(Ellipsis), 1))
            node.body = body or [ast.Expr(ast.Constant(Ellipsis))]
            return self.generic_visit(node)
    for public, (module, original) in declarations.items():
        path = ROOT.joinpath(*module.split('.')).with_suffix('.py')
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        node = next(n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name == original)
        if isinstance(node, ast.ClassDef):
            node.name = public
        elif isinstance(node, ast.FunctionDef):
            node.name = public
        rendered = ast.unparse(ast.fix_missing_locations(Stub().visit(node)))
        chunks.append(rendered)
    text = '\n\n'.join(chunks) + '\n'
    parsed = ast.parse(text)
    names = {n.name for n in parsed.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))}
    assert set(exports) <= names
    assert {name for name in names if not name.startswith('_')} == set(exports)
    assert '_internal' not in text
    if upper_layer_only:
        return _approved_stub(text, exports)
    return text, len(exports)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--developer', action='store_true', default=True, help='Include standalone Chinese developer README (default)')
    parser.add_argument('--minimal-stub', action='store_true', default=True, help='Use approved minimal delivery API (default)')
    parser.add_argument('--release-root', type=Path, default=ROOT / 'output/releases')
    parser.add_argument('--binary', type=Path, default=ROOT / 'output/sdk-full/acquisition_sdk.cp311-win_amd64.pyd')
    args = parser.parse_args()
    version = runpy.run_path(str(ROOT / 'acquisition_sdk/__init__.py'))['__version__']
    binary = args.binary.resolve()
    output = args.release_root.resolve()
    target = output / ('acquisition_sdk-' + version + ('-developer' if args.developer else '')
                       + ('-minimal' if args.minimal_stub else '') + '-cp311-win_amd64')
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise RuntimeError('Release directory already populated; do not overwrite an existing release')
    stub, count = generate_stub(upper_layer_only=args.minimal_stub)
    (target / 'acquisition_sdk.pyi').write_text(stub, encoding='utf-8')
    shutil.copyfile(binary, target / binary.name)
    files = [ROOT / 'main.py', ROOT / 'requirements.txt']
    for directory in ('model', 'control', 'view'):
        files.extend(p for p in (ROOT / directory).rglob('*') if p.is_file() and p.suffix in ('.py', '.toml') and '__pycache__' not in p.parts)
    for source in files:
        copied = target / source.relative_to(ROOT)
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, copied)
    if args.developer:
        shutil.copyfile(ROOT / 'README_DEVELOPER.md', target / 'README.md')
    else:
        (target / 'SDK_USAGE.md').write_text('''# Acquisition SDK 0.1.0

Requires Windows x64, CPython 3.11 and the Python/native dependencies in requirements.txt.
Dependencies are not bundled. The tested environment uses NumPy2.1.3, Open3D0.19.0,
SciPy1.14.1, PyQt6 6.11.0 and tomlkit0.13.3; the requirements version ranges are not fully certified.

Run python main.py, or import acquisition_sdk from your upper-level Python code.
Keep model/utils, model/MovingFrameData.py, model/gun_distributors and model/tomls.
The five original private directories and SDK private source are not required.
Edit open project code and restart; rebuild only when private SDK implementation changes.

Stop the app and all workers before updating. Back up the old binary, stub and project files.
Replace matching binary/stub files; preserve your customized open code and field configuration.
Roll back the matching binary/stub together. No hot replacement or cross-version pickle migration.

Known acceptance limits: five existing third-strategy planning assertions and one old
configuration-field test remain unresolved. This package has not passed hardware acceptance.
The .pyi preserves source declarations; originally untyped algorithm parameters remain Any.
''', encoding='utf-8')
    manifest = {p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(target.rglob('*')) if p.is_file()}
    excluded_prefixes = ('docs/', 'tools/', 'tests/', 'output/', 'acquisition_sdk/')
    assert not any('_internal' in name or name.startswith(excluded_prefixes) or name.endswith(('.pyc', '.c', '.pdb')) for name in manifest)
    runtime_exports = len(runpy.run_path(str(ROOT / 'acquisition_sdk/__init__.py'))['_EXPORTS'])
    metadata = {'version': version, 'python': 'cp311', 'platform': 'win_amd64',
                'exports': runtime_exports, 'stub_exports': count, 'files': manifest}
    internal_manifest = output / (target.name + '.manifest.json')
    internal_manifest.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    archive = output / (target.name + '.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in target.rglob('*'):
            if path.is_file():
                bundle.write(path, path.relative_to(target))
    print(json.dumps({'directory': str(target), 'archive': str(archive), 'files': len(manifest),
                      'exports': runtime_exports, 'stub_exports': count}))


if __name__ == '__main__':
    main()
