# 激光仿形自动喷涂系统

基于 PyQt6 的控制中心，负责激光采集、点云处理、运动规划、PLC 通讯与点云保存。根目录唯一 Python 启动文件为 `main.py`。

## 快速开始

在项目根目录执行，使用安装了项目依赖的 Python 3.11：

```powershell
python -m pip install -r requirements.txt
python main.py
```

常用命令：

| 用途 | 命令 |
| --- | --- |
| 正常启动 | `python main.py` |
| 空场界面预览，不启动硬件进程 | `python -m model.runtime.qt_preview` |
| 只读部署自检，不启动界面和硬件进程 | `python main.py --check-deployment` |
| 编译私有模块为扩展 | `python -m model.build_extensions build_ext --inplace` |
| 全量自动测试 | `python -m unittest discover -s tests -v` |
| 点云保存专项测试 | `python tests/run_saving_tests.py` |
| 代码规范检查，需安装 flake8 | `python -m flake8` |

源码启动会先定位项目根目录，再加载 `model/tomls`。冻结应用使用可执行文件所在目录。文件位置和工作目录的处理位于 `model/runtime/app_bootstrap.py`。

## 开发运行方式与采集策略

两者是不同的设置：`CONTROL_TYPE` 决定数据来源和调试方式，`strategy_name` 决定采数、处理及运动规划策略。

在 `main.py` 顶部设置开发运行方式，下面的路径仅为示例：

```python
CONTROL_TYPE = 2  # 1=TXT显示并联调PLC，2=实时采数与运动，3=只导入TXT画图
DATA_PATH = r"D:\draw_points\sample"
DATA_NAME = None
```

| CONTROL_TYPE | 行为 |
| --- | --- |
| 1 | 从 TXT 回放数据，显示点云并联调 PLC；目前支持策略 1、2 |
| 2 | 实时采集和运动；正常交付使用此方式 |
| 3 | 只导入 TXT 查看点云，设备配置只读，不启用 PLC、激光和保存进程 |

三种方式均等待人工点击界面启动按钮；方式 3 需点击“导入 TXT 点云”，启动软件不会自动导入。

方式 1、3 使用 `DATA_PATH` 和 `DATA_NAME`。方式 1 的目录回放中，`DATA_NAME=None` 时按自然文件名顺序处理数据集；指定名称时只处理对应数据集。同原点与独立原点的组织规则沿用 `ReadDataConfig.toml`，独立原点数据使用 `left_`、`right_` 等方向前缀。

采集策略由 `model/tomls/ModeConfig.toml` 的整数配置选择，修改后重启：

```toml
strategy_name = 1
```

| strategy_name | 内部名称 | 工作方式 | 设备配置文件 |
| --- | --- | --- | --- |
| 1 | `frame_by_frame` | 按 FIFO 逐帧采集、建帧并交给 PLC | `MachineConfig1.toml` |
| 2 | `complete_workpiece` | 采完整件点云，提取框体与挂具等特征，再进入分枪及运动规划 | `MachineConfig2.toml` |
| 3 | `continuous_bidirectional` | 连续往复采集，按整趟点云和工位状态处理 | `MachineConfig3.toml` |

TOML 中填写整数 `1/2/3`，内部模块之间使用策略名称字符串。更详细的开发入口和 TXT 规则见 [开发运行方式](docs/qt-developer-modes.md)。

## 当前界面

左侧保留“实时控制、设备控制、设备配置”三个页面。现有页面每秒接收一次状态更新，切页不暂停点云预览数据处理；PLC 收发和激光采集周期由工作进程管理，不随界面刷新改成一秒一次。

