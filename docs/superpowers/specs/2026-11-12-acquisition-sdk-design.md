# 采数 SDK 上下层拆分设计

状态：第二阶段修订设计已获用户确认（含 22 个实现及两项 utils 迁移）；第三阶段代表性编译/自测试验于2026-11-13完成，见[实测报告](../../sdk-stage3-result-2026-11-13.md)。正式业务迁移尚未开始。本稿取代此前将工具编译、配置迁移至 configs 的提案；尚未修改产品代码。

基线见 [第一阶段报告](../../sdk-stage1-baseline-2026-11-12.md)，提交 `6a9b102bc1fa23253fea2e1c09e6cd1a6bcc8799`。第一阶段范围统计保留为历史记录；本稿为最新设计范围。

## 1. 用户已明确的范围

- 仅在原 PRIVATE_PACKAGES = (lidar, plc, dataprocess, formats, pointcloud) 内选择闭源实现，不能因实现方便扩大到其他目录。
- GunDistributor.py 和整个 gun_distributors 为开放例外，含基类、默认实现和所有项目规则。
- MovingFrameData.py 为开放例外；PLC 报文因项目而异，必须能修改源码而不用重新编译 SDK。
- model/utils 默认公开；按用户后续补充，仅供底层使用的工具，或自身依赖待编译底层的工具，也可搬入相应私有包编译。目前确定 PointsFileUtil.py 与 FrameQueueManager.py 两项，其他工具保持公开，不复制进 SDK。control、view、motionplan、runtime、telemetry 和其余原本公开代码继续公开可直接使用。
- 保留 model/tomls/ 及其中十份 TOML，内容、编码、默认路径不变。不新增 configs/；目录名没有影响编译的技术含义，不能为了命名偏好迁移。
- 保留所有三种采数策略、开发运行方式与现有业务逻辑。一阶段一确认。

“一个接口”是固定 acquisition_sdk 导入入口及其支持集合，不代表整个应用只交付一个文件。SDK 需要与公开 model/utils、model/MovingFrameData.py、配置及第三方依赖配套使用，这些可见源码是本方案明确保留的扩展部分。

## 2. 方案及取舍

| 方案 | 结果 |
| --- | --- |
| 编译五包内私有实现及两项确认的工具，运行时引用其余开放工具和报文 | 符合最新要求；推荐。SDK 有明确公开源码依赖，不声称可单文件脱离这些依赖运行 |
| 连同共用工具和项目报文一起编译 | 被用户排除，不再采用 |
| 把开放工具复制进 SDK，同时保留原源码 | 会出现修改无效、双份状态和版本分叉，不采用 |
| 独立服务或原生 DLL 重写 | 用户主要通过 Python 调用且要求保留逻辑，本轮不采用 |

采用固定 SDK 门面导出现有对象，上层保持现有编排。目录、导入和构建变更允许；算法、业务条件、状态机、异常处理方式、队列协议和现有报文值不擅改。需要超出这些范围时先报告并单独确认。

## 3. 开放与闭源清单

| 原位置 | 闭源实现数（不含 __init__.py） | 开放例外 |
| --- | ---: | --- |
| model/lidar | 4 | 无 |
| model/plc | 2 | MovingFrameData.py 移到 model 根目录公开；仅 PlcCommon.py 和 PlcFrame.py 编译 |
| model/dataprocess | 7 | GunDistributor.py + gun_distributors 10 个实现全部公开 |
| model/formats | 4 | 原 3 个实现，加入 FrameQueueManager；数据类型和队列类通过 SDK 公开可调用 |
| model/pointcloud | 5 | 原 4 个实现，加入 PointsFileUtil |
| 其余目录 | 0 | 全部保持开放源码 |

总计 20 个原私有实现加 2 个确认迁入的工具，共 22 个实现进入 SDK。SDK 新增门面和包初始化胶水另计；不得把其余 model/utils、MovingFrameData 或分枪文件跟随编译进核心。

开发布局建议：

