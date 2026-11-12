# HNXS 横梁查找与运动链路分析

分析对象：`D:/Code/HNXS` 的 `FindBeams.py`、`FrameAnalyzer.py`、`MotionBuilder.py` 和 `control/PlcCommunicationProcess.py`。补充读取其 TOML 参数及 `FrameStackManager`，用于核对窗口单位和堆栈方向。本次仅静态分析，未修改 HNXS 或当前项目业务代码，未连接 PLC。

## 1. 调用顺序与职责

横梁检测实际上发生在 `auto_move_calculate()` 之前：

```text
PLC 主循环：接收 PLC → 接收激光帧 → 按 FIFO 推入左右堆栈
  └─ _axis_to_moving_frame()
       ├─ current_enable_value == 3
       │    ├─ BeamAndYAxisProcessor.process()     横梁检测、选择枪组和 Y 定位
       │    └─ auto_move_calculate(runtime_machine)
       │         ├─ FrameSearcher.analyze_for_machine()  局部矩形搜索、X 范围和阻挡判定
       │         ├─ MotionBuilder.build_xn_from_search() Y/U 指令与阶段切换
       │         └─ 汇总原始搜索 status，生成 gun_bits
       └─ 其他情况：move_to_origin()，枪位为 0
```

| 文件 | 实际作用 |
| --- | --- |
| FindBeams.py | 对 `type=1` 的云雀设备检测上下横梁，计算绝对 Y 目标及轴启用标记 |
| FrameAnalyzer.py | 根据已选 Y 目标，在 Z/Y 矩形内搜索 X，计算相对 X/U 目标及阻挡状态 |
| MotionBuilder.py | 把搜索结果转换为旧项目的 Y/U/SP 轴命令，维护进入/运行/退出阶段及往复方向 |
| PlcCommunicationProcess.py | 调用各模块、维护 FIFO 堆栈、组合设备和喷枪位并发送旧报文 |

旧项目 U 轴承担进退/往复方向，迁移到当前项目时需要明确对应本项目的 X 轴；旧轴数组、设备编号和报文不能直接复制。

## 2. 算法使用的数据

数据是按 Z 位置组织的 `frame_stack["left"/"right"]`，不是直接处理原始三维点集。每帧的 `FrameData` 包含按 Y 分层后的记录：

```text
H_Axis     → 这一层的 Y 高度
V_Axis_Min → 这一层的 X 最小值
V_Axis_Max → 这一层的 X 最大值
```

旧 `FrameStackManager.push_frame()` 将最新帧写入 index 0，旧帧向后移动，因此设备离激光的距离通过堆栈索引体现。空帧实际填充 H/X 都为 0；其注释写着固定 Y 层高度，但实际代码将 `H_Axis=0`。

旧检测器使用同一个 `y_threshold` 同时作为 Y 分层间距和 Z 毫米到帧索引的换算单位。旧配置中 Y/Z 阈值均为 10，暂时掩盖了这种耦合。当前项目迁移时必须独立使用真正的 Z 帧间距。

## 3. 横梁检测：沿 Z 统计 Y 出现频率

入口为 `BeamAndYAxisProcessor.process()`，只为 `type=1` 的云雀设备执行检测；`type=2` 的二维往复机直接沿用配置中的固定 Y 和启用列表。

### 3.1 选取设备位置附近的 Z 窗口

由设备 `offset_z`、`find_beams_length_z` 和 `y_threshold` 计算：

```text
center = offset_z // y_threshold
start  = int(center - find_beams_length_z / y_threshold / 2 - 1)
end    = int(center + find_beams_length_z / y_threshold / 2 - 1)
```

下界至少为 0，循环包含 start 和 end；上界通过 `idx < len(stack)` 限制。只有存在 `H_Axis > 0` 的帧才保留。

例：`offset_z=8570、长度=1000、间距=10`，实际扫描 index 806～906，共 101 个索引。公式中的 `-1` 使窗口相对理想中心偏移一帧，迁移时应重新确认，不直接照搬。

### 3.2 逐帧计数并筛选稳定高度

每帧提取全部正 Y，用 `set()` 去重后，每个 Y 最多计一次：

```text
count[Y] = 包含该 Y 高度的有效帧数量
候选高度条件：count[Y] >= 有效帧数量 × beams_threshold
```

这相当于找“沿 Z 持续存在的 Y 高度”，不是找某帧点数最多的位置，也没有对 X 深度做横梁判定。

例如窗口有 100 帧、其中 80 帧非空，比例 0.7 的实际门槛是 56 帧，不是 70 帧。只有 1 个有效帧时，这一帧内全部正 Y 都可通过比例门槛，代码没有最低样本数量要求。

