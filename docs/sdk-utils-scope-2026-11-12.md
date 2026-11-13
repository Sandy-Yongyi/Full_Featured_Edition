# utils 调用与打包范围审计

日期：2026-11-12。仅审计与设计更新，尚未迁移实现或编译。本清单补充 [SDK 设计](superpowers/specs/2026-11-12-acquisition-sdk-design.md)。

检查 model、control、view、main、构建脚本及 tests 中显式导入和函数/属性引用，排除 lib、output 和构建缓存。测试调用单独看待，不把“被测试调用”当作必须开放。分枪和 MovingFrameData 按用户已确认范围视为开放。

## 结论

1. PointsFileUtil.py 是可整体迁移的纯底层工具：manage_points_files 只有点云保存进程调用，迁入 pointcloud。
2. FrameQueueManager.py 并非只有底层调用；它由开放 PLC 进程创建、供开放运动规划使用。但它自身依赖待编译的 formats 帧类型，按用户后续允许的规则迁入 formats，SDK 导出原类供上层使用。
3. 其余 utils 不符合当前整体迁移条件，继续开放。不会为单个函数的直接调用分布而拆散共用文件、复制工具实现或改变算法。

## 全部文件分类

| 文件 | 生产调用/依赖 | 建议 |
| --- | --- | --- |
| PointsFileUtil.py | PointCloudSaveProcess.run 调用 manage_points_files；没有发现其他生产调用 | 整文件迁入 pointcloud，编译 |
| FrameQueueManager.py | control/PlcCommunicationProcess 创建；开放 motionplan 使用实例；自身 import formats 帧类型 | 整文件迁入 formats，编译并导出类 |
| TomlLoader.py | 五包、分枪、control、motionplan、配置/授权工具、main、部署检查共用 | 保留开放 |
| LoggerUtil.py | 底层、control、运动规划和工具共用；有日志器共享状态 | 保留开放，不做私有副本 |
| StrategyUtil.py | 采数策略与进程、开放 control、队列/配置工具共用 | 保留开放 |
| MachineConfigUtil.py | DataFindBlocks、开放分枪、control、MachineConfiguration、FrameSearchHelper 共用 | 保留开放 |
| LidarDirectionUtil.py | 采数进程、PipelineRuntime、DataProcessWorker、FrameQueueManager 共用 | 保留开放 |
| ProcessHeartbeat.py | 采数/保存/回放进程以及开放 PLC/处理/联调进程共用 | 保留开放 |
| UiTelemetry.py | SDK 采数/回放和开放 PLC/PipelineRuntime 共用 | 保留开放 |
| WorkpieceOriginUtil.py | SDK 点云处理预览、开放处理/联调进程及运动规划共用 | 保留开放 |
| ConfigurationService.py | PipelineRuntime 与配置/界面相关功能使用，无待编译底层 import | 保留开放 |
| MachineConfiguration.py | 开放设备配置读写/下发功能，无待编译底层 import | 保留开放 |
| PasswordConfig.py | ConfigurationService 等开放授权/配置功能使用 | 保留开放 |
| UiTaskFeedback.py | 开放 PLC 任务反馈功能使用 | 保留开放 |
| ConfigLoader.py | JSON ConfigLoader 类；未发现仓库生产调用，也没有五包 import | 保留现状；无调用不等于只由底层调用，不据此移动或删除 |

__init__.py 不含这类功能，保留为包初始化文件。

## 函数级判断需要考虑间接调用

- manage_points_files：仅保存进程调用，所在文件没有其他共享功能，适合整体移动。
- filter_active_direction_map：虽然外部直接调用只出现在采数进程，但开放的 get_active_lidar_config 也在同文件中调用它；后者由 PipelineRuntime、DataProcessWorker 和 FrameQueueManager 使用。不能将其认定为底层专用。
- normalize_lidar_ids/get_direction_lidar_config：作为上述开放方向选择入口的内部步骤，同样是共用功能。
- normalize_offset_value：DataFindBlocks 直接引用，但开放 normalize_machine_offset_values/get_machine_offset 等也调用它，不能按直接 import 统计就迁走。
- normalize_origin_side：被 get_origin_side 调用，后者用于开放流程；继续开放。
- transform_block_data_for_origin：仅发现定义，没有发现生产调用；不把无调用函数算作底层专用，也不趁本次清理删除。
- 只在某个共享类/文件内部调用的私有方法按整个文件归属，不因缺少外部调用就拆出闭源。

## FrameQueueManager 的具体证据与保留要求

- model/utils/FrameQueueManager.py 第 7 行导入 AxisFrameData 和 AxisData，来源为待打包的 model.formats。
- control/PlcCommunicationProcess.py 导入并在 _create_frame_queue_manager 创建实例，调用 push_frame、put_continuous_workpiece、push_workpiece、shift_queue、clear 等。
- MotionContinuousBidirectionalPlanning 使用 update_continuous_stations、continuous_slot_empty；其他规划和 helper 使用 frame_stack/queues。
- 这些调用都继续支持，SDK 顶层导出 FrameQueueManager，开放 PLC 只调整 import。
- 逐帧 FIFO、完整工件按方向/设备队列、第三策略三工位搬移和放行状态均保留。不能因名称中有 formats 就只移动数据字段、丢掉其管理行为。

## 实施时的路径

- 原 PointsFileUtil.py 的最终私有开发位置：acquisition_sdk/_internal/pointcloud/PointsFileUtil.py。
- 原 FrameQueueManager.py 的最终私有开发位置：acquisition_sdk/_internal/formats/FrameQueueManager.py。
- 若以原五包结构做迁移过渡，对应为 model/pointcloud 和 model/formats；不保留两份实现，最终发布不交付私有源目录。
- PointsFileUtil 内 logger 仍来自开放 model.utils.LoggerUtil。
- FrameQueueManager 内帧类型改为 SDK 私有 formats 的同一个类型；LoggerUtil、StrategyUtil、TomlLoader、LidarDirectionUtil 仍引用开放 utils。

静态检索无法证明仓库外的调用者或任意动态字符串加载不存在；本清单结论限定于本项目已检查的源文件。实施时需要按既有测试和三策略差分验证移动前后行为，不以静态统计代替运行验证。