```text
acquisition_sdk/                 # 自有开发源码；发布时不交付此目录
    __init__.py                  # 固定入口、版本及延迟导出
    __init__.pyi
    _internal/
        lidar/                   # 4 个实现
        plc/                     # 2 个通用实现，无 MovingFrameData.py
        dataprocess/             # 7 个实现，无分枪实现
        formats/                 # 原 3 个实现 + FrameQueueManager.py
        pointcloud/              # 原 4 个实现 + PointsFileUtil.py
model/
    MovingFrameData.py           # 开放：项目报文定义
    gun_distributors/            # 开放：GunDistributor.py + 10 个实现
    utils/                       # 除上述两项迁出外，其余全部开放，保留原目录
    tomls/                       # 10 份 TOML，路径和内容不变
    motionplan/                  # 开放
    runtime/                     # 开放
    telemetry/                   # 开放
control/                        # 开放
view/                           # 开放
main.py                         # 开放，保留当前开发设置
```

发布时以 acquisition_sdk.cp311-win_amd64.pyd 和 acquisition_sdk.pyi 代替 SDK 源码目录，其他开放代码和配置照常交付。不需要原五个底层目录，不在其中保留兼容 .py 或静默源码回退。第三方原生依赖仍需单独交付。

开放分枪的原计算体、类名、分发条件和惰性创建行为不变；只集中目录并调整导入。新增规则和项目分发选择仍直接在开放源码中编写，不新增插件注册系统。

## 4. SDK 功能接口

支持对象直接重导出原类/函数，不新增 Engine 状态机，不套代理、不复制 dataclass、不通过 JSON 改写队列对象。

| 顶层公开名称 | 原实现与保持要求 |
| --- | --- |
| LidarAcquisitionProcess | 原采数进程；构造、Process 行为、队列、心跳及可设置属性保持 |
| PlcManager | PlcCommon 中原管理器；config_path、get_plc、通信行为保持 |
| DataFilter / DataSplitting | 原公开方法、名称大小写、参数、默认值与返回值保持 |
| DataFindBlocks | 原构造、配置读取路径和处理方法保持；本轮不新增 config_dir 行为 |
| build_side_frame | 参数、缓存及返回结构保持 |
| BeamDetector / BeamResult | 原构造、find_for_machine/find_for_side/find_beams 保持 |
| FrameQueueManager | 原 utils/FrameQueueManager.py；移入 formats，构造、三策略队列行为及开放层调用方式保持 |
| PointCloudSaveService | 原构造、from_config_file、start、poll_status、drain_and_close、abort 和运行属性保持 |
| PointCloudFileProcess / resolve_txt_files | 原参数、文件顺序及工作进程行为保持 |
| stop_pipeline | 原参数、超时、错误列表和释放顺序保持 |

高级资源接口：PointCloudSaveProcess、PointCloudSaveBuffer、SharedPointCloudPool、SaveBufferFull、read_blocks。内部策略、驱动和分区实现不自动成为支持接口；自有实现测试可以访问 _internal，上层生产代码只使用支持集合。

## 5. 数据类型与开放 PLC 报文

### 5.1 SDK 公开的数据与编码基础

| 顶层名称 | 原对象 |
| --- | --- |
| FrameAxisData / AxisFrameData | formats.frame_by_frame.AxisFrameDataFormat 中 AxisData / AxisFrameData |
| BlockData / JigData / OutsideData / InsideData / SubInsideData | BlockDataFormat 中同名类型 |
| DistribeGunData / GunGroupData / SingleMachineData | BlockDataFormat 中同名分枪结果类型 |
| PartitionData / MergePartitionData / LateralData | FrameDataFormat 中同名类型 |
| PlcFrame / WireType / Int16 / UInt16 / Int32 / UInt32 / Float32 / FixedStr / Repeat | 原 PlcFrame.py 的通用序列化基类及字段标记 |

保留字段拼写、顺序、默认值、可变性、列表/None、相等、deepcopy、isinstance 和嵌套行为。FrameAxisData 只是原类型的公开别名，不合并数据类型。SDK 内生成的 BlockData 与顶层导出的类型必须是同一个类对象。

### 5.2 项目报文保持源码

原 model/plc/MovingFrameData.py 搬到 model/MovingFrameData.py，不编译、不藏入 SDK。AxisData、SendMovingFrameData、ReceiveMovingFrameData、create_axis_list 仍在这个开放文件中。上层直接使用：

```python
from model.MovingFrameData import AxisData, SendMovingFrameData, ReceiveMovingFrameData
from acquisition_sdk import PlcFrame, Int16, Int32, Repeat
```

第二行用于开放报文文件定义自己的 dataclass；并非每个上层调用点都需要导入这些基础标记。报文字段、顺序、重复数量、FRAME_SIZE 和字节序由开放报文定义。SDK 不保存另一个固定的收发帧副本，也不再顶层导出一套 PlcAxisData/SendMovingFrameData 别名。

