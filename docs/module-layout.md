# 模块目录与启动方式

根目录唯一 Python 入口是 `main.py`，其中 CONTROL_TYPE、DATA_PATH、DATA_NAME 的设置方式不变。

| 操作 | 在项目根目录执行 |
| --- | --- |
| 正式启动 | `python main.py` |
| 不连接硬件的空场预览 | `python -m model.runtime.qt_preview` |
| 只读部署检查 | `python main.py --check-deployment` |
| 检查私有实现清单 | `python -m tools.build_sdk --inventory` |
| 编译单个 SDK | `python -m tools.build_sdk --developer-env` |

`control` 保留开放的主控制、进程编排、PLC 通信、TXT 联调和数据处理进程。运行流程入口为 `control.PipelineRuntime.PipelineRuntime`。

`model.runtime` 提供进程健康监控、停止协调、环境初始化及启动辅助。环境根路径仍为项目根目录；冻结应用仍使用可执行文件目录。

`model.telemetry` 提供公共状态结构和队列状态收集；不依赖 Qt。`view.qt.QtUiBridge` 负责一秒一次的 Qt 状态刷新。

`acquisition_sdk` 提供固定公开导入入口，内部实现位于开发源码 `acquisition_sdk/_internal`。发布时用单个 `.pyd` 替代该源码包。原 `model/lidar`、`plc`、`dataprocess`、`formats`、`pointcloud` 不再需要。

项目 PLC 报文和帧头尾/读命令位于开放的 `model/MovingFrameData.py`；分枪入口及全部规则位于开放的 `model/gun_distributors`。这些文件可按项目修改，不需要重编 SDK。修改报文时仍需同步核对开放控制代码所使用的字段语义。

`model.utils.ConfigurationService` 负责通用运行配置，`model.utils.MachineConfiguration` 负责设备参数读写和下发；参数显示规则位于 `view.qt.MachineConfigSchema`。

构建清单精确包含22个实现及SDK包初始化：lidar4、plc2、dataprocess7、formats4、pointcloud5。FrameQueueManager移入私有formats并公开导出，PointsFileUtil移入私有pointcloud；其余utils保持开放源码和原路径。构建排除整个开放model/control/view命名空间；输出仅为SDK扩展，不是完整软件发布包。

旧的 `model.plot` 无运行时引用，已删除。点云绘图由 `view.qt.point_cloud_view` 完成。此次迁移不改变进程数量、队列通信方式和 TOML 配置路径。
