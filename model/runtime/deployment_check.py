"""Read-only deployment preflight; never constructs the hardware runtime."""

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
import sys

from model.runtime.app_bootstrap import application_directory


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def check_configurations(root: Path) -> tuple[CheckResult, ...]:
    results = []
    for name in (
        "ModeConfig.toml", "ReadDataConfig.toml", "SystemConfig.toml", "PlcConfig.toml",
        "SprayConfig.toml", "ProcessConfig.toml", "LidarConfig.toml",
        "MachineConfig1.toml", "MachineConfig2.toml", "MachineConfig3.toml",
    ):
        try:
            from model.utils.TomlLoader import TomlLoader
            config = TomlLoader.load(str(root / "model" / "tomls" / name))
            if name == "ModeConfig.toml":
                from model.utils.StrategyUtil import strategy_name_from_code
                strategy_name_from_code(config.get("strategy_name"))
        except (ImportError, OSError, ValueError) as exc:
            results.append(CheckResult(name, False, str(exc)))
        else:
            results.append(CheckResult(name, True, "配置可解析"))
    return tuple(results)


def check_windows_plugin(plugin_directory: Path) -> CheckResult:
    path = plugin_directory / "platforms" / "qwindows.dll"
    return CheckResult("Qt Windows 平台插件", path.is_file(), str(path))


def run_checks(root: Path) -> tuple[CheckResult, ...]:
    results = list(check_configurations(root))
    # Import native libraries to catch missing Python modules and DLL loaders.
    # No QApplication, controller, socket, or multiprocessing worker is created.
    for module in (
        "PyQt6.QtCore", "PyQt6.QtWidgets", "PyQt6.QtOpenGLWidgets",
        "OpenGL.GL", "numpy", "scipy", "open3d", "tomlkit",
    ):
        try:
            import_module(module)
        except Exception as exc:
            results.append(CheckResult(module, False, str(exc)))
        else:
            results.append(CheckResult(module, True, "模块导入成功"))
    try:
        from PyQt6.QtCore import QLibraryInfo
        plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
        result = check_windows_plugin(plugins) if sys.platform == "win32" else CheckResult(
            "Qt Windows 平台插件", False, "此部署检查面向 Windows")
    except Exception as exc:
        result = CheckResult("Qt Windows 平台插件", False, str(exc))
    results.append(result)
    return tuple(results)


def main() -> int:
    root = application_directory()
    print(f"只读部署自检：{root}")
    results = run_checks(root)
    for result in results:
        print(f"[{'OK' if result.ok else 'FAIL'}] {result.name}: {result.detail}")
    failures = sum(not result.ok for result in results)
    print(f"检查 {len(results)} 项，失败 {failures} 项。未启动界面或设备进程。")
    print("此检查不代替平台插件加载、OpenGL 渲染、设备联调或可执行文件验收。")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
