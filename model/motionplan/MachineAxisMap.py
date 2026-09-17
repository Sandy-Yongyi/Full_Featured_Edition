"""
设备轴索引映射配置模块。

按设备 type 和 install_orietation 查找本项目收发共用的 PLC AxisList 索引。
轴按报文排列，不按设备连续排列；以下均为从0开始的索引：

    0 左侧面Z，1 右侧面Z
    2 左二维Y，3 左二维X，4 右二维Y，5 右二维X
    6 左侧面Y2，7 左侧面X2，8 左侧面R2
    9 右侧面Y2，10 右侧面X2，11 右侧面R2
    12 左侧面Y1，13 左侧面X1，14 左侧面R1
    15 右侧面Y1，16 右侧面X1，17 右侧面R1
    18 激光201，19 激光202，20 激光203，21 激光204

轴名称统一使用 x/x1/x2，索引查询和指令写入使用相同名称。
映射不决定设备SN、轴限位或运动策略，配置与规划需单独按本项目适配。
"""

from model.utils.LoggerUtil import logger
from model.motionplan.motionutil.AxisLimits import clamp_speed, clamp_to_limit_yx
from model.plc.MovingFrameData import AxisData


INT16_MIN = -32768
INT16_MAX = 32767


AXIS_LIMIT_KEY: dict[str, dict[str, int]] = {
    "xn_rotate": {"z": 0, "y": 1, "x": 2, "r": 3},
    "z_2d_lift": {"y": 0, "x": 1},
}

XN_UPDOWN2_MAX_LIMIT_INDEX = {
    "y1": 0,
    "x1": 1,
    "y2": 2,
    "x2": 3,
}


def get_axis_config_index(machine_type: str, axis_name: str) -> int | None:
    """获取轴在 max_limit_speed / min_limit_pos / max_limit_pos 中的索引。"""
    limit_key = AXIS_LIMIT_KEY.get(machine_type, {})
    if axis_name.startswith("x"):
        lookup = "x"
    elif axis_name.startswith("y"):
        lookup = "y"
    elif axis_name.startswith("r"):
        lookup = "r"
    else:
        lookup = axis_name
    return limit_key.get(lookup)


def get_axis_config_value(machine_cfg: dict, axis_name: str, config_key: str, default: int = 0) -> int:
    """按设备通用轴定义读取配置值，如 safe_pos / max_limit_speed / min_limit_pos / max_limit_pos。"""
    machine_type = machine_cfg.get("type", "")
    values = machine_cfg.get(config_key, [])
    idx = get_axis_config_index(machine_type, axis_name)
    if machine_type == "xn_updown2" and config_key == "max_limit_pos" and isinstance(values, (list, tuple)) and len(values) >= 4:
        # 顶底两组只对最大位置限位使用独立四轴配置；两元素旧配置仍走通用 Y/X 索引。
        idx = XN_UPDOWN2_MAX_LIMIT_INDEX.get(axis_name, idx)
    if idx is not None and isinstance(values, (list, tuple)) and idx < len(values):
        return int(values[idx] or 0)
    return default


def get_axis_speed_limit(machine_cfg: dict, axis_name: str, default: int = 300) -> int:
    """获取设备指定轴的最大速度。"""
    return get_axis_config_value(machine_cfg, axis_name, "max_limit_speed", default)


def get_axis_position_limits(machine_cfg: dict, axis_name: str, default_min: int = 0, default_max: int = 1000) -> tuple[int, int]:
    """获取设备指定轴的位置最小/最大限位。"""
    min_limit = get_axis_config_value(machine_cfg, axis_name, "min_limit_pos", default_min)
    max_limit = get_axis_config_value(machine_cfg, axis_name, "max_limit_pos", default_max)
    return min_limit, max_limit


def get_axis_safe_pos(machine_cfg: dict, axis_name: str, default: int = 0) -> int:
    """获取设备指定轴的安全位置。"""
    return get_axis_config_value(machine_cfg, axis_name, "safe_pos", default)


MACHINE_AXIS_MAP = {
    # 第三模式：同侧两台设备共用Z，但仅xn_rotate拥有Z指令写入权。
    "xn_rotate": {
        "left": dict(z=0, y1=12, x1=13, r1=14, y2=6, x2=7, r2=8),
        "right": dict(z=1, y1=15, x1=16, r1=17, y2=9, x2=10, r2=11),
    },
    "z_2d_lift": {
        "left": dict(y=2, x=3),
        "right": dict(y=4, x=5),
    },
}


LIDAR_AXIS_MAP = {"201": 18, "202": 19, "203": 20, "204": 21}


