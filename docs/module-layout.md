# 模块目录与启动方式

根目录唯一 Python 入口是 `main.py`，其中 CONTROL_TYPE、DATA_PATH、DATA_NAME 的设置方式不变。

| 操作 | 在项目根目录执行 |
| --- | --- |
| 正式启动 | `python main.py` |
| 不连接硬件的空场预览 | `python -m model.runtime.qt_preview` |
| 只读部署检查 | `python main.py --check-deployment` |
| 编译私有扩展 | `python -m model.build_extensions build_ext --inplace` |

`control` 保留开放的主控制、进程编排、PLC 通信、TXT 联调和数据处理进程。运行流程入口为 `control.PipelineRuntime.PipelineRuntime`。

`model.runtime` 提供进程健康监控、停止协调、环境初始化及启动辅助。环境根路径仍为项目根目录；冻结应用仍使用可执行文件目录。

`model.telemetry` 提供公共状态结构和队列状态收集；不依赖 Qt。`view.qt.QtUiBridge` 负责一秒一次的 Qt 状态刷新。

`model.pointcloud` 提供 TXT 导入、共享内存缓冲和点云保存。`model.lidar` 提供采数进程、采数策略及激光驱动。

`model.utils.ConfigurationService` 负责通用运行配置，`model.utils.MachineConfiguration` 负责设备参数读写和下发；参数显示规则位于 `view.qt.MachineConfigSchema`。

构建清单仅包含 `model/lidar`、`model/plc`、`model/dataprocess`、`model/formats`、`model/pointcloud` 五个目录中的 Python 模块（不编译 `__init__.py`）。`control`、`view`、配置与公共状态保持源码形式。编译输出不自动删除源文件；发布时需按团队交付规则筛选源码。

旧的 `model.plot` 无运行时引用，已删除。点云绘图由 `view.qt.point_cloud_view` 完成。此次迁移不改变进程数量、队列通信方式和 TOML 配置路径。