- **实时控制**：点云、启动/停止、任务摘要、设备联锁和最近 print 事件。链条运动速度来自 PLC 的 `ChainSpeed`，按 `mm/s × 0.06` 转成 `m/min`。仅完整工件策略显示“外框、内框、挂具”图层选项。
- **设备控制**：总使能位于左上，六台设备分左右两列排列。总使能关闭时设备按钮不可点击，并清空界面设备开启请求；PLC 未连接或停止中禁止控制。按钮绿色表示界面开启请求；关闭后立即取消绿色并关枪，设备报文位仍持续为 1，直到所有轴回安全位置才清零。总使能关闭时同样保留返回所需的使能直到返回完成；发包层不再覆盖策略规划结果。
- **设备配置**：按当前策略读取对应 TOML，通过同名设备按钮选择参数，选中设备高亮并显示设备参数标题。参数直接编辑，启用密码时仅在保存时验证。参数区保留滚动条。

点云默认从负 X 方向观察，Z 水平、Y 竖直，网格位于 X–Z 平面；点云按 X 值使用冷色渐变。完整工件的外框为绿色、内框为红色、挂具为亮黄色。界面采用 125% 的字体与控件尺寸设置，三维点大小和相机缩放不因该设置改变。

## 目录结构与职责

```text
main.py                              # 正式入口、开发方式设置、单实例保护
control/                             # 开放的控制代码
├─ ControlCenter.py                   # 启停、控制命令、运行状态
├─ PipelineRuntime.py                 # 创建与管理进程、队列、共享内存
├─ PlcCommunicationProcess.py         # PLC 收发、调用运动规划
├─ DataProcessWorker.py               # TXT 回放与 PLC 联调
└─ DataProcessingProcess.py           # 完整工件处理进程，调用私有算法
model/
├─ runtime/                          # 运行与启动辅助
│  ├─ ProcessHealthMonitor.py
│  ├─ ShutdownCoordinator.py
│  ├─ app_bootstrap.py
│  ├─ qt_main.py
│  ├─ qt_preview.py
│  └─ deployment_check.py
├─ telemetry/                        # 公共状态与队列收集，不依赖 Qt
│  ├─ UiState.py
│  └─ RuntimeStateCollector.py
├─ pointcloud/                       # TXT 导入、共享内存与保存
│  ├─ PointCloudFileProcess.py
│  ├─ PointCloudSaveProcess.py
│  ├─ PointCloudSaveBuffer.py
│  └─ PointCloudSaveService.py
├─ lidar/                            # 采数进程、策略与激光驱动
├─ dataprocess/                      # 点云算法、特征提取、分区与分枪
├─ plc/                              # 报文定义、序列化及底层通信
├─ motionplan/                       # 开放的运动规划与轴映射
├─ formats/                          # 算法与规划共用的数据结构
├─ tomls/                            # 开放配置
└─ utils/                            # 配置及公共工具
   ├─ ConfigurationService.py
   └─ MachineConfiguration.py
view/qt/                             # Qt 界面、授权和 OpenGL 点云视图
├─ QtUiBridge.py                     # 一秒一次的 Qt 状态桥接
├─ MachineConfigSchema.py            # 参数名称及显示顺序
├─ main_window.py
└─ pages.py
```

旧 `model/plot` 已删除，当前绘图使用 `view/qt/point_cloud_view.py`。旧根目录的 `qt_main.py`、`qt_preview.py`、`app_bootstrap.py`、`deployment_check.py` 已迁入 `model/runtime`，不再保留同名根目录兼容文件。

调用关系为：Qt 界面 → `ControlCenter` → `PipelineRuntime` → 工作进程；工作进程通过状态队列和公共状态结构向界面反馈。参数显示规则放在 `view/qt`，参数读写和范围校验放在 `model/utils`。详见 [模块目录说明](docs/module-layout.md)。

## 进程与通信

下表列出常用自动运行路径。数量不含 Qt 主进程，`CONTROL_TYPE=2` 按 `spray_mode=0` 的自动采集路径统计。

| 运行方式 | 工作进程 | 数量 |
| --- | --- | --- |
| 实时采集，策略 1、3 | 激光采集 + PLC + 点云保存 | 3 |
| 实时采集，策略 2 | 激光采集 + 点云处理 + PLC + 点云保存 | 4 |
| TXT 联调，策略 1 | TXT 回放 + PLC | 2 |
| TXT 联调，策略 2 | TXT 回放 + 点云处理 + PLC | 3 |
| 只看 TXT 点云 | TXT 导入 | 1 |