### 3.3 将候选高度合并为梁段

1. 候选 Y 从小到大排序。
2. 若相邻 Y 恰好相差 `y_threshold`，归为同一连续段。
3. 连续段间距严格小于 `merge_beams` 时再次合并。
4. 梁段厚度定义为 `y_top - y_bottom`，不加一个 Y 网格宽度。
5. 厚度不超过 `beams_width` 才有效；单个高度的厚度为 0，也会接受。

### 3.4 选取上、下横梁

所有出现过的正 Y（包括未达到比例门槛的 Y）决定参考中心：

```text
y_center = (最小有效 Y + 最大有效 Y) / 2
```

- 只有一个合并段：其中心高于 y_center 就是上梁，否则是下梁；相等时归下梁。
- 多个合并段：只考虑最底段和最顶段。最底段有效则为下梁，最顶段有效则为上梁。
- 极端段过宽被拒绝后，不会继续向内部寻找替代梁；中间候选段也不会输出。

最终输出每侧 `upper/lower`，每根梁只有 `y_bottom/y_top`。没有横梁 ID、跨周期跟踪、置信度历史或目标锁存。

## 4. 横梁转换为 Y 目标与枪组

`_calculate_y_positions()` 从 `origin_pos` 复制绝对 Y 初始高度，启用列表全部置 0。

旧设备假定有 6 个 Y 轴，分为 `(0,1)、(2,3)、(4,5)` 三对。计算总高度范围：

```text
max_travel = origin_pos[-1] + limit_pos[1] - origin_pos[0]
section_len = max_travel / 3
```

用横梁中心落在上面三段中的位置选择轴对。每对的两个目标为：

```text
下方枪 Y = max(梁底 - y_safety, 该轴原始高度)
上方枪 Y = max(梁顶 + y_safety, 该轴原始高度)
```

实际 `y_safety` 由 SprayConfig 的 `y_location` 传入，当前值 150。选中的两轴启用为 1。

最后 `_fix_sequential_movement()`：每轴最多高于自身原始高度 1000 mm；相邻轴目标间距不得小于原始高度差，等价于后轴位移不得小于前轴位移。未启用的轴也可能因为这个约束被调整目标高度。

注意：下梁先计算、上梁后计算；若它们选中同一轴对，后计算的上梁会覆盖下梁目标。硬编码三对轴及 1000 mm 行程不能用于当前只有 Y1/Y2 的内外顶底设备。`_assign_beam_to_axes()` 并未被当前主链调用，应以 `_calculate_y_positions()` 为准。

## 5. Y 定位后，局部搜索 X 和阻挡

`auto_move_calculate()` 按设备调用 `FrameSearcher.analyze_for_machine()`。

### 5.1 X 搜索窗口

Z 范围为 `offset_z - z_start_diatance` 至 `offset_z + z_end_diatance`，换算时使用整数整除，包含两端索引。它与检测横梁的宽 Z 窗口不同。

对云雀，只有一对枪的两个启用标记都为 1，才处理该枪组。设两个绝对 Y 目标为 `Y0/Y1`：

```text
margin = y_diatance + y_limit
枪组搜索 Y 范围 = [Y0 - margin, Y1 + margin]
单枪阻挡 Y 范围 = [当前枪 Y - margin, 当前枪 Y + margin]
```

收集矩形内每行的非零 X 最小值和最大值，然后：

```text
x_min = max(min(xs) - offset_x - x_diatance, 0)
x_max = max(max(xs) - offset_x - x_diatance, 0)
y_target = 绝对 Y 目标 - origin_pos[该轴]
```

任一 X 目标大于 0，搜索结果 `status` 就为 1。代码没有要求二者同时大于 0。

### 5.2 阻挡检测的实际含义

`has_any_y_in_rectangle()` 内部仍调用 X 收集函数，所以实际条件是“矩形内存在非零 Y 且至少有一个非零 X”，不只是注释中的 Y 非零。

当 `blocked=True` 时，代码把 `x_max` 改为 `x_min`，但保留原先可能为 1 的 status。因此实际行为是取消 X 往复、改为 X 定位，**并没有实现注释中‘不能进枪/关枪’的承诺**。

二维往复机的分支不依赖横梁：使用固定 Y 枪高和往复行程构造搜索区域，X/U 定位到局部最小 X，再让共用 Y 轴往复。

## 6. 运动构建与喷枪位

旧云雀阶段意图为：

```text
idle → entering（U 回零，Y 定位）→ running（U 往复）→ exiting（U 回零）→ idle
```