通用编解码器必须支持开放 dataclass 子类，并能通过 get_type_hints/Annotated 正确读取开放类的类型注解，第三阶段用真实编译基类验证。

现有 START、END、ReadCommon 位于 PlcCommon.py，属于项目报文外框/请求命令。提案将这三个常量以原名称和原字节值移到开放 MovingFrameData.py，PlcCommon 导入它们；不改变拼包、解包或请求流程。这样后续字段、帧头尾、读命令的项目差异不会因常量被闭源而卡住。涉及完全不同的握手或传输流程不能仅靠修改 dataclass 自动适配，需要修改对应开放编排或另行设计，不在本轮重写协议。

当前项目依然按原 20 轴、134 字节和原字节序验证；不会借本次迁移修改现场报文。其他项目修改报文后，若开放控制/运动代码读取的字段或轴含义也变化，需同步修改这些开放代码；SDK 不推断业务字段含义。

## 6. utils 逐项审计与两项迁移

此前计划的九个工具一并编译方案仍撤销。按用户最新补充，两个符合条件的文件单独纳入打包：

| 文件 | 仓库生产调用/依赖证据 | 归属 |
| --- | --- | --- |
| PointsFileUtil.py / manage_points_files | 仅 PointCloudSaveProcess.py 的 run 导入并调用；清理点云保留文件 | 迁入 pointcloud/PointsFileUtil.py，随 SDK 编译 |
| FrameQueueManager.py / FrameQueueManager | 直接依赖 formats.frame_by_frame 的 AxisFrameData/AxisData；由开放 PlcCommunicationProcess 创建，运动规划使用其队列及方法 | 迁入 formats/FrameQueueManager.py，随 SDK 编译，并顶层导出 FrameQueueManager |

FrameQueueManager 不是“只有五包调用”的工具。按用户新增的“utils 自身调用底层也可打包”规则纳入，不能错误归类其调用者。原构造和所有公开方法、frame_stack、queues、active_directions、stack_size 等现有属性保持，不把队列隐藏成新的协议；开放 PLC/运动代码仍可正常使用。

迁移只更改位置和 import；PointsFileUtil 的保留清理逻辑、FrameQueueManager 三策略 FIFO/整件队列/三工位状态机的所有计算体保持原样。源码结构调整阶段直接迁入 SDK 的 _internal/pointcloud 和 _internal/formats，不在仓库中保留两份实现。

TomlLoader、LoggerUtil、ProcessHeartbeat、StrategyUtil、MachineConfigUtil、LidarDirectionUtil、WorkpieceOriginUtil、UiTelemetry 继续保留原 model/utils 路径、实现、状态和导入方式；其余开放工具同样保留。完整分类和函数级例外见 [utils 调用审计](../../sdk-utils-scope-2026-11-12.md)。

SDK 仍直接运行时 import 上述其余开放工具，用户可以查看和修改；修改生效需要重启进程，无需重编 SDK。公开工具版本需要与 SDK 的调用约定兼容。不能为消除依赖而把其代码复制进 SDK 或改成 SDK 代理。

底层对公开目录的依赖白名单：

- 原有 9 项中除已迁入的 PointsFileUtil 之外，剩余 8 个 model.utils 工具模块；
- model.MovingFrameData 项目报文模块。

不得主动依赖 control、view、motionplan 或开放分枪规则。公开模块内部可能有正常的 SDK 使用，这不等同于允许 SDK 编译整个 model 包。

### FrameQueueManager 的上层导入适配

FrameQueueManager 移入 SDK 后，内部直接使用同一私有包的帧类型；开放 PlcCommunicationProcess 的旧 utils 导入改为：

```python
from acquisition_sdk import FrameQueueManager
```

相应测试的导入和 patch 路径按实际迁移适配，不修改其业务断言。其余留在 utils 中的工具不需要为了这次搬迁引用原 formats 路径；本轮没有发现其他 utils 文件显式 import 五包底层类型。

### 冷导入与循环依赖

`import acquisition_sdk` 或版本查询不导入 LoggerUtil、Open3D，不创建日志、队列、共享内存、设备连接或工作进程。纯数据类型和通用 PlcFrame 标记的导入也不应创建这些资源。