def get_lidar_axis_index(lidar_id: str | int) -> int:
    """获取激光运动轴在收发 AxisList 中的索引。"""
    lidar_key = str(lidar_id)
    if lidar_key not in LIDAR_AXIS_MAP:
        raise ValueError(f"未知激光轴: {lidar_id}, 可用编号: {list(LIDAR_AXIS_MAP)}")
    return LIDAR_AXIS_MAP[lidar_key]


def get_axis_map(machine_type: str, orientation: str) -> dict:
    """获取指定设备类型和安装方向的完整轴映射字典。"""
    if machine_type not in MACHINE_AXIS_MAP:
        raise ValueError(f"未知设备类型: {machine_type}, 可用类型: {list(MACHINE_AXIS_MAP.keys())}")
    type_map = MACHINE_AXIS_MAP[machine_type]
    if orientation not in type_map:
        raise ValueError(f"设备 '{machine_type}' 不支持方向 '{orientation}', 可用方向: {list(type_map.keys())}")
    return type_map[orientation]


def get_axis_index(machine_type: str, orientation: str, axis_name: str) -> int:
    """获取指定设备某个轴在 PLC AxisList 中的索引。"""
    axis_map = get_axis_map(machine_type, orientation)
    if axis_name not in axis_map:
        raise ValueError(f"轴 '{axis_name}' 不存在于 {machine_type}/{orientation}, 可用轴: {list(axis_map.keys())}")
    return axis_map[axis_name]


def get_x_axes(machine_type: str, orientation: str) -> dict:
    """获取所有 X 类轴的名称到 PLC 索引映射。"""
    axis_map = get_axis_map(machine_type, orientation)
    return {k: v for k, v in axis_map.items() if k.startswith("x")}


def has_axis(machine_type: str, orientation: str, axis_name: str) -> bool:
    """判断指定设备是否拥有某个轴。"""
    axis_map = get_axis_map(machine_type, orientation)
    return axis_name in axis_map


def get_all_axis_indices(machine_type: str, orientation: str) -> list:
    """获取指定设备所有轴的 PLC 索引列表。"""
    return list(get_axis_map(machine_type, orientation).values())


def _limit_axis_command(machine_cfg: dict, axis_name: str, axis_data: AxisData) -> AxisData:
    """在写入 PLC 报文前统一限制单轴位置和速度。"""
    machine_type = machine_cfg.get("type", "")
    if machine_type == "out_2d_servo" and axis_name == "y":
        pos = int(axis_data.Pos)
        speed = int(axis_data.Speed)
        if not (INT16_MIN <= pos <= INT16_MAX and INT16_MIN <= speed <= INT16_MAX):
            sn = machine_cfg.get("sn", "?")
            logger.error(
                f"SN[{sn}] out_2d_servo Y点云载荷超出Int16，当前轴发送零值: "
                f"Pos={pos}, Speed={speed}"
            )
            return AxisData()
        return AxisData(Pos=pos, Speed=speed, Status=0)

    min_position, max_position = get_axis_position_limits(machine_cfg, axis_name)
    if min_position > max_position:
        raise ValueError(f"轴 {axis_name} 的位置限位无效: {min_position} > {max_position}")
    max_speed = get_axis_speed_limit(machine_cfg, axis_name)
    status = 0 if machine_type in ("xn_rotate", "z_2d_lift") else int(axis_data.Status)
    return AxisData(Pos=clamp_to_limit_yx(int(axis_data.Pos), min_position, max_position), Speed=clamp_speed(int(axis_data.Speed), max_speed), Status=status)


def apply_to_axis_list(machine_data: dict, machine_cfg: dict, axis_list: list):
    """将设备运动指令字典应用到 PLC AxisList 中。"""
    machine_type = machine_cfg.get("type", "")
    orientation = machine_cfg.get("install_orietation", "left")
    axis_map = get_axis_map(machine_type, orientation)
    for axis_name, axis_data in machine_data.items():
        if axis_name in axis_map:
            idx = axis_map[axis_name]
            axis_list[idx] = _limit_axis_command(machine_cfg, axis_name, axis_data)
        elif axis_name == "y":
            for mapped_axis, idx in axis_map.items():
                if mapped_axis.startswith("y"):
                    axis_list[idx] = _limit_axis_command(machine_cfg, mapped_axis, axis_data)


def apply_device_axes_to_list(machine_config: dict, sn: int, axis_cmds: dict, axis_list: list):
    """按设备配置将单台设备的轴运动指令写入 AxisList。"""
    machine_cfg = machine_config.get(str(sn))
    if not machine_cfg:
        return

    try:
        apply_to_axis_list(axis_cmds, machine_cfg, axis_list)
    except Exception as e:
        logger.error(f"将 SN[{sn}] 的轴数据应用到 AxisList 时出错: {e}")
