"""按 Z 窗口统计 Y 持续性；仅识别横梁，不计算任何轴运动。"""

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypedDict

from acquisition_sdk._internal.formats.frame_by_frame.AxisFrameDataFormat import AxisFrameData


BeamType = Literal["upper", "lower"]
BeamBounds = tuple[int, int]


class BeamResult(TypedDict):
    found: bool
    beam_type: BeamType
    y_bottom: int | None
    y_top: int | None


class BeamDetector:
    """共用横梁检测器：内外顶取上梁，内外底取下梁；参数由调用者传入。"""

    def __init__(self, process_config: Mapping[str, Any]):
        self.y_threshold = int(process_config.get("y_threshold", 10))
        self.z_threshold = int(process_config.get("z_threshold", 10))
        self.beams_threshold = float(process_config.get("beams_threshold", 0.7))
        self.merge_beams = int(process_config.get("merge_beams", 300))
        self.beams_width = int(process_config.get("beams_width", 200))
        self.min_valid_frames = int(process_config.get("beams_min_valid_frames", 5))
        if self.y_threshold <= 0 or self.z_threshold <= 0:
            raise ValueError("横梁检测的 y_threshold、z_threshold 必须大于 0")
        if not math.isfinite(self.beams_threshold) or not 0 < self.beams_threshold <= 1:
            raise ValueError("beams_threshold 必须大于 0 且不超过 1")
        if self.merge_beams < 0 or self.beams_width < 0 or self.min_valid_frames < 1:
            raise ValueError("merge_beams、beams_width 不能为负，beams_min_valid_frames 必须至少为 1")

    def find_for_machine(self, machine_cfg: Mapping[str, Any], frame_stack: Mapping[str, Sequence[AxisFrameData | None]],
                         runtime_cfg: Mapping[str, Any] | None = None) -> BeamResult:
        """按设备方向和搜索偏移检测；返回绝对 Y 层边界，不添加定位偏移。"""
        machine_type = machine_cfg.get("type")
        if machine_type not in ("inout_up", "inout_down"):
            raise ValueError("横梁检测仅支持 inout_up 和 inout_down")
        beam_type: BeamType = "upper" if machine_type == "inout_up" else "lower"
        side = str(machine_cfg.get("install_orietation", "left"))
        if side not in ("left", "right"):
            raise ValueError("横梁检测安装方向必须为 left 或 right")
        runtime_cfg = runtime_cfg or {}
        front = int(runtime_cfg.get("search_front_z_offset", machine_cfg.get("search_front_z_offset", 0)))
        after = int(runtime_cfg.get("search_after_z_offset", machine_cfg.get("search_after_z_offset", 0)))
        center = int(machine_cfg["z_position"])
        return self.find_for_side(side, center, front, after, frame_stack, beam_type)

    def find_for_side(self, side: str, z_position: int, front_offset: int, after_offset: int,
                      frame_stack: Mapping[str, Sequence[AxisFrameData | None]], beam_type: BeamType = "upper") -> BeamResult:
        """供设备规划器显式传入方向、Z 定位及前后搜索偏移，接口不依赖运动类型。"""
        if side not in ("left", "right") or beam_type not in ("upper", "lower"):
            raise ValueError("横梁方向或类型无效")
        if front_offset < 0 or after_offset < 0:
            raise ValueError("横梁搜索前后 Z 偏移不能为负")
        bounds = self.find_beams(frame_stack.get(side, ()), z_position - front_offset, z_position + after_offset)[beam_type]
        return {"found": bounds is not None, "beam_type": beam_type, "y_bottom": bounds[0] if bounds else None, "y_top": bounds[1] if bounds else None}

    def find_beams(self, frames: Sequence[AxisFrameData | None], z_start: int, z_end: int) -> dict[BeamType, BeamBounds | None]:
        """窗口两端包含在内；只用正 Y 非空帧作为比例分母，空窗不回退到边缘帧。"""
        empty: dict[BeamType, BeamBounds | None] = {"upper": None, "lower": None}
        start = max(0, math.ceil(z_start / self.z_threshold))
        end = min(len(frames) - 1, math.floor(z_end / self.z_threshold))
        y_counts: Counter[int] = Counter()
        valid_count = 0
        for index in range(start, end + 1):
            frame = frames[index]
            rows = frame.FrameData if frame is not None else None
            ys = {int(row.H_Axis) for row in rows or () if row.H_Axis is not None and row.H_Axis > 0}
            if ys:
                valid_count += 1
                y_counts.update(ys)
        if valid_count < self.min_valid_frames:
            return empty
        threshold = valid_count * self.beams_threshold
        beam_ys = sorted(y for y, count in y_counts.items() if count >= threshold)
        if not beam_ys:
            return empty
        y_center = (min(y_counts) + max(y_counts)) / 2
        segments = self._merge_segments(beam_ys)
        if len(segments) == 1:
            bottom, top = segments[0]
            if top - bottom <= self.beams_width:
                kind: BeamType = "upper" if (bottom + top) / 2 > y_center else "lower"
                empty[kind] = (bottom, top)
            return empty
        lower, upper = segments[0], segments[-1]
        return {"lower": lower if lower[1] - lower[0] <= self.beams_width else None, "upper": upper if upper[1] - upper[0] <= self.beams_width else None}

    def _merge_segments(self, beam_ys: list[int]) -> list[BeamBounds]:
        """先合并连续 Y 层，再以严格小于 merge_beams 的间距合并区间。"""
        segments: list[BeamBounds] = []
        start = previous = beam_ys[0]
        for y in beam_ys[1:]:
            if y != previous + self.y_threshold:
                segments.append((start, previous))
                start = y
            previous = y
        segments.append((start, previous))
        merged = [segments[0]]
        for bottom, top in segments[1:]:
            if bottom - merged[-1][1] < self.merge_beams:
                merged[-1] = (merged[-1][0], top)
            else:
                merged.append((bottom, top))
        return merged
