def get_frame_fifo_step_mm(config, default=10):
    """读取逐帧队列每格对应的毫米数。"""
    step = config.get("frame_fifo_step_mm", default)
    if type(step) is not int or step <= 0:
        raise ValueError(f"frame_fifo_step_mm 必须为正整数，当前值: {step!r}")
    return step
