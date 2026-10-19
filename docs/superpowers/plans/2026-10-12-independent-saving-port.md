# Full-featured independent saving implementation plan

> 用户已明确授权同步功能并要求兼容三种模式。当前会话直接实施，使用 TDD、独立审查及完成前验证。

**Goal:** 三种模式均移除采集进程保存线程，同时保持全功能语义。
**Architecture:** 来源共享块池和同级保存进程；模式区别放在显式任务元数据与已有计算数据准备中。
**Spec:** ../specs/2026-10-12-independent-saving-port.md

- [x] 保存端支持 relative_z 与 absolute_sorted，预览按工件元数据控制与镜像；先补反向扫描、右原点和禁用预览测试。
- [x] 采集端复制存储帧到共享池；非逐帧模式用计算帧列表保留完整数组接口；模式准备独立于保存提交。测试三模式两原点、原发送消息及多工件。
- [x] 主界面启动/故障/排空移植，保留 ModeConfig、密码、中英文、清洗与模式特有控件。
- [x] 配置/setup/README/脚本示例同步；运行新增测试与原测试、Cython、diff 审查。
- [x] 独立审查后修复重要问题，再白名单同步目标项目并在目标重跑验证。

## Ledger

- 目标基线 e7c5fa0a58ff4c4a73bd563eca3330623755f2e6，只有 output/ 未跟踪，不触碰。
- 基线 7 个测试中 1 个已有失败：清洗轴期望900、实际1150，保留并报告。
- 全部暂存编辑在 D:/Code/SXZJ/.port-full-featured，目标写入使用用户授权的专用提权命令；不改全局 git 配置，不提交。
- 三模式×两原点下游数据对照、连续反向绝对Z、跨块回绕精度、右原点仅预览镜像、分区模式禁用保存预览、PLC连接代数/逐帧消息、密码关闭及无固定点数上限均通过。
- `python tests/run_saving_tests.py`：33项通过。原全套只有既有清洗测试失败；没有新增运动控制修改。
- 5个核心变更模块通过 Cython 生成 C 检查，compileall 通过；没有编译发布 exe/pyd。
- 一次独立只读审查未发现阻止同步的重要问题。现场雷达、PLC、异常断线与窗口关闭仍须实测。
- 白名单18个文件已同步目标：7个更新、11个新增；复制前与后均检查SHA256及路径范围，未覆盖其他工作。
- 目标 `D:/Code/Full_Featured_Edition` 专项33项通过；全套40项中39项通过，唯一失败仍是基线清洗测试（1150 != 900）。目标compileall和git diff --check通过。
- Windows spawn 验证从真实脚本运行；stdin测试入口不能被spawn重载，因此新增 tests/run_saving_tests.py 作为专项入口。
