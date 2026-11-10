"""Parameter labels and editable keys shared with the legacy machine editor."""

CONTINUOUS_PARAM_KEYS = {
    "xn_rotate": [
        "out_front_x_offset", "out_after_x_offset", "out_up_y_offset", "out_down_y_offset",
        "out_z_front_offset", "out_z_after_offset", "z_back_speed", "x_pos_speed", "x_recip_speed",
        "y_pos_speed", "y_recip_speed", "outside_total_cycles",
    ],
    "z_2d_lift": [
        "out_front_x_offset", "out_up_y_offset", "out_down_y_offset", "out_z_front_offset",
        "out_z_after_offset", "x_pos_speed", "x_recip_speed", "y_pos_speed", "y_recip_speed",
    ],
}

CONTINUOUS_LABELS = {
    "out_front_x_offset": "Front X offset (mm)",
    "out_after_x_offset": "Rear X offset (mm)",
    "out_up_y_offset": "Upper Y offset (mm)",
    "out_down_y_offset": "Lower Y offset (mm)",
    "out_z_front_offset": "Front Z offset (mm)",
    "out_z_after_offset": "Rear Z offset (mm)",
    "z_back_speed": "Z return spray speed (mm/s)",
    "x_pos_speed": "X positioning speed (mm/s)",
    "x_recip_speed": "X reciprocating speed (mm/s)",
    "y_pos_speed": "Y positioning speed (mm/s)",
    "y_recip_speed": "Y reciprocating speed (mm/s)",
    "outside_total_cycles": "Spray cycles",
}

PARAM_LABELS = {
    "tracking": "是否跟踪(0否/1是)",
    "y_move_min": "Y轴往复最小位置(mm)",
    "y_move_max": "Y轴往复最大位置(mm)",
    "out_front_x_offset": "外侧前X轴偏移(mm)",
    "out_after_x_offset": "外侧后X轴偏移(mm)",
    "in_front_x_offset": "内侧前X轴偏移(mm)",
    "in_after_x_offset": "内侧后X轴偏移(mm)",
    "x_pos_speed": "X轴定位速度(mm/s)",
    "x_recip_speed": "X轴往复速度(mm/s)",
    "x_status_offset": "喷枪出粉偏移(mm)",
    "origin_pos": "Y轴原点位置(mm)",
    "out_up_y_offset": "外侧上顶Y轴偏移(mm)",
    "out_down_y_offset": "外侧下底Y轴偏移(mm)",
    "in_up_y_offset": "内侧上顶Y轴偏移(mm)",
    "in_down_y_offset": "内侧下底Y轴偏移(mm)",
    "y_pos_speed": "Y轴定位速度(mm/s)",
    "y_recip_speed": "Y轴往复速度(mm/s)",
    "out_z_front_offset": "外侧Z轴前定位偏移(mm)",
    "out_z_after_offset": "外侧Z轴后定位偏移(mm)",
    "search_front_z_offset": "搜索Z数据前偏移(mm)",
    "search_after_z_offset": "搜索Z数据后偏移(mm)",
    "in_z_front_offset": "内侧Z轴前定位偏移(mm)",
    "in_z_after_offset": "内侧Z轴后定位偏移(mm)",
    "z_back_speed": "Z轴反喷速度(mm/s)",
    "z_zeroing_speed": "Z轴归零速度(mm/s)",
    "z_spray_position": "平板Z轴喷涂位置(mm)",
    "outside_total_cycles": "外侧往复喷涂次数",
    "inside_total_cycles": "内侧往复喷涂次数",
    "recip_reduce_distance": "往复减少距离(mm)",
}

OUT_2D_SERVO_PARAM_KEYS = ["out_front_x_offset", "out_up_y_offset", "out_down_y_offset", "out_z_front_offset", "out_z_after_offset", "x_pos_speed", "y_recip_speed",]

INOUT_UP_PARAM_KEYS = [
    "out_front_x_offset", "out_after_x_offset", "in_front_x_offset", "in_after_x_offset",
    "out_up_y_offset", "in_up_y_offset", "out_z_front_offset", "out_z_after_offset",
    "search_front_z_offset", "search_after_z_offset",
    "x_pos_speed", "x_recip_speed", "y_pos_speed", "y_recip_speed",
]

