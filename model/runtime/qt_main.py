"""PyQt6 application construction and guarded standalone entry point."""

from __future__ import annotations

import sys
import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from model.runtime.app_bootstrap import prepare_environment

if TYPE_CHECKING:
    from control.ControlCenter import ControlCenter


def parse_launch_arguments(argv, *, control_type=2, data_path=None, data_name=None):
    parser = argparse.ArgumentParser(description="智能喷涂控制中心（默认实时采数）")
    parser.add_argument("--control-type", type=int, choices=(1, 2, 3), default=control_type,
                        help="开发调试：1=TXT联调PLC，2=实时采数，3=只画图")
    parser.add_argument("--data-path", help="开发调试的 TXT 文件或目录")
    parser.add_argument("--data-name", help="可选的数据集文件名/后缀，用于目录筛选")
    args = parser.parse_args(argv)
    if args.control_type == 2:
        if args.data_path or args.data_name:
            parser.error("实时采数方式不使用 --data-path/--data-name")
    else:
        args.data_path = args.data_path or data_path
        args.data_name = args.data_name if args.data_name is not None else data_name
        if not args.data_path:
            parser.error("运行方式 1/3 必须设置 main.py 的 DATA_PATH 或提供 --data-path")
    return args


def build_controller(*, control_type=2, data_path=None, data_name=None) -> ControlCenter:
    data_path = str(Path(data_path).expanduser().resolve()) if data_path else None
    prepare_environment()
    from control.ControlCenter import ControlCenter
    from control.PipelineRuntime import PipelineRuntime

    runtime = PipelineRuntime(control_type=control_type, data_path=data_path, data_name=data_name)
    return ControlCenter(
        runtime,
        strategy_name=runtime.strategy_name,
        chain_speed=runtime.chain_speed,
        save_chain_speed=runtime.save_chain_speed,
        send_control=runtime.send_control,
        async_stop=True,
    )


def main(*, control_type=2, data_path=None, data_name=None) -> int:
    args = parse_launch_arguments(sys.argv[1:], control_type=control_type, data_path=data_path, data_name=data_name)
    prepare_environment()
    from PyQt6.QtWidgets import QApplication
    from view.qt.QtUiBridge import QtUiBridge
    from view.qt.main_window import IndustrialMainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    controller = build_controller(control_type=args.control_type, data_path=args.data_path, data_name=args.data_name)
    bridge = QtUiBridge(controller)
    window = IndustrialMainWindow(controller, bridge)
    window.showMaximized()
    bridge.start()
    return app.exec()


def launch() -> int:
    from main import launch as guarded_launch
    return guarded_launch()


if __name__ == "__main__":
    raise SystemExit(launch())
