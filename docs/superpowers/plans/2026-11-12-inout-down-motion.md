# 内外底路径规划实施计划

**确认依据：** 用户确认设备 1/4 的 origin_pos 均为 [1300,1600]，完整镜像最新内外顶规则，包括无梁下半区喷涂、首次定位、100 mm 大幅移动等待和 Y2>=Y1 相对目标约束。

**设计：** MotionInOutDownPlanning 搜索 lower 梁及运动 Z 窗口内 Y 下半区。Y1/X1 负责底部；Y2/X2 负责梁上方。主规划器只分发命令，不接收横梁结果或自动规划内部安全回位状态。公用的两机构状态机移入 motionutil/InOutFramePlanningBase.py，顶/底使用独立实例，不互相继承，也不共用机构状态。

**公式：** Y1 梁底预检查 y_bottom-safety_beam-out_down_y_offset < origin[0] 时本组安全返回关粉；否则底部 ymin-out_down_y_offset <= origin[0] 时保持 PLC Y1、X1 最小定位开粉，大于时定位差值并 X1 往复。Y2 绝对目标 y_top+safety_beam+in_down_y_offset，小于 origin[1] 时本组安全返回关粉，否则相对定位；附近 ±in_down_y_offset 有数据时 X2 最小定位，无数据时往复。

**无梁：** 下半区仍有有效 X 数据时 Y1 按 ymin-out_down_y_offset-origin[0] 限位截取后往复喷底部，Y2 待 X2 安全后去最大限位并关粉；无数据时两组安全回位关粉。防撞相对目标约束优先于保持/回位目标。

**文件：** 修改 MotionInOutDownPlanning.py、MotionInOutUpPlanning.py、MotionFrameByFramePlanning.py、MachineAxisMap.py、MachineConfig1.toml；新增共享基类、tests/test_motion_inout_down.py、docs/inout-down-planning.md；保持其他用户参数。

## 步骤

- [x] 先添加内外底几何、镜像分支、等待/往复、原点和限位、方向及启停测试，确认现有占位模块不能通过。
- [x] 提取公共运动基类、实现内外底镜像计算、统一顶底 Y 目标约束。
- [x] 接入按帧分发及复位，修改两台原点，更新文档。
- [x] 运行内外顶/底及原有运动使能相关测试、flake8、pyright；不提交，不连接 PLC。

## 验证结果

先观察到旧占位构造器不支持新接口、两台原点不正确导致新增测试失败。实现后共 83 项内外顶/底、横梁、二维、轴映射、回位、设备和总使能回归通过；修改文件 flake8 通过，业务源码与相关测试 pyright 为 0 errors。大幅 Y 调整测试显式让两组 X 尚未到最小值，避免把正确的 Y2>=Y1 修正误判为等待失败。顶设备的原有运动测试均通过。

配置保存命令曾被自动审批拒绝，担心覆盖整份配置；未执行该命令，改用精确补丁仅更新设备 1/4 的 origin_pos，其他用户配置保留。文档见 docs/inout-down-planning.md。未提交、未连接真实 PLC。

后续用户明确防撞修正方向不同：内外顶令 Y2=Y1，内外底令 Y1=Y2。已按此修正公共目标约束，并让内外底先规划 Y2、再修正 Y1 的目标及等待判断；左右设备最终报文测试期望从 1000/1000 改为 800/800，新增 Y1 下限冲突拒绝测试。共 84 项相关回归通过，flake8 和类型检查通过。
