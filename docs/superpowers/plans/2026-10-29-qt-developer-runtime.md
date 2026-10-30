# Qt 开发调试运行方式恢复

依据：原 Qt 改造设计的功能保留要求，以及用户确认的开发运行方式 1/2/3。交付版默认方式 2，不增加操作员模式选择控件，改动不提交。

- [x] 恢复 QtPipelineRuntime 的 control_type：1=TXT+PLC，2=实时采数，3=只画图。与 strategy_name、spray_mode 分开。
- [x] 方式 1 复用 DataProcessWorker，并按策略 2 增加工件处理进程；不启动激光或保存。沿用现有 TXT 联调支持范围（策略 1/2），策略 3 提前明确拒绝，不连接设备。
- [x] 方式 3 使用独立 TXT 导入进程，人工点击导入按钮后加载指定文件/目录至现有 Qt 画布；不连接设备、不启用保存、不写生产配置。导入报错通过现有告警与停机流程反馈。
- [x] 提供开发命令参数 --control-type、--data-path、--data-name；支持 main.py 顶部代码配置；方式 1/2/3 都由按钮触发。
- [x] 测试进程组合、错误输入、TXT 真正导入画布、模式隔离、停止与重新加载、默认生产入口及完整回归；记录实际验证边界。

决策：只画图模式增加一个仅负责文件导入的子进程，避免大 TXT 的磁盘读取和解析阻塞 Qt 主线程。只检查点云数据引用，不增加模拟 PLC。默认生产流程不变。

验证：先复现运行方式接口缺失。新增 13 项回归，开发模式与入口/运行时相关 22 项通过；完整回归 165 项通过（14.641 秒）。只画图使用真正的导入子进程并将实际临时 TXT 的 XYZ/RGB 应用到 Qt 画布数据，验证停止清空、重新加载及无效文件告警。联调及生产进程拓扑测试拦截启动方法，未连接真实 PLC/激光；本轮不等同现场机械联调或新文件查看流程的完整桌面验收。

实现文件：control/PointCloudFileProcess.py、control/QtPipelineRuntime.py、control/DataProcessWorker.py、control/ControlCenter.py、qt_main.py、view/qt/pages.py、view/qt/main_window.py。开发用法见 docs/qt-developer-modes.md。所有修改未提交。

2026-10-30 用户修订：方式 3 改为人工点击导入；默认视角改为 Z 水平、Y 竖直、X 深度。详细验证见迁移进度记录，完整回归最新 169 项通过。
