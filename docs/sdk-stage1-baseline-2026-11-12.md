# 采数 SDK 第一阶段：范围、依赖与行为基线

日期：2026-11-12。状态：第一阶段检查完成，等待确认后进入第二阶段接口设计；尚未开发 SDK 或编译产物。

## 已确认的目标与执行约束

- 下层编译为 Python 可调用的 SDK，发布时不需要原来的五个私有包目录。
- 上层继续提供 Python 源码，`control`、`view`、`model/motionplan` 保持开放。
- 根据本阶段用户新增要求，`GunDistributor.py` 及整个 `gun_distributors`（含基类、默认规则和所有项目规则）全部开放。
- 后续建议新建 `model/gun_distributors/`，统一放置分枪入口和各分枪实现；本阶段尚未移动文件，这不是最终接口设计。
- 保持三种采数策略及开发运行方式的现有支持关系。此次封装不重写算法、不扩展原有支持范围、不改变报文、坐标、队列、进程及停止语义。
- 一阶段一确认。第一阶段只做审计、现有测试与文档；既有业务失败单独记录，不在本阶段修复。

## 基线版本与环境

- 基线提交：`6a9b102bc1fa23253fea2e1c09e6cd1a6bcc8799`。
- 开始时 Git 工作区干净；本阶段只新增本报告和 `output/sdk-baseline/` 证据文件。
- 解释器：`C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe`，CPython 3.11.0，Windows AMD64。
- 实际环境：NumPy 2.1.3、Open3D 0.19.0、SciPy 1.14.1、PyQt6 6.11.0、Cython 3.0.12、Nuitka 2.5.9、setuptools 65.5.0、tomlkit 0.13.3。
- 这些是本机实测版本，不代表已验证整个 `requirements.txt` 声明范围，尤其不能将本机结果推广到其他 Python 小版本和架构。
- 对 `main.py`、根目录构建脚本、requirements、model/control/view/tests 下 Python 与 TOML 共 181 个文件记录 SHA-256；测试前后相同。
- 未安装或升级依赖，未启动生产界面、连接设备、编译扩展或修改现场配置。测试使用离屏 Qt；现有测试仍会创建模拟工作进程、临时文件和项目日志。

## 更新后的开放与闭源候选范围

| 范围 | 实现文件数（不含 __init__.py） | 第一阶段结论 |
| --- | ---: | --- |
| model/lidar | 4 | 闭源候选：驱动、采数进程、三策略、方向状态 |
| model/plc | 3 | 闭源候选：通信、报文编解码、收发数据类型 |
| model/dataprocess | 7 | 闭源候选：滤波、拆分、整件分区识别、逐帧建帧、横梁检测 |
| model/formats | 3 | 实现为闭源候选；上层使用的数据类型必须公开可调用 |
| model/pointcloud | 4 | 闭源候选：文件回放、保存、共享内存与保存服务 |
| GunDistributor.py + gun_distributors | 11 | 全部开放，明确排除出闭源构建清单 |
| control / view / model/motionplan | — | 保持开放，不收进整个黑盒运行时 |
| model/utils / model/runtime / model/telemetry | — | 存在共用功能；第二阶段逐项决定公开或内部使用方式，不默认全部闭源 |

五包原始候选有 32 个实现文件，分枪开放后剩 21 个。当前旧构建脚本仍按五包递归收集，后续需要显式排除开放例外；不能继续仅以目录前缀决定闭源范围。

完整文件、类、函数、调用点和路径定位点见 [静态依赖清单](../output/sdk-baseline/dependencies.md)，机器可读记录见 [inventory.json](../output/sdk-baseline/inventory.json)。

## 依赖与接口设计必须解决的事实

### 上层直接依赖底层

静态 AST 扫描发现 26 个生产文件直接引用闭源候选模块，另有 20 个测试文件直接引用。这是显式 import 统计，不包含运行时动态行为推断。

生产调用点包括：4 个 control 文件、11 个运动规划文件、FrameQueueManager，以及 10 个直接使用底层数据类型的分枪文件。分枪目录中的默认实现只继承基类，未计入直接 import 调用点。

上层现在不只是调用一个启动入口，还会使用：

- 采数/回放工作进程、点云保存服务及共享资源接口；
- `DataFilter`、`DataSplitting`、`DataFindBlocks`、`build_side_frame`、`BeamDetector`；
- PLC 收发帧及轴数据、逐帧结构、完整工件特征结构和分枪结果结构。

因此，在保持 control/motionplan/分枪开放的前提下，“一个接口”应理解为一个固定 SDK 导入入口，不能强行缩减成只有 start/stop 的类。第二阶段必须保留上层实际需要的能力，否则会迫使业务重写。

`model.plc.MovingFrameData.AxisData` 与 `model.formats.frame_by_frame.AxisFrameDataFormat.AxisData` 是两个不同类型，公开接口需要区分；不能合并类型或覆盖名称。`BlockData` 等类型在处理进程和开放分枪之间传递，必须保持字段、默认值、类型身份与序列化一致。

