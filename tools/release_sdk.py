"""One-command approved developer delivery: build, package and offline verify."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]

PROBE = '''import multiprocessing as mp
from pathlib import Path
import os, sys
root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
os.chdir(root)
def worker(queue):
    import acquisition_sdk as sdk
    queue.put(sdk.BlockData(lidar_status=3))
if __name__ == '__main__':
    import acquisition_sdk as sdk
    assert sdk.__compiled__.module
    for name in sdk.__all__: getattr(sdk, name)
    from model.MovingFrameData import SendMovingFrameData
    assert len(SendMovingFrameData().to_bytes()) == 134
    ctx = mp.get_context('spawn'); queue = ctx.Queue()
    child = ctx.Process(target=worker, args=(queue,))
    try:
        child.start()
        assert queue.get(timeout=20).lidar_status == 3
        child.join(10)
        assert child.exitcode == 0
    finally:
        if child.is_alive(): child.terminate(); child.join(5)
        queue.close(); queue.join_thread()
    print('Compiled SDK exports, public packet and spawn: OK')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reuse-binary', action='store_true', help='Explicitly reuse output/sdk-full binary; do not use after private source changes')
    args = parser.parse_args()
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    if sys.version_info[:2] != (3, 11) or sys.platform != 'win32' or sys.maxsize <= 2 ** 32:
        raise RuntimeError('Release requires Windows x64 CPython 3.11')
    from tools.package_sdk import generate_stub
    generate_stub(upper_layer_only=True)  # Reject unapproved interfaces before compiling.
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output = ROOT / 'output/releases' / stamp
    output.mkdir(parents=True, exist_ok=False)
    binary = ROOT / 'output/sdk-full/acquisition_sdk.cp311-win_amd64.pyd'
    if not args.reuse_binary:
        build = ROOT / 'output/sdk-builds' / stamp
        subprocess.run([sys.executable, '-B', str(ROOT / 'tools/build_sdk.py'), '--developer-env', '--output-dir', str(build)], cwd=ROOT, check=True)
        binary = build / binary.name
    if not binary.is_file():
        raise FileNotFoundError(binary)
    subprocess.run([sys.executable, '-B', str(ROOT / 'tools/package_sdk.py'), '--binary', str(binary), '--release-root', str(output)], cwd=ROOT, check=True)
    version = runpy.run_path(str(ROOT / 'acquisition_sdk/__init__.py'))['__version__']
    target = output / f'acquisition_sdk-{version}-developer-minimal-cp311-win_amd64'
    archive = output / (target.name + '.zip')
    extracted = output / 'acceptance'
    extracted.mkdir()
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if not (extracted / name).resolve().is_relative_to(extracted.resolve()):
                raise ValueError('Invalid archive member')
        bundle.extractall(extracted)
    manifest = json.loads((output / (target.name + '.manifest.json')).read_text())
    for name, digest in manifest['files'].items():
        if hashlib.sha256((extracted / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Invalid file hash: {name}')
    for excluded in ('docs', 'tools', 'tests', 'output', 'acquisition_sdk'):
        if (extracted / excluded).exists():
            raise ValueError(f'Unexpected delivery directory: {excluded}')
    probe = output / 'verify_release.py'
    probe.write_text(PROBE, encoding='utf-8')
    subprocess.run([sys.executable, '-I', '-B', str(probe), str(extracted)], cwd=output, timeout=60, check=True)
    subprocess.run([sys.executable, '-B', str(extracted / 'main.py'), '--check-deployment'], cwd=output, timeout=60, check=True)
    result = {'archive': str(archive), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
              'verified_files': len(manifest['files']), 'stub_exports': manifest['stub_exports'],
              'reused_binary': args.reuse_binary, 'passed': True}
    (output / 'acceptance-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    main()