门面通过延迟导出提供对象。开放 MovingFrameData 导入 SDK 的 PlcFrame/标记时，只加载无设备依赖的 PlcFrame 模块，不加载 PlcCommon。调用方稍后获取 PlcManager 才加载 PlcCommon，后者从开放 MovingFrameData 获取已定义的接收帧与协议常量。这条导入链必须做双向顺序和冷启动验证，不能靠随意重写 __module__ 或 sys.modules 注入绕过。

SDK 不 chdir、不设置全局多进程方式、不启动 Qt。调用会导入现有 LoggerUtil 的功能时保留原日志初始化语义；原 prepare_environment 仍在开放应用入口先执行。

## 7. 配置与运行路径保持现状

不改名、不搬迁 model/tomls，不新增 SDK 路径工具，不批量重写留在 utils 的工具或 UI 配置读取。main.py 当前 CONTROL_TYPE=1 和策略配置均保留。

保留当前 cwd/model/tomls 的使用方式和应用 prepare_environment 行为。SDK 调用方要按既有项目约定提供开放 model 包、配置和工作目录；本轮不承诺任意配置目录能在所有路径完整传播，也不顺便修复基线中部分模块忽略外部 config_dir 的现象。

原本有 config_dir/config_path 的接口继续保留，原本写死项目默认路径的读取也不擅改。若后续确实需要完整支持外部配置目录，单列需求再确认，避免封装与配置行为修复混杂。

点云输出仍由 PointCloudSaveService 原 output_dir 参数决定，应用默认 app/data/points；日志仍按原语义写 cwd/data/logs。报告不输出实际密码和完整现场配置值。

## 8. 三策略与开放层协作

保留 Qt -> ControlCenter -> PipelineRuntime -> 原工作进程。开放 PipelineRuntime 创建队列、心跳和资源清单；SDK 提供既有进程/服务/算法/通用编解码和格式类型；项目报文、工具、分枪和运动在开放层。

| 策略 | 保持的流程与差异 |
| --- | --- |
| 1 / frame_by_frame | SDK 逐帧采集、建帧 -> 开放队列/PLC/运动；相对 Z 保存，保存待完成不阻塞逐帧交付 |
| 2 / complete_workpiece | SDK 整件采数 -> 开放 DataProcessingProcess 调 SDK DataFindBlocks -> BlockData -> 开放分枪/运动 -> 开放报文定义 + SDK 通用通信；相对 Z 保存，处理侧线框预览优先 |
| 3 / continuous_bidirectional | 开放扫描/运动与 SDK 采数策略按原状态协作；有效整趟交付，绝对 Z 和 Z/Y/X 排序，中断无效趟丢弃；不擅自补激光轴映射 |

自动实时路径进程数仍为 3/4/3；TXT 联调策略 1/2 为 2/3，策略 3 保留原拒绝；只看 TXT 为 1，不启动设备/保存链路。人工启动条件、消息字段、FIFO、连接代次、心跳、联锁、异常重连、保存 ACK 与停止顺序均保持。

## 9. 构建与版本

固定 acquisition_sdk 模块名，首版 `__version__ = "0.1.0"`，`SDK_API_VERSION = 1`。版本号写到发布 zip/wheel 和 manifest，不给 .pyd 基名加 _v0_1。兼容修复/新增保持旧调用，破坏兼容的变更需说明并更新接口代次。

优先验证本机 Nuitka 2.5.9 与 CPython 3.11 Windows AMD64。包编译只显式纳入 acquisition_sdk 下的私有实现；对整个 model 命名空间禁用跟随编译，开放工具、报文、运动和分枪须保持运行时外部依赖。实际选项、延迟导出和 spawn 可行性以第三阶段试验为准。

不能继续无条件递归原五包：必须排除 MovingFrameData.py 和所有分枪文件，并确认两项工具已迁入对应私有目录。当前旧 build_extensions.py 的根路径问题在构建阶段处理，不改变业务函数。

发布采用正向清单：核心 .pyd/.pyi、全部开放源码、原 model/tomls 配置、运行依赖和版本说明。排除私有源码、生成 C、调试文件、缓存、内部测试和基线证据。不把“原五包路径消失”误写成“公开 model 包也被删除”。

新增声明文件覆盖 SDK 支持对象、现有类方法/运行属性和数据字段，不以空类或全 Any 交付。MovingFrameData 和 utils 继续依靠自己的可见源码提供说明与补全。

升级先退出应用和全部工作进程，再备份/替换同名 .pyd 及匹配声明、确认公开依赖接口兼容后重启，不热替换加载中的扩展，不覆盖用户修改的开放源码和现场配置。