INOUT_DOWN_PARAM_KEYS = [
    "out_front_x_offset", "out_after_x_offset", "in_front_x_offset", "in_after_x_offset",
    "out_down_y_offset", "in_down_y_offset", "out_z_front_offset", "out_z_after_offset",
    "search_front_z_offset", "search_after_z_offset",
    "x_pos_speed", "x_recip_speed", "y_pos_speed", "y_recip_speed",
]

OUT_LIFT_PARAM_KEYS = ["out_z_front_offset", "out_z_after_offset"]

XN_UPDOWN2_PARAM_KEYS = [
    "out_front_x_offset",
    "out_after_x_offset",
    "x_pos_speed",
    "x_recip_speed",
    "out_up_y_offset",
    "out_down_y_offset",
    "y_pos_speed",
    "out_z_front_offset",
    "out_z_after_offset",
]

XN_UPDOWN4_PARAM_KEYS = [
    "out_front_x_offset",
    "out_after_x_offset",
    "x_pos_speed",
    "x_recip_speed",
    "out_up_y_offset",
    "out_down_y_offset",
    "in_up_y_offset",
    "in_down_y_offset",
    "y_pos_speed",
    "search_front_z_offset",
    "search_after_z_offset",
    "out_z_front_offset",
    "out_z_after_offset",
]

DEVICE_PARAM_KEYS = {
    0: [
        "out_front_x_offset", "x_pos_speed", "x_recip_speed", "x_status_offset", "out_up_y_offset", "out_down_y_offset", "y_pos_speed", "y_recip_speed",
        "out_z_front_offset", "out_z_after_offset", "z_back_speed", "z_zeroing_speed", "outside_total_cycles", "recip_reduce_distance",
    ],
    1: [
        "out_front_x_offset", "out_after_x_offset", "in_front_x_offset", "in_after_x_offset", "x_pos_speed", "x_recip_speed",
        "x_status_offset",
        "out_up_y_offset", "out_down_y_offset", "in_up_y_offset", "in_down_y_offset", "y_pos_speed", "y_recip_speed",
        "out_z_front_offset", "out_z_after_offset", "in_z_front_offset", "in_z_after_offset", "z_back_speed", "z_zeroing_speed",
        "outside_total_cycles", "inside_total_cycles", "recip_reduce_distance",
    ],
    2: [
        "out_front_x_offset", "out_after_x_offset", "in_front_x_offset", "in_after_x_offset", "x_pos_speed", "x_recip_speed",
        "x_status_offset",
        "out_up_y_offset", "out_down_y_offset", "in_up_y_offset", "in_down_y_offset", "y_pos_speed", "y_recip_speed",
        "out_z_front_offset", "out_z_after_offset", "in_z_front_offset", "in_z_after_offset", "z_back_speed", "z_zeroing_speed",
        "outside_total_cycles", "inside_total_cycles", "recip_reduce_distance",
    ],
}


def parameter_order(sn: int, config: dict, strategy_name: str) -> list[tuple[str, str]]:
    if strategy_name == "continuous_bidirectional":
        return [(key, CONTINUOUS_LABELS[key]) for key in CONTINUOUS_PARAM_KEYS.get(config.get("type", ""), ())]
    if strategy_name == "frame_by_frame":
        keys = {"inout_up": INOUT_UP_PARAM_KEYS,
                "inout_down": INOUT_DOWN_PARAM_KEYS,
                "H2D_XYservo": OUT_2D_SERVO_PARAM_KEYS,
                "2d_servo": OUT_2D_SERVO_PARAM_KEYS,
                "xn_updown4": XN_UPDOWN4_PARAM_KEYS,
                "xn_updown2": XN_UPDOWN2_PARAM_KEYS,
                "out_2d_servo": OUT_2D_SERVO_PARAM_KEYS,
                "out_lift": OUT_LIFT_PARAM_KEYS,
                }.get(config.get("type", ""), ())
    else:
        keys = DEVICE_PARAM_KEYS.get(sn, DEVICE_PARAM_KEYS[1] if config.get("type", "") == "xn_side" else ())
    return [(key, PARAM_LABELS[key]) for key in keys]
