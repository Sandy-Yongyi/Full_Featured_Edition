"""项目 PLC 报文定义；修改 ModeConfig 后重启，底层始终使用相同收发类名。"""
from dataclasses import dataclass, field
from typing import Annotated, ClassVar
from acquisition_sdk import Int16, Int32, PlcFrame, Repeat


# 字节序配置: '>' = 大端序 (Big-Endian), '<' = 小端序 (Little-Endian)
_BYTE_ORDER = ">"
AXIS_LIST_COUNT = 20


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
    FRAME_SIZE: ClassVar[int] = 134
    Operate: Annotated[int, Int32()] = 0       # bit0=使能, bit1=左侧内外顶, bit2=左侧内外底, bit3=左侧二维, bit4=右侧内外顶, bit5=右侧内外底, bit6=右侧二维
    Gun_cont1: Annotated[int, Int32()] = 0     # 开枪控制1（保留）
    Gun_cont2: Annotated[int, Int16()] = 0     # 开枪控制2（保留）
    HeartBeat: Annotated[int, Int16()] = 0     # 心跳递增：最大值30000 重置0
    Control: Annotated[int, Int16()] = 0       # 远程操作位（bit1=1链条运动）bit0保留不用
    AxisList: Annotated[list[AxisData], Repeat(AXIS_LIST_COUNT)] = field(default_factory=create_axis_list)


@dataclass
class ReceiveMovingFrameData(PlcFrame):
    """接收帧数据结构。"""
    BYTE_ORDER = _BYTE_ORDER
    FRAME_SIZE: ClassVar[int] = 134
    ChainPulse: Annotated[int, Int32()] = 0     # 链条脉冲计数（最大值160000pulse）
    ChainSpeed: Annotated[int, Int32()] = 0     # 链条速度
    HeartBeat: Annotated[int, Int16()] = 0      # 心跳递增：最大值30000 重置0
    Status: Annotated[int, Int16()] = 0         # 公共状态位（bit0=1是伺服正常，bit1=1是PC自动模式，bit1=0是PLC点动模式）
    Operate: Annotated[int, Int16()] = 0        # （保留）
    AxisList: Annotated[list[AxisData], Repeat(AXIS_LIST_COUNT)] = field(default_factory=create_axis_list)

START = bytes([2, 2, 2, 2])
END = bytes([3, 3, 3, 3])
ReadCommon = b'\x02\x02\x02\x02\x01\x03\x03\x03\x03'