### 底层的共用依赖

闭源候选直接依赖以下 9 个项目辅助模块：

`LidarDirectionUtil`、`LoggerUtil`、`MachineConfigUtil`、`PointsFileUtil`、`ProcessHeartbeat`、`StrategyUtil`、`TomlLoader`、`UiTelemetry`、`WorkpieceOriginUtil`。

此外直接依赖 NumPy、Open3D；配置辅助功能还使用 tomlkit。第三方原生依赖的运行文件仍需交付，不能把“一个自有核心 .pyd”承诺成“整个 Python 运行环境只剩一个文件”。

用户将分枪代码开放后，`XNUpDown4GunDistributor -> motionplan.MachineAxisMap` 不再是闭源底层的反向依赖。后续应让开放分枪继续调用开放轴映射，并从 SDK 获取现有特征/结果类型，不能将分枪规则复制进闭源包。

### 路径与多进程约束

- `LidarCommon`、`PlcCommon`、`DataFindBlocks` 等有基于工作目录拼出的 `model/tomls` 路径。
- 开放的 `GunDistributor` 和多个分枪实现也有此类配置定位，未来迁移目录时需要同步处理。
- `PipelineRuntime` 部分接口支持 config_dir，但不能据此认为所有底层调用已经使用该目录。
- `LoggerUtil` 导入时创建项目日志；运行根目录不能只靠移动模块后推算。
- 主入口使用 spawn 与 freeze_support。进程、队列传输类型、共享内存描述符以及进程内重新导入必须在编译产物中重新验证。
- 原有测试有对类 `__module__`、原文件位置及 patch 路径的断言；这些是布局契约，后续可以按新设计更新，但不能把业务结果断言随之放宽。

## 三种采数策略基线

编号以 `StrategyUtil.STRATEGY_CODE_MAP` 和 ModeConfig 为准。策略类内部部分旧注释编号与配置编号不同，不应据旧注释改变映射。

| strategy_name | 实际工厂类型 | 自动实时路径的工作进程 | 必须保留的差异 |
| --- | --- | --- | --- |
| 1 / frame_by_frame | FrameByFrameStrategy | 激光采数 + PLC + 点云保存，共 3 个 | 按 FIFO 建帧发送；保存相对 Z；不因保存待完成阻塞逐帧交付 |
| 2 / complete_workpiece | CompleteWorkpieceStrategy | 激光采数 + 点云处理 + PLC + 点云保存，共 4 个 | 整件积累后处理；特征数据交给开放分枪/运动规划；相对 Z；draw_type=2 时保存侧不覆盖处理侧预览 |
| 3 / continuous_bidirectional | ContinuousBidirectionalStrategy | 激光采数 + PLC + 点云保存，共 3 个 | 按往返端点划分整趟；保留绝对 Z，保存按 Z/Y/X 排序；被中断的无效趟不交付为完整工件 |

以上进程数量按 control_type=2、spray_mode=0 统计，不包含 Qt 主进程，也不代表所有喷涂模式进程组合相同。

三策略的共有约束：同原点/独立原点、左右方向、PLC 连接代次、FIFO 回绕、状态与心跳、保存任务/ACK 对应关系、停止时先封存后排空，以及共享资源生命周期均保持。

## 开发运行方式基线

| CONTROL_TYPE | 当前支持关系 | 工作进程 |
| --- | --- | --- |
| 1：TXT 联调 PLC | 策略 1、2；策略 3 在启动工作进程前拒绝 | 策略 1：回放 + PLC；策略 2：回放 + 处理 + PLC |
| 2：实时采数与运动 | 策略 1、2、3 | 见上表，必须保留各策略差异 |
| 3：只看 TXT | 不启动真实 PLC、雷达、保存链路；使用现有预览约束 | TXT 文件进程 1 个 |

三种运行方式均等待人工启动/导入，不得因 SDK 导入或实例化而连接设备。目录回放自然顺序、显式文件选择、左右方向命名和现有拒绝条件也保持不变。

当前 main.py 的现场开发设置为 CONTROL_TYPE=1，策略配置为 1；本阶段没有改成生产默认或切换现场策略。测试通过临时配置覆盖三个策略。

## 自动验证结果

逐模块运行全部 42 个 `tests/test_*.py`，每模块独立进程、120 秒超时，Qt 使用 offscreen。测试子进程通过临时 sitecustomize 禁止 socket connect/connect_ex/sendto，防止接触真实设备；保存、回放与进程测试仍使用其真实实现。0 个模块超时。

| 统计 | 结果 |
| --- | ---: |
| 测试总数 | 273 |
| 通过 | 265 |
| 断言失败 | 6 |
| 运行错误 | 2 |
| 跳过 | 0 |
| 完全通过的模块 | 39 / 42 |

另行执行现有 `main.py --check-deployment`：19 项检查通过，退出码 0。检查涵盖十份 TOML 解析、运行库导入和 qwindows.dll 存在性，不证明硬件、真实 OpenGL 或业务参数全部正确。

