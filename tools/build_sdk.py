"""Build the single private SDK without compiling the open application code."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_SOURCES = (
    "lidar/LidarAcquisitionProcess.py", "lidar/LidarAcquisitionStrategies.py", "lidar/LidarCommon.py", "lidar/LidarDirectionState.py",
    "plc/PlcCommon.py", "plc/PlcFrame.py",
    "dataprocess/DataFilter.py", "dataprocess/DataSplitting.py", "dataprocess/complete_workpiece/DataFindBlocks.py",
    "dataprocess/complete_workpiece/DataPartitionAuto.py", "dataprocess/complete_workpiece/DataPartitionStatic.py",
    "dataprocess/frame_by_frame/BeamDetector.py", "dataprocess/frame_by_frame/BuildSideFrame.py",
    "formats/FrameQueueManager.py", "formats/frame_by_frame/AxisFrameDataFormat.py",
    "formats/complete_workpiece/BlockDataFormat.py", "formats/complete_workpiece/FrameDataFormat.py",
    "pointcloud/PointCloudFileProcess.py", "pointcloud/PointCloudSaveBuffer.py", "pointcloud/PointCloudSaveProcess.py",
    "pointcloud/PointCloudSaveService.py", "pointcloud/PointsFileUtil.py",
)


def get_private_sources(root=ROOT):
    directory = Path(root).resolve() / "acquisition_sdk/_internal"
    expected = {directory / name for name in PRIVATE_SOURCES}
    actual = {path for path in directory.rglob("*.py") if path.name != "__init__.py"}
    if actual != expected:
        raise ValueError(f"SDK source inventory mismatch: missing={sorted(map(str, expected - actual))}, extra={sorted(map(str, actual - expected))}")
    package = directory.parent
    allowed = set(expected)
    for path in expected:
        parent = path.parent
        while parent.is_relative_to(package):
            allowed.add(parent / "__init__.py")
            parent = parent.parent
    actual_package = set(package.rglob("*.py"))
    if actual_package != allowed:
        raise ValueError(f"SDK package inventory mismatch: missing={sorted(map(str, allowed - actual_package))}, extra={sorted(map(str, actual_package - allowed))}")
    return sorted(expected)


def expected_module_names(root=ROOT):
    get_private_sources(root)
    names = set()
    for path in (Path(root) / "acquisition_sdk").rglob("*.py"):
        parts = path.relative_to(root).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        names.add(".".join(parts))
    return names


def check_compilation_report(report_path, root=ROOT):
    modules = [node.attrib for node in ET.parse(report_path).iter("module")]
    if {module["name"] for module in modules} != expected_module_names(root):
        raise ValueError("Compilation report does not contain exactly the SDK modules")
    if any(module["kind"] not in ("CompiledPythonModule", "CompiledPythonPackage") for module in modules):
        raise ValueError("Unexpected module entity in SDK compilation report")
    return modules


def developer_environment():
    environment = {name.upper(): value for name, value in os.environ.items()}
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    result = subprocess.run([str(installer), "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                             "-property", "installationPath"], capture_output=True, text=True, check=True)
    installation = result.stdout.strip()
    if not installation:
        raise RuntimeError("No installed Visual Studio x64 C++ toolchain found")
    script = Path(installation) / "VC/Auxiliary/Build/vcvars64.bat"
    setup = subprocess.run('cmd.exe /d /s /c ""' + str(script) + '" >nul && set"', capture_output=True, text=True, errors="replace", check=True)
    for line in setup.stdout.splitlines():
        if "=" in line and not line.startswith("="):
            name, value = line.split("=", 1)
            environment[name.upper()] = value
    return environment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", action="store_true", help="Only validate and list the 22 private source files")
    parser.add_argument("--developer-env", action="store_true", help="Activate the existing Visual Studio x64 environment for this build only")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output/sdk-full")
    args = parser.parse_args(argv)
    sources = get_private_sources()
    if args.inventory:
        print(json.dumps([path.relative_to(ROOT).as_posix() for path in sources], indent=2))
        return 0
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-B", "-m", "nuitka", "--module", "acquisition_sdk", "--include-package=acquisition_sdk",
               "--nofollow-import-to=model", "--nofollow-import-to=control", "--nofollow-import-to=view", "--msvc=latest",
               "--jobs=2", "--disable-cache=ccache", "--output-dir=" + str(output), "--report=" + str(output / "compilation-report.xml")]
    environment = developer_environment() if args.developer_env else os.environ.copy()
    started = time.monotonic()
    with (output / "build.log").open("wb") as stream:
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
        print(json.dumps({"build_pid": process.pid, "log": str(output / "build.log")}), flush=True)
        code = process.wait()
    result = {"command": command, "exit_code": code, "seconds": round(time.monotonic() - started, 3)}
    if code == 0:
        result["compiled_modules"] = len(check_compilation_report(output / "compilation-report.xml"))
    (output / "build-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
