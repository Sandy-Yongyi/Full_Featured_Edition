"""项目 PLC 报文定义；修改 ModeConfig 后重启，底层始终使用相同收发类名。"""
from dataclasses import dataclass, field
from typing import Annotated, ClassVar
from model.plc.PlcFrame import Int16, PlcFrame, Repeat


# 字节序配置: '>' = 大端序 (Big-Endian), '<' = 小端序 (Little-Endian)
_BYTE_ORDER = ">"
AXIS_LIST_COUNT = 22


@dataclass
class AxisData(PlcFrame):
    """单轴数据。"""

    BYTE_ORDER = _BYTE_ORDER
    Pos: Annotated[int, Int16()] = 0
    Speed: Annotated[int, Int16()] = 0
    Status: Annotated[int, Int16()] = 0


def create_axis_list() -> list[AxisData]:
    """按已确认 PLC 顺序创建收发共用伺服轴。"""
    return [AxisData() for _ in range(AXIS_LIST_COUNT)]


@dataclass
class SendMovingFrameData(PlcFrame):
    """发送帧数据结构。"""
    BYTE_ORDER = _BYTE_ORDER
    FRAME_SIZE: ClassVar[int] = 140
    Type: Annotated[int, Int16()] = 2
    Status: Annotated[int, Int16()] = 0     # 伺服正常、激光/手补/喷涂位可放行
    Operate: Annotated[int, Int16()] = 0    # 总使能及左侧面、左二维、右侧面、右二维开关
    HeartBeat: Annotated[int, Int16()] = 0
    AxisList: Annotated[list[AxisData], Repeat(AXIS_LIST_COUNT)] = field(default_factory=create_axis_list)


@dataclass
class ReceiveMovingFrameData(PlcFrame):
    """接收帧数据结构。"""
    BYTE_ORDER = _BYTE_ORDER
    FRAME_SIZE: ClassVar[int] = 138
    Status: Annotated[int, Int16()] = 0     # 伺服正常、三个工位到达及各工位放行完成
    Operate: Annotated[int, Int16()] = 0    # 总使能及四台设备开关
    HeartBeat: Annotated[int, Int16()] = 0
    AxisList: Annotated[list[AxisData], Repeat(AXIS_LIST_COUNT)] = field(default_factory=create_axis_list)
