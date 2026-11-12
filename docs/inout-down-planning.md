# 内外底 Y1/X1、Y2/X2 喷涂规划

实现：model/motionplan/MotionInOutDownPlanning.py。Y 原点在下方，Y/X 均向正方向运动。设备 1/4 的 origin_pos=[1300,1600]，分别是 Y1/Y2 离地高度；保留各设备当前行程、速度与安全位置配置。

## 结构

MotionFrameByFramePlanning 仅在自动模式且设备开启时分发调用，接收轴命令，不接收或存储横梁结果。顶/底设备继承 motionutil/InOutFramePlanningBase，共用已验证的限位、反馈读取、首次/大幅 Y 调整等待、X 往复和异常关粉流程；各规划器实例的状态独立，按 SN 和机构编号保存。下梁检测仍属于私有 dataprocess 功能块。

## 搜索窗口

- 下梁检测：按 install_orietation 取 left/right，显式传入 z_position-search_front_z_offset 至 z_position+search_after_z_offset，使用 lower 结果。
- 运动搜索：z_position-out_z_front_offset 至 z_position+out_z_after_offset，Y 取 y_center 以下的点云，包含中心。共用 xmin/xmax/ymin。
- y_center 为查梁窗口全部正 Y 的最高最低中点；无梁且查梁窗口为空时允许使用运动窗口自身的 Y 范围中点。
- 窗口两端包含，下界索引向上取整、上界向下取整，完全越界不使用边缘帧。

X 两个端点：

```text
x_low  = xmin - out_front_x_offset - x_position
x_high = xmax - out_after_x_offset - x_position
```

目标和速度均限制在设备对应轴范围及 Int16 范围内。

## Y1/X1：底部喷涂

先检查横梁底部是否允许出枪：

```text
beam_bottom_absolute = y_bottom - safety_beam - out_down_y_offset
```

beam_bottom_absolute < origin_pos[0]：本组关粉并按既有 X 先回安全、Y 再回安全流程处理。等于原点时允许。

通过后，使用运动窗口中的最低 Y：

```text
y1_absolute = ymin - out_down_y_offset
```

- y1_absolute <= origin_pos[0]：保持 PLC 当前 Y1 实际反馈，X1 定位 x_low，使用 x_pos_speed 并持续开粉。
- y1_absolute > origin_pos[0]：Y1 定位 y1_absolute-origin_pos[0]，X1 在 x_low/x_high 往复，使用 x_recip_speed 并持续开粉。

## Y2/X2：横梁上方喷涂

```text
y2_absolute = y_top + safety_beam + in_down_y_offset
y2_target = y2_absolute - origin_pos[1]
```

y2_absolute < origin_pos[1]：本组关粉、安全返回。否则定位对应 Y2 相对目标。

在同一运动 Z 窗口内检查绝对 Y 区间 [y2_absolute-in_down_y_offset,y2_absolute+in_down_y_offset]：有正 Y 数据时 X2 定位 x_low，使用 x_pos_speed 开粉；全空时 X2 在 x_low/x_high 往复，使用 x_recip_speed 开粉。局部检查只选择运动模式，X 端点仍使用共用搜索结果。

## 未找到下梁

若运动 Z 窗口与 Y 下半区仍有有效 X 数据：

- Y1 目标 ymin-out_down_y_offset-origin_pos[0]，截取到对应限位内可达位置；X1 往复喷底部。
- X2 先回安全位置并关粉，到位后 Y2 移到最大限位。
- 维持有效的 Y1/X1 往复状态，只清除 Y2/X2 的喷涂状态；再次出现下梁时 Y2 重新首次定位。

无有效下半区几何则两组安全返回关粉。缺少反馈、配置错误、有效速度为 0 时不开枪。

## 状态、相对位置与报文

- 首次有效目标：Y 定位和 X 定位 x_low 并行，Y 到位且 X 到最小值后才往复。
- 连续有效目标变化距 PLC 反馈严格超过 beam_y_large_move_threshold（默认 100 mm）：对应 X 到最小值、Y 到位后恢复往复，等待跨周期保持；小幅调整不暂停往复。
- 始终要求发送的相对位置 Y1<=Y2。内外底以 Y2 为基准：若 Y1>Y2，将 Y1 修正为 Y2，保持 Y2 不变，例如 Y1=1000、Y2=800 时发送 800/800。先构建 Y2 命令，再以该命令修正 Y1 目标和 X1 到位等待；最终报文写入时再次检查。约束优先于保持反馈或安全目标，若 Y1 下限无法满足则拒绝冲突轨迹、关闭运动与粉位。内外顶相反，以 Y1 为基准修正 Y2。
- X1/X2 的 Status bit0 为各自开枪位。有效目标定位、等待、往复和换向期间保持开粉；关闭设备、故障或切换手动/清理时关粉并清除自动状态。Gun_cont1/Gun_cont2 不用于本设备。

相对目标顺序约束不替代 PLC 的实际运动同步及硬件联锁。尚未连接真实 PLC 或用现场点云验证机械轨迹。
