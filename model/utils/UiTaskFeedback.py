"""Read the current workpiece plan for display without consuming its queue."""

from model.telemetry.UiState import GunPlanState, TaskDetailState, TaskState


STAGES = {
    "wait_front_outside": "等待工件前沿", "recip_front_outside": "外侧前喷",
    "recip_front_inside": "内侧前喷", "recip_inside_end_face": "内框端面喷涂",
    "recip_after_inside": "内侧后喷", "recip_after_outside": "外侧后喷",
    "wait_after_outside": "等待工件离开", "recip_outside": "平板往复喷涂",
    "wait_missed_cabinet_clear": "等待异常工件通过", "finish": "当前阶段完成",
}


def _frame_task_feedback(process) -> TaskState:
    fifo = getattr(getattr(process, "plc_data", None), "ChainCountCM", None)
    timeout = getattr(process, "raw_data_timeout_active", None)
    input_status = "原始数据超时" if timeout else ("未触发超时" if timeout is not None else "待反馈")
    details = [TaskDetailState("链条 FIFO", str(fifo) if fifo is not None else "待反馈"), TaskDetailState("原始数据输入", input_status),]
    stacks = getattr(getattr(process, "frame_queue_manager", None), "frame_stack", {})
    directions = {"left": "左侧", "right": "右侧", "left_upper": "左上", "right_upper": "右上"}
    for direction, stack in stacks.items():
        # These are fixed-length FIFO slots, including empty AxisFrameData.
        # Counting slots must not be presented as a count of valid workpieces.
        details.append(TaskDetailState(f"{directions.get(direction, direction)}缓存", "已建立",
                                       f"{len(stack)} 个槽位（含空帧）"))
    return TaskState(name="逐帧联动喷涂", stage="原始数据超时" if timeout else "帧队列联动", details=tuple(details))


def _continuous_task_feedback(process) -> TaskState:
    scan = getattr(process, "continuous_scan", None)
    scan_stages = {
        "startup": "扫描初始化", "homing": "扫描轴回零", "waiting": "等待扫描",
        "scanning": "往复扫描中", "complete": "本趟扫描完成", "retry_wait": "等待重采确认",
        "retry_position": "重采定位中", "fault": "扫描故障",
    }
    stage = scan_stages.get(getattr(scan, "stage", ""), "扫描阶段待反馈")
    details = [TaskDetailState("扫描状态", stage, getattr(scan, "error", ""))]
    manager = getattr(process, "frame_queue_manager", None)
    phases = getattr(manager, "continuous_phases", ())
    stacks = getattr(manager, "frame_stack", {})
    phase_names = {"empty": "空闲", "release": "请求放行", "transit": "转运中"}
    for index, name in enumerate(("激光位", "手补位", "自动位")):
        phase = phases[index] if index < len(phases) else None
        # Inspect references only: no copying, iterating, or truth-testing arrays.
        slots = [stack[index] for stack in stacks.values() if index < len(stack)]
        occupied = ("有点云数据" if any(slot is not None for slot in slots) else ("无点云数据" if slots and len(slots) == len(stacks) else "点云占用待反馈"))
        details.append(TaskDetailState(name, phase_names.get(phase or "", "待反馈"), occupied))
    return TaskState(name="往复采集与工位流转", stage=stage, details=tuple(details))


def build_task_summary(process) -> TaskState:
    """Only fields rendered by the realtime page; never traverse gun plans."""
    if process.strategy_name == "frame_by_frame":
        return TaskState(name="逐帧联动喷涂", stage="原始数据超时" if getattr(process, "raw_data_timeout_active", False) else "帧队列联动")
    if process.strategy_name == "continuous_bidirectional":
        scan = getattr(process, "continuous_scan", None)
        stages = {"startup": "扫描初始化", "homing": "扫描轴回零", "waiting": "等待扫描",
                  "scanning": "往复扫描中", "complete": "本趟扫描完成", "retry_wait": "等待重采确认",
                  "retry_position": "重采定位中", "fault": "扫描故障"}
        return TaskState(name="往复采集与工位流转", stage=stages.get(getattr(scan, "stage", ""), "扫描阶段待反馈"))
    planner = getattr(getattr(process, "complete_workpiece_planner", None), "xn_side_planner", None)
    states = getattr(planner, "_work_states", {})
    queues = getattr(getattr(process, "frame_queue_manager", None), "queues", {})
    stages = []
    for sn_key, config in process.machine_config.items():
        if config.get("type") != "xn_side":
            continue
        sn = int(sn_key)
        frames = queues.get(config.get("install_orietation"), {}).get(sn)
        stage = STAGES.get(states.get(sn, {}).get("state"), "等待工艺阶段反馈") if frames and frames[0] is not None else "等待工件"
        stages.append(f"SN {sn} · {stage}")
    return TaskState(name="完整工件喷涂", stage=" / ".join(stages) or "等待工件")


def build_task_feedback(process) -> TaskState:
    if process.strategy_name == "frame_by_frame":
        return _frame_task_feedback(process)
    if process.strategy_name == "continuous_bidirectional":
        return _continuous_task_feedback(process)
    planner = getattr(getattr(process, "complete_workpiece_planner", None), "xn_side_planner", None)
    states = getattr(planner, "_work_states", {})
    queues = getattr(getattr(process, "frame_queue_manager", None), "queues", {})
    plans = []
    stages = []
    total = 0
    for sn_key, config in process.machine_config.items():
        if config.get("type") != "xn_side":
            continue
        sn = int(sn_key)
        total += int(config.get("spray_num", 0) or 0)
        frames = queues.get(config.get("install_orietation"), {}).get(sn)
        first = frames[0] if frames else None
        block = first.get("data") if isinstance(first, dict) else first
        stage = STAGES.get(states.get(sn, {}).get("state"), "等待工艺阶段反馈") if block is not None else "等待工件"
        stages.append(f"SN {sn} · {stage}")
        for machine in getattr(block, "distribe_gun_list", None) or ():
            if machine.machine_id != sn:
                continue
            for group in machine.gun_groups or ():
                for gun in group.gundata_list or ():
                    if gun.gun_id is None:
                        continue
                    plans.append(GunPlanState(
                        machine_id=sn, gun_id=int(gun.gun_id), group=group.group_type or "",
                        group_id=group.group_id, selected=gun.gun_y_enable == 1, stage=stage,
                        y_upper=gun.gun_y_upper, y_lower=gun.gun_y_downer, angle=gun.gun_r_angle,
                    ))
    return TaskState(name="完整工件喷涂", stage=" / ".join(stages) or "等待工件", total_guns=total, gun_plans=tuple(plans))