证据：[汇总](../output/sdk-baseline/summary.json)、[逐模块命令与退出码](../output/sdk-baseline/test-results.json)、[测试前校验值](../output/sdk-baseline/source-hashes-before.json)、[测试后校验值](../output/sdk-baseline/source-hashes-after.json)。测试日志均位于相同 evidence 目录。

### 已有不通过项（未修复）

1. **布局/构建不一致：1 个失败、1 个错误。** `test_module_layout` 预期构建脚本位于 model，但实际在根目录，导致 model.build_extensions 不可导入、根目录文件清单不符。只读调用实际脚本发现其 root 解析为 `D:\Code`，`get_extensions()` 返回 0。后续构建阶段必须处理此构建问题，不涉及改采数算法。
2. **第三策略运动规划：5 个失败。** 安全位置、清理时 X 目标、设备独立 X 限位、使能保持、伺服告警相关断言不符。测试夹具仍含旧设备/轴假设，部分与当前 20 轴六设备配置不一致；其中的全部原因尚未诊断，不能将五项一概认定为测试过时，也不能据此擅改控制逻辑。
3. **旧配置字段：1 个错误。** `test_qt_deployment` 读取 MachineConfig1 中不存在的 `top_chain_hold_enabled`。十份配置本身可解析；这是字段预期与现状不一致，未补字段或修改配置。

对这三个模块二次运行：19 个测试，仍为 6 个失败、2 个错误，退出码 1。见 [复核日志](../output/sdk-baseline/baseline-failures-recheck.log)。没有通过删除断言或修改配置消除这些失败。

### 已通过的关键行为与证据

| 行为 | 现有测试证据 | 验证范围 |
| --- | --- | --- |
| 三策略 × 两种数据原点的坐标、保存策略和交付差异 | test_lidar_save_integration 的 test_three_modes_keep_their_own_coordinates_and_delivery_interfaces | 合成数据；包含子测试组合，不增加 unittest 顶层测试计数 |
| 三策略工作进程组合 | test_qt_developer_modes 的 test_delivery_process_combinations_for_all_three_strategies_are_preserved | Process.start 被 mock，证明编排选择，不证明真实设备启动 |
| 第三策略中断趟丢弃 | test_lidar_save_integration 的 test_continuous_interrupted_pass_releases_blocks_and_is_not_saved | 模拟断连与状态 |
| TXT 联调、只看 TXT、策略 3 不支持 TXT 联调的拒绝条件 | test_qt_developer_modes，15 项全通过 | 临时点云、配置及设备调用替身 |
| TXT 自然顺序、显式名称、独立原点数据集 | test_txt_replay_sequence，5 项全通过 | 文件/队列回放 |
| 保存精度、Z 回绕、绝对 Z 排序、ACK、写盘错误 | test_point_cloud_saving、test_save_lifecycle | 包含真实 spawn 保存进程与临时文件 |
| 停止封存、背压和保存排空 | test_save_stress，3 项全通过 | CPU/文件模拟，无设备操作 |
| 开放运动规划及设备使能相关既有回归 | test_motion_inout_up/down、test_motion_2d_xy_servo、test_device_enable_control 等 | 现有单元/模拟覆盖 |

## 尚未验证及后续门槛

- 尚未生成统一 SDK、单个 .pyd、.pyi 或发布包；本阶段不证明编译路线可行。
- 尚无针对拆分后公开接口的差分测试；当前结果仅用于确定改造前基线。
- 现有测试没有证明三策略从真实雷达到 PLC 的全链路等价，也没有用现场样本独立验证全部整件识别、分区和每一种分枪规则。后续需要保留现有算法，以可重复样本补充对比；没有样本的部分明确标记为待实机验收。
- 第三策略现有扫描轴适配限制已由 README 和空 LIDAR_AXIS_MAP 记录。不能在此次封装中擅自分配旧轴或声称现场功能完整通过。
- 手动喷涂、设备异常重连、完整停止顺序、长时间运行和真实性能仍需按各自运行条件验证，不能由自动实时路径的进程数测试代替。
- 最终验收必须在没有五个底层源码目录的交付目录中验证，且上层可修改分枪与运动规划，不要求重新编译 SDK。
- 业务回归不得新增失败；已有失败不代表允许新增偏差。第二阶段需定义这些基线不通过项的处理方式，布局测试可随新接口更新，业务断言不能无依据放宽。

## 下一阶段的具体确认内容

下一步仅设计，不移动源码：确定 21 个底层实现的封装清单、9 个共用辅助模块的归属、公开类型与功能入口，以及开放分枪的新目录和导入方式。

推荐保持现有算法和队列协议，提供一个固定 SDK 入口供开放 control/motionplan/分枪调用。分枪入口及规则均保留开放，不放入核心二进制。具体导出名称和签名以第二阶段经确认的设计为准。

实施开发、构建试验和真实目录迁移均需等待相应阶段确认。
