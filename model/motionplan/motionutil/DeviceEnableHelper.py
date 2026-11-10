"""界面请求与规划器实际使能分开，返回途中不撤销设备使能。"""


def requested_operate(proc) -> int:
    feedback = int(proc.plc_data.Operate or 0)
    mask = int(getattr(proc, "device_enable_mask", 0)) & 0x7F
    return (feedback & ~0x7F) | (mask if mask & 1 else 0)


def final_operate(requested: int, planned: int) -> int:
    # 总使能关闭后，仍保留返回设备的电使能，直至最后一台完成安全返回。
    return (planned & ~1) | int(bool(requested & 1 or planned & 0x7E))