`PipelineRuntime` 负责创建资源和工作进程。主入口使用 Windows `spawn` 并调用 `freeze_support()`；不要在模块导入时直接启动子进程。

| 通道 | 用途 |
| --- | --- |
| `control_queue` | 界面控制、设备开关和配置更新发送给 PLC 进程 |
| `pulse_queue` | PLC 脉冲、FIFO 和链条运动状态发给采数/回放进程 |
| `raw_data_queue` | 逐帧结果或完整工件点云，消费者由策略决定 |
| `machine_data_queue` | 策略 2 的处理结果发给 PLC 进程 |
| `viz_queue` | 点云和框体预览；容量为 2，界面端合并读取最新预览 |
| `ui_status_queue` | 设备通讯状态、链速、软件使能位与任务摘要 |
| `log_queue` | 子进程 print/stderr 收集；最近事件仅显示 print |
| 共享点云池 + 保存任务/ACK 队列 | 大点云保存、块描述传递及完成回收 |

**当前完整工件采数 → 数据处理仍使用普通队列传数组。** 保存链路的共享内存尚未复用于处理链路；不要把“保存使用共享内存”理解为所有点云传输都已零拷贝。

## 点云保存

保存进程独立于采数与 PLC，父进程创建共享内存池，采数进程写点云块，通过任务队列提交块描述。保存成功后返回 ACK，再回收对应块。

| ReadDataConfig.toml 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `point_cloud_save_block_mb` | 16 | 每块内存大小，MiB |
| `point_cloud_save_block_count` | 32 | 块数量，总池约 512 MiB |
| `point_cloud_save_format` | `txt` | 支持 `txt` / `npy` |
| `point_cloud_preview_voxel_mm` | 10 | 预览体素尺寸，0 不降采样 |
| `point_cloud_acquisition_stop_timeout_s` | 15 | 整数秒，等待采数封存退出 |
| `point_cloud_save_shutdown_timeout_s` | 120 | 整数秒，等待保存排空 |

池内使用 float64 XYZ，每点 24 字节；方向点云与 combined 分别占空间。缓冲耗尽会报错，不覆盖仍待保存的数据。

策略 1、2 的保存点云执行相对 Z 回绕修正并归零；策略 3 保留绝对 Z，按 Z/Y/X 排序。先写 `.part`，成功后改名，并生成 `.complete.json` 工件清单。清单中的 `incomplete` 表示未完整采集。关闭时先结束采数，再排空保存任务并清理共享资源。

预览降采样不降低保存点数。完整工件 `draw_type=2` 时由处理进程提供框体预览，保存进程不覆盖它。右原点转换用于预览对齐，源 TXT 不被修改。

## 配置文件

配置均位于 `model/tomls`，修改采集策略、设备布局等配置后重启软件。

| 文件 | 作用 |
| --- | --- |
| `ModeConfig.toml` | `strategy_name`、运行工艺模式及密码配置 |
| `SystemConfig.toml` | 左/右及上侧激光分组 |
| `LidarConfig.toml` | 激光地址、安装方向、扫描角及坐标偏移 |
| `PlcConfig.toml` | PLC 网络与连接参数 |
| `ReadDataConfig.toml` | 点云过滤、原点、脉冲换算、FIFO、超时和保存参数 |
| `ProcessConfig.toml` | 特征提取、挂具识别及分区参数 |
| `MachineConfig1.toml` | 策略 1 的设备参数 |
| `MachineConfig2.toml` | 策略 2 的设备参数及适用设备的平板参数 |
| `MachineConfig3.toml` | 策略 3 的设备参数 |
| `SprayConfig.toml` | 运动容差和喷涂参数范围 |

`translate_data_origin=1` 使用同原点，`2` 使用独立原点。`pulse_to_mm` 表示每毫米脉冲数。链条实际速度来自报文 `ChainSpeed`；配置 `lidar_scan_speed` 是扫描/回零速度配置，两者不能混用。