往复方向按轴保存，到端点容差范围内后换向。若总行程大于两倍变速距离，中间区域用快速，端部区域用慢速；否则全程慢速。代码主要限制目标不为负，没有统一使用机器最大位置和最大速度做末端校验。

实际状态机存在以下差异：

- 第一次有数据时进入 entering；下一周期只要上周期和本周期都存在有效 status，就直接将 stage 改成 running，可能绕过 Y 到位等待。
- exiting 中仍然立即生成新 Y 目标，没有真正等待全部 U 回零后才允许 Y 移动。
- 状态按整台设备的 `any(status)` 切换，没有独立锁存每个枪组；检测结果变化会直接改变目标。
- PLC 轴反馈读取异常时默认返回 0，可能把缺失反馈当作回零成功。

喷枪位来自 `FrameSearcher` 返回的原始 `status`，并非最终运动阶段或到位结果：FX 占 bit0～7，设备 2 云雀从 bit8 开始，其他云雀从 bit14 开始，汇总进旧报文 `Gun_cont1`。所以 entering/exiting 或 blocked 情况下，仍可能存在 status=1 的开枪位。迁移时必须把开枪许可与运动状态联锁。

## 7. 旧项目实际参数与调节影响

| 参数 | 当前 HNXS 值 | 影响 |
| --- | --- | --- |
| find_beams_length_z | 1000 | 横梁统计的 Z 长度；长窗口更稳定，但可能混入相邻工件 |
| y_threshold | 10 | Y 层连续性；旧代码同时把它用于 Z 索引 |
| beams_threshold | 0.7 | 某 Y 在非空帧中的最低出现比例 |
| merge_beams | 300 | 合并梁段的间距阈值，严格小于才合并 |
| beams_width | 200 | 合并后的最大梁厚度 |
| y_location | 150 | 枪 Y 距离梁上下边缘的安全距离 |
| z_start_diatance / z_end_diatance | 100 / 100 | X 搜索和阻挡检测的前后 Z 长度 |
| x_diatance / y_diatance | 100 / 100 | X 进枪偏移、Y 搜索安全范围 |
| u_fastspeed / u_slowspeed | 500 / 300 | 旧 U/X 往复快慢速度 |
| u_changespeed_threshold | 100 | 距离端点的减速区域长度 |
| pos_tolerance | 5 | 到位和换向容差 |

当前合并阈值 300 大于最大梁厚 200：多个近邻细段可能先合并、再因总厚度过宽而全部丢弃。参数应结合真实点云调节，不能只增加合并距离来提升检出率。

## 8. 迁移到当前项目的建议

可复用的是“按 Z 统计 Y 持续出现比例 → 连续段合并 → 梁段筛选”的检测思路；不直接复用旧枪组分配、旧运动状态机和 PLC 轴索引。

建议检测模块只输出横梁边界、有效帧数、出现比例和检测有效性；Y 目标选择及枪位许可由本项目的 `model/motionplan` 执行。数据处理与轴运动分开，便于单独验证误检、漏检和安全回位。

需明确并改造：

1. 使用本项目的 `z_position`、实际 Z 帧间距和 `FrameQueueManager`，确认空帧/FIFO 跳变语义，分离 Y 分辨率与 Z 步距。
2. 增加有效帧最低数量/窗口覆盖率，避免少量数据即被当成稳定横梁；按实际需要加入持续确认、释放滞后或工件目标锁存。
3. 明确找最上/最下两根，还是返回全部横梁；明确是否需要 X 深度/厚度特征排除门板、侧面和挂具。
4. 当前 inout_up/inout_down 各只有 Y1/X1/Y2/X2，按对应两组机构分配目标，使用本项目的 origin_pos、独立限位和轴映射，不能沿用旧三对六轴。
5. 建立真正的“X 安全 → Y 到位 → 允许进枪/往复 → 退枪 → 安全返回”状态机，阶段由轴反馈推进，状态中锁存有效目标。
6. 阻挡、无数据、配置错误、反馈缺失、关闭设备及安全返回时，按明确的本项目规则关枪；枪位由最终许可生成，不照抄旧 Gun_cont 位号。
7. 用真实 TXT 验证单上梁、单下梁、双梁、细碎噪点、空窗、少量有效帧、厚板、相邻工件和梁目标跨周期变化，再做 PLC 联调。

结论：旧实现是基于 Y 高度持续性的规则检测器，可作为本项目横梁识别的起点，但其检测有效性门槛、枪组分配和运动/开枪联锁需要独立修改后才能迁移。
