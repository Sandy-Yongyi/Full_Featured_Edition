import os
import sys
import ctypes
import multiprocessing
from model.runtime.app_bootstrap import prepare_environment


# 开发调试只需修改这里，然后直接运行 main.py；交付时保持 CONTROL_TYPE = 2。
CONTROL_TYPE = 1  # 1=TXT显示并联调PLC，2=实时采数与运动，3=只导入TXT画图
DATA_PATH = r"D:\draw_points\ZJYMS"  # TXT文件或目录；仅方式1/3使用
DATA_NAME = "combined_20260620_110503.txt"  # 目录内的数据集名称，例如 "sample.txt"；None为自动查找


def qt_main():
    from model.runtime.qt_main import main as run_qt
    return run_qt(control_type=CONTROL_TYPE, data_path=DATA_PATH, data_name=DATA_NAME)


def is_already_running():
    """检查是否已有程序实例在运行"""
    mutex_name = "Global\\MainExeMutex"

    try:
        # 尝试创建互斥体
        ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        last_error = ctypes.windll.kernel32.GetLastError()

        # 如果错误码是183（已存在），则返回True
        return last_error == 183  # ERROR_ALREADY_EXISTS
    except Exception as e:
        from model.utils.LoggerUtil import logger
        logger.error(f"检查单实例出错: {str(e)}")
        return True


def disable_console_interaction():
    """安全禁用控制台交互"""
    if sys.platform == 'win32':
        kernel32 = ctypes.WinDLL('kernel32')
        STD_INPUT_HANDLE = -10

        hStdin = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        if hStdin is None or hStdin == ctypes.c_void_p(-1).value:
            return

        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(hStdin, ctypes.byref(mode)):
            ENABLE_QUICK_EDIT_MODE = 0x0040
            new_mode = mode.value & ~ENABLE_QUICK_EDIT_MODE
            kernel32.SetConsoleMode(hStdin, new_mode)


def main():
    prepare_environment()
    from model.utils.LoggerUtil import logger
    from model.utils.TomlLoader import TomlLoader

    logger.info(f"main process ID: {os.getpid()}")

    if is_already_running():
        english = TomlLoader.load(os.path.join(os.getcwd(), "model", "tomls", "ModeConfig.toml")).get("strategy_name") == 3
        ctypes.windll.user32.MessageBoxW(
            0,
            "The software is already running. Do not start another instance." if english else "程序已在运行中，请不要启动多个实例",
            "Already Running" if english else "错误提示",
            0x10  # MB_ICONERROR
        )
        logger.error("检测到已有实例运行，退出程序")
        sys.exit(1)  # 非零退出码表示异常退出

    return qt_main()


def launch() -> int:
    multiprocessing.freeze_support()
    prepare_environment()
    if sys.argv[1:] == ["--check-deployment"]:
        from model.runtime.deployment_check import main as check_deployment
        return check_deployment()
    disable_console_interaction()
    if multiprocessing.get_start_method(allow_none=True) is None:
        multiprocessing.set_start_method('spawn')
    return main()


if __name__ == "__main__":
    raise SystemExit(launch())
