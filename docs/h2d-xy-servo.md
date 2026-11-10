# H2D_XYservo 按帧规划

设备 2、5 使用独立的 `Motion2DXYServoFramePlanning`，与旧 `MotionOut2DServoFramePlanning` 区分。`spray_num=3`、`spray_radius=500`，使用本侧按帧数据。

- 运动搜索 Z：`z_position - spray_radius * (spray_num - 2) - out_z_front_offset` 至 `z_position + spray_radius * (spray_num - 2) + out_z_after_offset`。
- 在搜索范围内提取 Y 最小、最大值及 X 最小值；全零空帧不参与计算。
- Y 下限：`y_min - out_down_y_offset - origin_pos[0]`；上限：`y_max + out_up_y_offset - origin_pos[0]`。以 `y_recip_speed` 在两端往复，到位按 `spray_pos_tolerance` 判断。
- X：`x_min - out_front_x_offset - x_position`，速度为 `x_pos_speed`。
- 三枪检测分别为 `z_position - spray_radius / 2 - spray_radius` 至 `z_position - spray_radius / 2`、中间 `z_position ± spray_radius / 2`、`z_position + spray_radius / 2` 至 `z_position + spray_radius / 2 + spray_radius`。这些窗口单独扫描，不受运动搜索窗口截断。
- 边界向上取整并转换到 Z 帧索引；使用闭区间，共享边界有数据时两把相邻枪均可置位。
- 第 1/2/3 把枪分别使用 X 轴 `Status` 的 bit0/1/2，掩码为 0～7；不写入 `Gun_cont1/2`。左侧 X 为 AxisList[3]，右侧 X 为 AxisList[5]。
- XY 位置按设备限位及 Int16 范围限制；速度限制到非负设备最大速度与 Int16 范围。没有有效运动范围、配置异常或速度为零时不开枪。
- 关闭设备、安全返回、手动和清理模式不带三枪状态；使能请求由策略规划器处理：关闭按钮立即关枪，但设备报文位持续为 1，所有轴回到安全位置后才清零；发包层不再覆盖规划结果。

`MachineConfig1.toml` 的设备 2、5 使用 `origin_pos` 表示 Y 轴离地高度。当前配置均为 `origin_pos = [1300]`，取单元素列表的唯一值；也兼容配置服务归一化后的标量和运行时更新值。无需新增 `y_position`。缺失或包含多个高度时输出零速、关枪命令，不猜测安装坐标。

配置格式（数值须由现场标定提供）：

```toml
# [2] 或 [5]
type = "H2D_XYservo"
spray_num = 3
spray_radius = 500
# x_position = 实际 X 安装坐标
origin_pos = [1300]  # Y 轴离地高度，单位 mm
```

代码验证覆盖左右设备发包、枪区边界、坐标换算、往复换向、限位、异常关枪和序列化；尚未进行 PLC 实机运动验收。
