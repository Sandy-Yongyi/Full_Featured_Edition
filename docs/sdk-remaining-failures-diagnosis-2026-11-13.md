# SDK 迁移后原有六项失败的排查

## 范围和状态

这六项失败在迁移前基线中已存在，不属于 SDK 打包新增回归。本文记录根因证据，不表示已经修复；本轮没有修改 TOML、运动规划或 PLC 使能逻辑。

复现命令：`python -B -m unittest tests.test_motion_continuous_bidirectional_planning tests.test_qt_deployment -v`。
本次日志：`output/remaining-six-repro.log`；15 项测试，9 项通过、5 项断言失败、1 项错误。

## 第三模式：配置、轴映射和测试夹具不一致

`model/tomls/MachineConfig3.toml` 定义四台旧设备，类型为 `xn_rotate` 和 `z_2d_lift`。`model/motionplan/MachineAxisMap.py` 的映射仅支持 `inout_up`、`inout_down`、`H2D_XYservo`，使用 20 轴布局。运动目标辅助函数对不支持的设备类型返回空指令，因而旧配置不能由当前映射完成预期的安全位和清理动作。

测试仍采用旧轴下标，并只设置 PLC 反馈中的 `Operate`。当前 `DeviceEnableHelper.requested_operate` 从 `device_enable_mask` 读取软件请求，未设置时按零处理。这是使能位断言失败的另一个原因，不能只调整预期数值。

报警测试预期低五位使能全部清零；当前 `final_operate` 允许设备在安全返回完成前保留使能。应在设备布局确定后，对照返回状态验证报警行为，不能未经确认修改安全返回语义。

涉及的五个失败测试：

- `test_builds_all_device_safe_commands_without_overwriting_lidar_axes`
- `test_clean_mode_moves_x_to_max_only_after_all_station_data_is_empty`
- `test_clean_mode_uses_each_devices_own_x_limit`
- `test_enabled_devices_keep_their_operate_bits_after_reaching_safe_position`
- `test_servo_alarm_uses_status_bit_zero_and_disables_all_device_motion`

2026-11-13 用户确认：第三模式暂不用于现场。因此保留第三模式实现和原配置，不选择或迁移其设备布局，不删除、跳过测试或修改断言来消除上述失败。将布局适配及安全返回验证作为该模式未来现场启用的前置事项；暂不使用不代表该模式已完成现场验收。

## 部署检查：断言依赖已不存在的项目字段

`test_repository_configurations_all_parse_after_confirmed_sn3_conflict_resolution` 的十份配置解析检查通过，随后读取 `MachineConfig1.toml` 中的 `config["3"]["top_chain_hold_enabled"]` 触发 KeyError。该字段当前不存在，错误并非 TOML 解析失败。

后续应将仓库解析测试与历史项目字段约束分离，使用实际部署检查契约验证；不得为迎合测试而向现场配置补入无依据的业务参数。

## 后续验证

确定第三模式设备布局后，单独实施修复，并明确记录是否涉及业务行为变化。随后重跑目标测试、全量回归以及源代码/二进制一致性验证；若发布文件改变，重新生成 ZIP 和哈希清单。真实 PLC、雷达、工件及独立机器验收仍需现场环境。