## 10. 验证与完成标准

对改造前源码、拆分后源码和编译发布产物使用相同配置及输入做差分。布局断言可依据新设计更新，业务断言不得放宽。

1. 三策略 × 两种数据原点：坐标、消息/连接代次、dtype、形状、特征字段、None/空值、FIFO、保存排序/精度一致。Open3D 随机性需固定可复现输入与种子并记录限制，不能用宽容差掩盖未知偏差。
2. 真实 spawn：往返逐帧类型、嵌套 BlockData 和开放 model.MovingFrameData 类型；检查 pickle、deepcopy、类型身份、队列返回和退出码。只保留发布文件，不靠私有源码目录运行。
3. 真实保存进程：块不覆盖、ACK、错误上报、停止封存排空、.part/.complete.json、TXT/NPY 精度；不以 mock start 代替编译后运行。
4. 目录/配置：model/tomls 和十份 TOML 字节不变，剩余公开 utils 仍为原路径源码；两个迁移工具除 import/模块位置适配外逻辑不变。其他 cwd 通过原应用入口启动的行为保持。
5. 开放报文扩展：保持同一个 .pyd，复制交付包到隔离目录，仅改开放报文的测试 dataclass、字段组合和帧常量，验证通用编码/解码与 fake socket 收发，不连接设备；不能把真实现场报文改掉。
6. 开放工具扩展：保持同一个 .pyd，只在测试交付副本中修改一个公开工具的可控结果，冷启动/子进程能观察到变化，证明没有隐式编译或私有副本。
7. 开放分枪/运动：相同特征与设备参数对比迁移前后所有结果字段；临时新增分枪和修改运动实现，无需重编 SDK。
8. 冷导入和双向导入顺序：先开放报文再 SDK PlcManager、先 SDK 再报文，都无循环初始化失败；版本/类型导入不产生运行资源；没有 sys.modules 伪装或旧五包源码回退。
9. 支持的 CONTROL_TYPE 组合、拒绝条件、进程数、人工启动及保存/停止语义不变。
10. 发布与构建清单验证：22 个实现候选及 SDK 胶水进入核心；MovingFrameData、其余 utils、control/view/motionplan/分枪都未进入核心；原五个底层文件目录不需要交付。三种 FrameQueueManager 路径均做原输入对比，开放层真实调用 SDK 类，不能仅以导入成功验收。

基线 273 项：265 通过、6 失败、2 错误。布局/构建问题按新布局适配；第三策略 5 项业务断言与旧字段错误保留记录、独立诊断，不为绿灯删除断言。未解决时报告明确保留已知业务问题，不称三策略全部实机验收通过。

没有硬件或代表性整件样本的路径列入待验收。封装完成不代表补齐现有第三策略轴适配，也不保证未知协议的业务语义自动适配。

## 11. 后续阶段与确认点

- 第二阶段：确认修订范围、公开报文及帧常量、两项 utils 按上述规则迁移编译、配置不迁移。
- 第三阶段：细化试验计划确认后，在隔离环境验证单包 .pyd、外部公开依赖不被编译、开放报文继承/反射、延迟导出和真实 spawn。此时不迁移产品算法。
- 第四阶段：试验通过并确认后，编写正式实施计划，补差分与接口验证，迁移私有实现、开放报文和分枪、调整上层 import。
- 第五阶段：改为验证原路径/公开依赖保持和脱离原五包目录运行，不实施此前已撤销的配置路径迁移。
- 第六阶段：版本化发布包、.pyi、使用说明及 manifest。
- 第七阶段：干净目录回归、开放扩展验证、代码审查和实机待验收清单。

每阶段交付结果并等待确认。内部导出写法、脚本文件名、测试文件组织交给实施者；不得改变已明确的开放范围与业务语义。

## 12. 审阅记录

先前独立审阅已确认开放依赖、报文/编译基类导入顺序和外部修改生效的设计。用户最新两项工具迁移补充亦已独立复核，结论为 `nothing important left`：22 个实现范围一致，队列管理器的三策略及公开运行属性保留明确，未引入新的设计依赖问题。编译后的继承/注解反射、外部依赖排除、三策略队列管理及 spawn 仍待后续实测。

本次仅修订文档，未移动文件、改工具或报文、改配置、编译或安装依赖。

再次核对 181 个源码、测试与配置文件 SHA-256，与第一阶段基线一致。
