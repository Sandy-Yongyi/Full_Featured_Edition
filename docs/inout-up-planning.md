# 内外顶 Y1/X1、Y2/X2 喷涂规划

实现文件：model/motionplan/MotionInOutUpPlanning.py。MotionFrameByFramePlanning 只在对应设备开启且进入自动运动分支时调用；关闭、故障安全返回、手动或清理时重置自动等待/往复状态。左右侧共用一个类，状态按设备 SN 和机构 1/2 分开。

## 配置

ProcessConfig.toml：

```toml
safety_beam = 80
beam_y_large_move_threshold = 100
```

设备以 origin_pos=[Y1离地高度,Y2离地高度] 表示原点，例如 [3000,3300]。Y 向负方向运动、X 向正方向运动；min_limit_pos=[-1600,0]、max_limit_pos=[0,1200]、safe_pos=[0,0]。保留独立四轴限位配置兼容。所有目标和速度受对应轴限位及 Int16 范围约束。

## 两个搜索窗口

1. 查梁窗口：z_position-search_front_z_offset 至 z_position+search_after_z_offset。向检测器显式传入安装方向、Z 定位、前后偏移，返回上横梁 found/y_bottom/y_top。
2. 运动窗口：z_position-out_z_front_offset 至 z_position+out_z_after_offset。共用搜索窗口内 y_center 以上的非零 X 最小/最大值和最高 Y；y_center 是查梁窗口全部正 Y 的最高、最低值中点，包含未达到梁出现比例的层。

Z 两端包含，索引下界向上取整、上界向下取整，完全越界不使用边缘帧。左右侧只读取各自数据。

两把枪共用 X 端点：

```text
x_low  = xmin - out_front_x_offset - x_position
x_high = xmax - out_after_x_offset - x_position
```

## Y1/X1：横梁下方

```text
y1_absolute = y_bottom - safety_beam - in_up_y_offset
y1_target = y1_absolute - origin_pos[0]
```

y1_absolute > origin_pos[0] 时本组回安全位置并关粉；等于原点时允许目标 0 喷涂。

在运动 Z 窗口内，检查绝对 Y 范围 [y1_absolute-in_up_y_offset,y1_absolute+in_up_y_offset] 中是否存在正 Y 数据。有数据时 X1 定位 x_low，采用 x_pos_speed 并持续开粉；没有数据时在 x_low/x_high 往复，采用 x_recip_speed 并持续开粉。局部检查不重新计算 X 端点。

## Y2/X2：顶部

先做独立横梁高度预检查：

```text
beam_top_absolute = y_top + safety_beam + out_up_y_offset
```

若 beam_top_absolute > origin_pos[1]，本组回安全位置并关粉。否则使用共用搜索结果：

```text
y2_absolute = ymax + out_up_y_offset
```

- y2_absolute >= origin_pos[1]：Y2 目标使用 PLC 当前实际反馈，X2 定位 x_low，采用 x_pos_speed 并持续开粉。
- y2_absolute < origin_pos[1]：Y2 定位 y2_absolute-origin_pos[1]，X2 在 x_low/x_high 往复，采用 x_recip_speed 并持续开粉。

## 首次及大幅调整

- 无梁到有梁，或设备重新开启：Y 定位和 X 定位 x_low 并行；Y 到位且 X 到最小值后才进入往复。不会要求 X 先回安全原点。
- 连续有梁，Y 新目标与当前实际反馈差值严格超过 beam_y_large_move_threshold：保持当前 Y，让对应 X 到 x_low；X 到位后改变 Y，等待 Y 到位再恢复往复。等待状态跨周期保持，不因仍有数据而提前解除。
- 差值不超过阈值：Y 以 y_pos_speed 跟随目标，不打断现有 X 往复。
- 两组分别判断、分别等待。往复到端点公差内后换向。

有效横梁且本组高度有效时，X1/X2 Status bit0 保持为 1，包括 X 定位、上述等待和往复换向。没有横梁时两组关粉、安全返回，再次有梁重新首次定位；本组高度超原点时只关闭该组。无有效运动几何、缺少反馈、错误配置或有效速度为 0 时也不开枪。

失梁时以及高度超原点时的安全返回沿用 X 先回 safe_pos、Y 再回 safe_pos 的既有流程；这与有梁喷涂中的首次/大幅调整规则不同。Gun_cont1/Gun_cont2 不用于这两把枪。

## 当前验证范围

已用合成帧和模拟 PLC 反馈验证几何、负 Y 限位、原点相等边界、连续等待、100 mm 边界、左右映射、持续粉位及关闭复位。尚未用现场点云和真实 PLC 验证机械轨迹。