策略 1 的 SN 0～2 对应左侧内外顶、内外底、二维；SN 3～5 对应右侧三台设备。显示哪些参数由 `view/qt/MachineConfigSchema.py` 决定，保存沿用配置合并和参数范围校验，不删除未显示的配置项。

## PLC 报文字段

报文源码为 [MovingFrameData.py](model/plc/MovingFrameData.py)，序列化框架为 [PlcFrame.py](model/plc/PlcFrame.py)。当前使用大端序，20 组轴，每组 `Pos/Speed/Status` 均为 Int16。

发送字段顺序：

| 字段 | 类型 | 字节偏移 | 用途 |
| --- | --- | --- | --- |
| `Operate` | Int32 | 0 | bit0 总使能，bit1～6 左侧内外顶/内外底/二维、右侧内外顶/内外底/二维 |
| `Gun_cont1` | Int32 | 4 | 保留枪控字 |
| `Gun_cont2` | Int32 | 8 | 保留枪控字 |
| `HeartBeat` | Int16 | 12 | 心跳 |
| `Control` | Int16 | 14 | 远程控制字，bit1 链条运动；规划中还使用 bit15 表示缓存有数据 |
| `AxisList` | 20 × AxisData | 16 | 轴命令 |

接收字段顺序为 `ChainPulse(Int32)`、`ChainSpeed(Int32)`、`HeartBeat(Int16)`、`Status(Int16)`、`Operate(Int16)`、`AxisList[20]`。接收 `Operate` 与发送 `Operate` 是各自报文字段，不能只按名称推断用途。

当前发送字段实际序列化为 136 字节、接收为 134 字节，但两类的 `FRAME_SIZE` 常量目前均写为 134。发送端超长时会记录告警并发送实际载荷；此处需要与 PLC 协议核对后统一，README 不将其描述为已一致的固定长度。帧头、帧尾分别为四字节 `02` 和四字节 `03`。修改字段后同步核对字段类型、顺序、序列化长度及 PLC 端定义。

## 私有模块构建与团队交付

原根目录 `setup.py` 没有丢失：其构建职责已迁入 [model/build_extensions.py](model/build_extensions.py)，以满足根目录只保留 `main.py` 的目录约定。

在项目根目录执行：

```powershell
python -m model.build_extensions build_ext --inplace
```

构建脚本调用 setuptools/Cython，自动收集以下目录内除 `__init__.py` 外的 Python 模块：

```text
model/lidar
model/plc
model/dataprocess
model/formats
model/pointcloud
```

`control`、`view`、`model/motionplan`、公共工具与配置不在此扩展编译清单内。编译需要与目标 Python 和 Windows 架构匹配的 C/C++ 编译工具；该命令生成扩展模块，不生成整套软件的 EXE。

`build_ext --inplace` 不自动删除私有 `.py` 源码，也不自动筛选交付文件。对团队发布时需另外整理扩展、包初始化文件、依赖、开放源码及 TOML 配置，避免把私有源码一起交付。移动模块或修改报文后应重新编译，避免旧扩展覆盖同名新源码。

## 检查与已知事项

flake8 使用仓库 [.flake8](.flake8)：最大行长 180、最大复杂度 20；业务源码和测试参与检查，构建缓存、第三方依赖与生成产物排除。单行不超过 180 字符时尽量保持单行。类型检查应使用项目实际 Python 环境。

目录迁移后的验证覆盖跨工作目录入口、Windows 子进程、TXT 导入、保存及新模块构建清单。当前仍有第三策略激光轴映射与 20 轴报文不匹配、旧部署测试依赖已不存在配置字段的问题；自动测试、部署自检都不能替代设备联调和 EXE 验收。

更多说明：[模块目录](docs/module-layout.md)、[开发运行方式](docs/qt-developer-modes.md)、[部署检查与验收](docs/qt-deployment.md)。
