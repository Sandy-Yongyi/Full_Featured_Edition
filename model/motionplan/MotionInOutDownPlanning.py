"""内外底当前仅查找下梁并维持原有安全回位；喷涂轨迹后续单独实现。"""


class MotionInOutDownPlanning:
    def __init__(self, beam_detector, motion_to_target):
        self.beam_detector = beam_detector
        self.motion_to_target = motion_to_target

    def auto_inout_down_move(self, machine_cfg, runtime_cfg, plc_data, frame_queue_manager):
        # 下梁检测保留在设备规划内部，后续内外底轨迹直接消费该结果。
        self.beam_detector.find_for_machine(machine_cfg, frame_queue_manager.frame_stack, runtime_cfg)
        commands, ready = self.motion_to_target.move_to_origin_safe(machine_cfg, runtime_cfg, plc_data)
        return commands, ready
