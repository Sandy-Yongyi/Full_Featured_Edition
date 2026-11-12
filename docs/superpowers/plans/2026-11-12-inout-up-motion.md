# 内外顶路径规划实施计划

**确认依据：** 用户确认内外顶负向 Y、两个原点高度、横梁门槛、Y1 阻挡定位/无阻挡往复、Y2 梁顶预检查与顶部高度、首次及大幅 Y 调整规则、X1/X2 Status bit0 开枪。

**结构：** 新增 MotionInOutUpPlanning，主按帧规划器只在设备开启自动分支分发调用。检测器保留原返回字典，新增显式方向/位置/搜索偏移入口。下梁检测转入独立 MotionInOutDownPlanning，仅保留原有检测与安全返回，不增加内外底喷涂逻辑。

**参数：** ProcessConfig 增加 safety_beam=80、beam_y_large_move_threshold=100；保持当前 MachineConfig1 已由用户修改的负 Y 限位和 origin_pos。

**约束：** 首次有梁时 Y 定位和 X 最小值定位并行，二者到位后允许往复；连续有梁且目标相对反馈变化严格超过 100 时先让 X 到最小值，保持当前 Y，随后 Y 到位再往复。等待过程锁存阶段，不因下一周期仍有梁提前解除。小幅调整不打断往复。有效喷涂期间定位/往复及等待保持粉位，失梁/本组高度超原点关粉；故障、无可用几何/反馈和关闭设备也不得开枪。Y2 保持实际 PLC Y 反馈。无梁恢复安全位置，关枪；再次有梁重新走首次定位。

## 步骤

- [x] 先编写状态机、几何、边界和关闭复位测试，确认新模块不存在导致失败。
- [x] 实现内外顶及内外底检测调用封装，主规划器移除直接检测调用。
- [x] 更新参数、使用说明及旧集成测试，只将内外底保留安全返回断言。
- [x] 运行检测/运动/使能相关回归、flake8、pyright，检查差异，不提交。

## 验证记录

新测试首先因 MotionInOutUpPlanning 缺失而失败。完成实现后，test_motion_inout_up、test_beam_detector、test_motion_2d_xy_servo、test_project_axis_map、test_device_return_enable、test_device_enable_control、test_master_enable_gate 共 59 项通过。修改代码及测试 flake8 通过；业务源码与相关测试 pyright 为 0 errors。旧轴映射测试的顶设备反馈从越界的 +100 修正为实际行程内的 -100，断言仍验证无梁时 X 先回安全位置、Y 等待，以及未全部回位时使能保持。未修改用户已更新的 MachineConfig1 负 Y 配置；未提交、未连接 PLC。
