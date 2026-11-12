"""界面请求与规划器实际使能分开，返回途中不撤销设备使能。"""


def requested_operate(proc) -> int:
    feedback = int(proc.plc_data.Operate or 0)
    mask = int(getattr(proc, "device_enable_mask", 0)) & 0x7F
    return (feedback & ~0x7F) | (mask if mask & 1 else 0)


def final_operate(requested: int, planned: int) -> int:
    # 总使能关闭后，仍保留返回设备的电使能，直至最后一台完成安全返回。
    return (planned & ~1) | int(bool(requested & 1 or planned & 0x7E))


def validate_enable_transition(current: int, target: int, pc_auto: bool | None, all_safe: bool) -> None:
    if target & 1 and not current & 1 and pc_auto is not True:
        raise ValueError("PLC点动模式无法使能" if pc_auto is False else "等待PC自动模式反馈，无法使能")
    if current & 1 and not target & 1 and (current & 0x7E or not all_safe):
        raise ValueError("设备未全部关闭并安全回位，无法关闭使能")
