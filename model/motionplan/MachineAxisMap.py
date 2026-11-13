"""本项目收发共用的 20 轴映射（下标从 0 开始）。

左内外顶 Y1/X1/Y2/X2=0/1/2/3；左内外底=4/5/6/7；左二维 Y/X=8/9。
右内外顶 Y1/X1/Y2/X2=10/11/12/13；右内外底=14/15/16/17；右二维 Y/X=18/19。
四轴设备的两元素限位/速度/安全位按 Y/X 共用，四元素配置按 Y1/X1/Y2/X2 读取。
"""

from model.utils.LoggerUtil import logger
from model.motionplan.motionutil.AxisLimits import clamp_speed, clamp_to_limit_yx
from model.MovingFrameData import AxisData


INT16_MIN = -32768
INT16_MAX = 32767


AXIS_LIMIT_KEY: dict[str, dict[str, int]] = {
    "H2D_XYservo": {"y": 0, "x": 1},
    "inout_up": {"y": 0, "x": 1},
    "inout_down": {"y": 0, "x": 1},
}

FOUR_AXIS_CONFIG_INDEX = {"y1": 0, "x1": 1, "y2": 2, "x2": 3}


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
    if machine_type in ("inout_up", "inout_down") and isinstance(values, (list, tuple)) and len(values) >= 4:
        # 四元素按独立轴读取；两元素按 Y/X 共用。
        idx = FOUR_AXIS_CONFIG_INDEX.get(axis_name, idx)
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
    "inout_up": {
        "left": dict(y1=0, x1=1, y2=2, x2=3),
        "right": dict(y1=10, x1=11, y2=12, x2=13),
    },
    "inout_down": {
        "left": dict(y1=4, x1=5, y2=6, x2=7),
        "right": dict(y1=14, x1=15, y2=16, x2=17),
    },
    "H2D_XYservo": {
        "left": dict(y=8, x=9),
        "right": dict(y=18, x=19),
    },
}

# 本项目的 20 个 PLC 轴均已分配给喷涂设备，无旧项目的激光运动轴。
LIDAR_AXIS_MAP: dict[str, int] = {}


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
    min_position, max_position = get_axis_position_limits(machine_cfg, axis_name)
    if min_position > max_position:
        raise ValueError(f"轴 {axis_name} 的位置限位无效: {min_position} > {max_position}")
    max_speed = get_axis_speed_limit(machine_cfg, axis_name)
    status = int(axis_data.Status)
    return AxisData(Pos=clamp_to_limit_yx(int(axis_data.Pos), min_position, max_position), Speed=clamp_speed(int(axis_data.Speed), max_speed), Status=status)


def limit_inout_y_targets(machine_cfg: dict, y1_target: int, y2_target: int) -> tuple[int, int]:
    """相对位置越界：内外顶改 Y2 等于 Y1，内外底改 Y1 等于 Y2。"""
    y1_min, y1_max = get_axis_position_limits(machine_cfg, "y1")
    y2_min, y2_max = get_axis_position_limits(machine_cfg, "y2")
    y1_min, y1_max = max(INT16_MIN, y1_min), min(INT16_MAX, y1_max)
    y2_min, y2_max = max(INT16_MIN, y2_min), min(INT16_MAX, y2_max)
    if y1_min > y1_max or y2_min > y2_max:
        raise ValueError("内外顶底 Y 轴限位无效")
    y1_limited = clamp_to_limit_yx(int(y1_target), y1_min, y1_max)
    y2_limited = clamp_to_limit_yx(int(y2_target), y2_min, y2_max)
    if machine_cfg.get("type") == "inout_down":
        y1_limited = min(y1_limited, y2_limited)
        if y1_limited < y1_min:
            raise ValueError("Y1 下限无法满足 Y1 <= Y2，禁止发送冲突轨迹")
    else:
        y2_limited = max(y1_limited, y2_limited)
        if y2_limited > y2_max:
            raise ValueError("Y2 上限无法满足 Y2 >= Y1，禁止发送冲突轨迹")
    return y1_limited, y2_limited


def enforce_inout_y_order(machine_cfg: dict, axis_cmds: dict) -> dict:
    """在设备命令写入报文前检查；复制 Y 指令，避免修改调用方持有的轴对象。"""
    if machine_cfg.get("type") not in ("inout_up", "inout_down") or "y1" not in axis_cmds or "y2" not in axis_cmds:
        return axis_cmds
    commands = dict(axis_cmds)
    y1 = _limit_axis_command(machine_cfg, "y1", axis_cmds["y1"])
    y2 = _limit_axis_command(machine_cfg, "y2", axis_cmds["y2"])
    y1.Pos, y2.Pos = limit_inout_y_targets(machine_cfg, y1.Pos, y2.Pos)
    commands.update(y1=y1, y2=y2)
    return commands


def apply_to_axis_list(machine_data: dict, machine_cfg: dict, axis_list: list):
    """将设备运动指令字典应用到 PLC AxisList 中。"""
    machine_type = machine_cfg.get("type", "")
    orientation = machine_cfg.get("install_orietation", "left")
    axis_map = get_axis_map(machine_type, orientation)
    machine_data = enforce_inout_y_order(machine_cfg, machine_data)
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
