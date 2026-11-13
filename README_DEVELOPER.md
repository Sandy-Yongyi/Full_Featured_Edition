# 激光仿形喷涂系统：开发人员指南

本文随开发交付包提供，可独立阅读。底层采集和处理以 `acquisition_sdk` 二进制库交付，项目控制、界面、报文、运动规划及分枪规则提供 Python 源码。SDK版本通过 `acquisition_sdk.__version__` 查询，Python接口版本通过 `acquisition_sdk.SDK_API_VERSION` 查询。

## 1. 收到哪些文件

```text
项目根目录/
├─ README.md                            # 本开发指南
├─ main.py                              # 启动入口、数据来源选择
├─ requirements.txt                     # Python 依赖清单
├─ acquisition_sdk.cp311-win_amd64.pyd    # 私有底层：Windows x64 / CPython 3.11
├─ acquisition_sdk.pyi                  # IDE 补全、参数和数据类型声明
├─ control/                             # 开放：启停、进程、队列、PLC调度
├─ view/                                # 开放：Qt界面、参数展示、点云显示
└─ model/                               # 开放：项目业务和配置
   ├─ MovingFrameData.py                # 项目PLC收发报文和协议常量
   ├─ gun_distributors/                 # 分枪工厂、各类设备分枪规则
   ├─ motionplan/                       # 运动规划、轴映射、联锁辅助
   ├─ runtime/                          # 启动、自检、进程健康及停机
   ├─ telemetry/                        # 界面状态收集和数据结构
   ├─ utils/                            # 公共工具、配置读写和校验
   └─ tomls/                            # 十份TOML配置
```

运行时可能创建 `data/`，用于日志和点云，不必预先交付历史数据。文件哈希清单由维护方内部保存，不随开发ZIP交付，也不是程序运行依赖。

## 2. 环境与第一次启动

使用 **Windows x64、64位 CPython 3.11**。当前 `.pyd` 不适用于 Python 3.10/3.12、32位Python、Linux或其他架构。第三方依赖和原生运行库未封装进 `.pyd`。

在解压后的项目根目录打开 PowerShell：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -c "import acquisition_sdk as sdk; print(sdk.__version__, sdk.SDK_API_VERSION)"
.\.venv\Scripts\python.exe main.py --check-deployment
.\.venv\Scripts\python.exe -m model.runtime.qt_preview
```

`--check-deployment` 检查依赖、配置和Qt插件，不连接硬件、不启动工作进程；不验证设备参数与现场机械完全匹配。`qt_preview` 用于空场界面预览。准备好项目配置和现场条件后，再执行 `python main.py`。


## 3. 先分清两个“模式”

### 3.1 `main.py` 的开发运行方式

| 设置 | 行为 | 是否连接设备 |
| --- | --- | --- |
| `CONTROL_TYPE = 1` | TXT回放、显示并联调PLC；支持策略1按帧模式、2完整工件模式 | 会连接PLC，可能发控制指令，只是不实时进行采数 |
| `CONTROL_TYPE = 2` | 真实雷达采集和PLC运动流程 | 实时采数以及自动路径规划设备运动 |
| `CONTROL_TYPE = 3` | 导入TXT查看点云 | 不启用PLC、雷达和保存进程 |
| `DATA_PATH` | TXT文件或目录，方式1/3使用 | 改为开发人员本机存在的路径 |
| `DATA_NAME` | 目录内的数据集名；`None`按自然文件名顺序查找 | 指定名称时只处理对应数据集 |


### 3.2 `ModeConfig.toml` 的三种采数策略

| `strategy_name` | 内部名称 | 数据流程 | 设备配置 |
| --- | --- | --- | --- |
| 1 | `frame_by_frame` | 雷达帧→滤波/建帧→FIFO队列→逐帧运动规划 | `MachineConfig1.toml` |
| 2 | `complete_workpiece` | 累计完整工件→分区/框体/挂具→开放分枪→运动规划 | `MachineConfig2.toml` |
| 3 | `continuous_bidirectional` | 连续往复扫描→整趟数据/工位状态→规划 | `MachineConfig3.toml` |

三种策略代码均保留。**第三模式暂不用于现场**：其旧四设备配置与当前20轴映射不兼容，启用前需重新确认设备布局和适配。

## 4. 系统如何协作

```text
Qt界面（view/qt）
    ↕ 用户操作 / 状态展示
ControlCenter → PipelineRuntime（control）
    ├─ 采集进程：SDK LidarAcquisitionProcess
    │    ├─ 策略1/3 → raw_data_queue → PLC进程
    │    └─ 策略2 → raw_data_queue → DataProcessingProcess
    │                                 ├─ SDK DataFindBlocks
    │                                 └─ 开放 GunDistributor
    │                                      ↓ machine_data_queue
    ├─ PLC进程：PlcCommunicationProcess ←───┘
    │    ├─ 开放 motionplan / MachineAxisMap
    │    ├─ 开放 MovingFrameData
    │    └─ SDK PlcManager → PLC
    └─ 保存进程：SDK PointCloudSaveProcess ← 保存任务/共享点云块

PLC脉冲/FIFO → pulse_queue → 采集/回放
点云预览 → viz_queue → Qt
状态/日志 → ui_status_queue、log_queue → Qt
```

自动实时方式下，策略1/3一般为采集、PLC、保存三个工作进程；策略2增加一个完整工件处理进程。TXT方式以回放进程替代实时采集。保存使用共享内存块和ACK回收；完整工件采集到处理仍通过普通队列传数组，不能假定所有链路都是零拷贝。

Windows采用 `spawn`。自建入口启动进程时使用 `if __name__ == "__main__":` 和 `multiprocessing.freeze_support()`，不要在模块导入时直接启动进程。界面状态约每秒更新，不等于PLC通讯或采数周期为一秒。

## 5. SDK包含什么，怎么调用

SDK将22个私有实现合并为一个扩展，统一通过 `import acquisition_sdk` 使用，不依赖原五个目录路径。精简声明版的 `acquisition_sdk.pyi` 只声明当前上层直接导入的类/函数及其必要类型依赖.原未标注类型的参数仍有 `Any`，不表示可以传入任意数据。下划线开头的辅助声明仅用于类型关联，不作为项目调用入口。精简声明不会移除二进制运行时的导出。

交付声明的公开入口和类方法按维护方已批准白名单固定，构造函数和必要数据字段继续声明。声明不是SDK完整能力清单。上层今后需要调用未声明的接口或方法时，由SDK维护方确认并更新声明。

| 能力 | 主要公开接口 |
| --- | --- |
| 三策略采集调度、雷达通讯与坐标处理 | `LidarAcquisitionProcess`；通讯和策略辅助在SDK内部 |
| PLC管理、通用二进制编解码 | `PlcManager`、`PlcFrame`、`Int16`、`Int32`、`Repeat` |
| 点云滤波、分组、完整工件提取 | `DataFilter`、`DataSplitting`、`DataFindBlocks` |
| 按帧建帧与横梁识别 | `build_side_frame`、`BeamDetector` |
| 帧队列和按帧结构 | `FrameQueueManager`、`AxisFrameData` |
| 工件/分枪结果结构 | `BlockData`、`DistribeGunData`、`GunGroupData`、`SingleMachineData` |
| 文件回放与保存 | `PointCloudFileProcess`、`resolve_txt_files`、`PointCloudSaveService`、`stop_pipeline` |

以下示例只做内存滤波，不连接硬件：

```python
import numpy as np
from acquisition_sdk import DataFilter

points = np.array([[10., 20.], [100., 200.]])
selected = DataFilter().PassThroughFilter(points, 0, 50, 0, 50)
print(selected)  # [[10. 20.]]
```

SDK依然会导入开放的报文、分枪和公共工具，所以 `.pyd` 不是脱离 `model/` 即可运行的独立DLL。项目级算法调用可参考 `control/DataProcessingProcess.py`；项目进程接线参考 `control/PipelineRuntime.py`，不要凭名称重新拼一套进程链。

## 6. 项目开发流程：需求对应改哪里

| 需求 | 开放修改位置 | 需要重编SDK吗 |
| --- | --- | --- |
| 修改界面、按钮、参数名称和可见项 | `view/qt/`；参数展示 `MachineConfigSchema.py` | 否 |
| 修改项目启停、队列、控制指令调度 | `control/` | 否 |
| 修改PLC报文、字段、帧头尾、读请求 | `model/MovingFrameData.py`，同步PLC程序和收发调用 | 否；通用编解码不支持的新类型需SDK方处理 |
| 修改轴顺序、设备布局、运动规划 | `model/motionplan/`，特别是 `MachineAxisMap.py`，同步设备配置 | 否 |
| 修改完整工件分枪规则 | `model/gun_distributors/GunDistributor.py`及具体分配器 | 否 |
| 修改公共配置读写/范围校验 | `model/utils/`，参数展示规则同时调整 | 否 |
| 调整现有算法公开参数 | 十份 `model/tomls/*.toml` | 否 |
| 更换雷达协议、改私有滤波/分区/保存实现 | 向SDK维护方提出需求 | 是 |

报文开发注意：收发各134字节载荷、外层各4字节头尾；目前共20轴，大端序。`model.MovingFrameData.AxisData` 是PLC报文单轴，`acquisition_sdk.FrameAxisData` 是采数帧单轴，二者不可混用。修改轴数需同步 `AXIS_LIST_COUNT`、结构长度、PLC程序、`MachineAxisMap`及设备配置；只改TOML不能改变协议。

分枪入口以 `distribute_for_machine(blockdata, machine_cfg, machine_id)` 返回该设备分枪结果；新增设备类型需在工厂分支选择对应分配器，并与运动规划的类型支持保持一致。保留 `BlockData` 等SDK数据结构约定，避免队列消费者拿到不同字段。

## 7. 配置修改总原则

下面覆盖当前十份TOML中的全部参数名。相同参数在多台设备或 `.flat` 子表重复出现时只解释一次。距离通常为mm、线速度通常为mm/s、旋转角度为度；轴列表必须按对应设备类型读取，不能假定每个列表都是相同轴序。

手动改文件后**停止并重启整个程序及子进程**。多数配置在对象/进程初始化时读取；部分界面保存会发送配置更新，但不能据此认为任意文件都能热更新。一次只改一类参数，保留修改前文件及效果记录。`SprayConfig`中的范围决定界面允许输入什么，设备文件中的实际值决定设备怎样运动，两者不同。

### 7.1 ModeConfig.toml：全局入口

| 参数 | 修改后的作用 |
| --- | --- |
| `strategy_name` | 整数1/2/3，切换采数和运动策略及对应设备配置；必须重启 |
| `spray_mode` | 0自动、1手动；改变运行流程和实时采集资源创建，不能代替PLC自动/点动反馈 |
| `auth_password` | 界面受保护操作的密码；本文不列现场密码 |
| `require_password` | 是否要求输入操作密码；这是界面操作控制，不是SDK加密或PLC安全联锁 |

### 7.2 SystemConfig.toml：雷达分组

`left_lidar_ids`、`right_lidar_ids`、`left_upper_lidar_ids`、`right_upper_lidar_ids` 指定各方向的雷达ID列表，ID对应 `LidarConfig` 表名，使用字符串。改动会改变哪些雷达参与哪个方向的数据合并；空列表表示该组未配置。必须同时核对安装方向、原点与过滤范围，不能只换IP。

### 7.3 LidarConfig.toml：每台雷达的连接与坐标

每个 `[1]`、`[2]` 等表代表一台雷达。

| 参数 | 修改后的作用 |
| --- | --- |
| `host`、`port` | 改变连接地址；地址错误会连接失败或重连 |
| `type` | 选择已实现的雷达协议/解析类型，当前配置为字符串 `"120"`；不是任意型号名 |
| `install_orietation` | 安装方向，如left/right；保留原拼写，坐标转换依赖此键 |
| `start_angle_direction` | 0向下、1向上、2向右、3向左，面对雷达正面；只看面对粉房左边的激光，按同一参数配置其余方向 |
| `start_angle`、`stop_angle` | 120类型的有效扫描角区间；缩小会丢弃区间外点，不能补回被硬件遮挡的数据 |
| `same_origin_offset_x`、`same_origin_offset_y` | 同一原点模式的XY安装偏移，改变拼接后位置 |
| `diff_origin_offset_x`、`diff_origin_offset_y` | 独立原点模式的XY偏移，改变对应方向的局部坐标 |

### 7.4 PlcConfig.toml：PLC连接

| 参数 | 修改后的作用 |
| --- | --- |
| `tcp_ip`、`tcp_port` | TCP连接的PLC地址和端口 |
| `udp_ip`、`udp_port` | UDP模式本机绑定的接收地址和端口，不是TCP目标的替代写法 |
| `connection_type` | `"tcp"`或`"udp"`；当前正常路径为TCP，UDP不能视为已经完成控制发包验收 |

当前 `[1]` 为运行使用的PLC。修改连接参数不会改变报文结构；结构仍在开放的 `MovingFrameData.py` 中定义。

### 7.5 ReadDataConfig.toml：采集、过滤、队列和保存

| 参数 | 修改后的作用 |
| --- | --- |
| `combined_x_min`、`combined_x_max`、`combined_y_min`、`combined_y_max` | 同原点合并数据的XY直通过滤范围；缩小后会裁掉工件点，扩大可能引入背景 |
| `left_x_min`、`left_x_max`、`left_y_min`、`left_y_max` | 左方向过滤范围 |
| `right_x_min`、`right_x_max`、`right_y_min`、`right_y_max` | 右方向过滤范围 |
| `left_upper_x_min`、`left_upper_x_max`、`left_upper_y_min`、`left_upper_y_max` | 左上方向过滤范围 |
| `right_upper_x_min`、`right_upper_x_max`、`right_upper_y_min`、`right_upper_y_max` | 右上方向过滤范围 |
| `energy_percentage` | 原能量过滤比例配置；当前未发现采集流程读取该键，不应承诺修改后有效 |
| `radius_threshold`、`radius_num` | 雷达近距离遮挡检测：有效半径小于阈值的点数超过radius_num时判遮挡，不是最小有效点数；增大半径或减小数量更容易判遮挡 |
| `x_threshold`、`y_threshold`、`z_threshold` | 点云空间分组间隔；增大使分组更粗，不能简单理解为采样频率 |
| `left_scan_points_threshold`、`right_scan_points_threshold`、`left_upper_scan_points_threshold`、`right_upper_scan_points_threshold` | 各方向有效帧点数门槛；提高会更容易把稀疏帧判为空 |
| `max_scan_length` | 当前工件最大扫描长度，达到限制会结束采集；过小会截断长工件 |
| `plc_send_max_retries` | PLC发送重试上限；提高会延长故障处理等待，不会修复协议不匹配 |
| `max_pulse` | 反馈脉冲回绕上限，必须与PLC一致，否则距离连续性错误 |
| `pulse_to_mm` | 脉冲到毫米换算系数；影响距离和位置判断，按实际反馈单位标定 |
| `fifo_unit_mm` | 每单位FIFO对应链条距离；影响帧与设备位置对齐 |
| `diff_start_pulse` | 检测运动的脉冲差阈值；提高后微小运动更难触发 |
| `lidar_connect_max_retries`、`plc_connect_max_retries` | 上层重连次数上限；越大越久才放弃，不是连接超时秒数 |
| `raw_data_timeout_s` | 链条运动时无新激光数据的保护超时；减小更敏感，过小可能误停链 |
| `socket_recv_poll_timeout_ms`、`socket_recv_max_attempts` | 单次通讯接收时间片及数量，总等待约两者乘积；不是每片重发请求，过短会误判超时 |
| `process_heartbeat_interval_s`、`process_unresponsive_timeout_s` | 进程心跳更新间隔及无响应判定时间；超时应明显大于更新间隔及合理处理耗时 |
| `translate_data_origin` | 1同原点，2独立原点；同时选择对应安装偏移和TXT方向组织方式 |
| `draw_type` | 1点云、2线框、3两者；主要影响预览，不能替代算法开关 |
| `threadpool_size` | 旧兼容项；当前独立保存进程不使用该线程池，修改不能增加保存并发 |
| `point_cloud_save_block_mb`、`point_cloud_save_block_count` | 保存共享内存块大小和数量；容量约为乘积MiB，增大占用更多内存，过小会出现缓冲不足 |
| `point_cloud_save_format` | `"txt"`保留一位小数；`"npy"`保留处理后float64精度，不恢复处理前已损失的信息 |
| `point_cloud_preview_voxel_mm` | 仅预览降采样，越大显示越稀疏；0显示全部点，不改变保存精度 |
| `point_cloud_acquisition_stop_timeout_s` | 停机等待采集封存和退出时间；过短可能使采集未及时完成封存 |
| `point_cloud_save_shutdown_timeout_s` | 停机等待保存排空时间；增大允许更长写盘等待，超时报警 |
| `start_skip_mm` | 策略1/2启动时跳过已进入扫描区工件的距离条件，避免从半件开始 |
| `frame_by_frame_queue_size` | 策略1每方向帧队列容量；容量需覆盖设备距离及积压，增大占更多内存 |
| `fifo_reverse_tolerance` | FIFO小幅后退容忍量；超过按异常处理，不应通过放大容差掩盖反馈错误 |
| `complete_workpiece_queue_size` | 策略2每方向/设备完整工件队列容量，增大占更多内存 |
| `workpiece_fifo_step_mm` | 策略2工件FIFO位置量化步长；改变位置推进粒度 |
| `linked_stop_distance_mm` | 策略2双方向停止位置允许差，过小容易判不同步，过大可能容忍不匹配 |
| `workpiece_origin_side` | 策略2原点侧 `"left"`/`"right"`，改变工件坐标方向 |
| `workpiece_origin_reference_x` | 右原点变换基准：`x_new=基准-x_old`；错误会整体镜像/定位偏移 |
| `swing_threshold` | 策略3往复边界余量，改变开始/结束判断 |
| `max_swing_pulse`、`min_swing_pulse` | 策略3扫描范围/起点；须与扫描轴映射一致，当前第三模式不用于现场 |
| `lidar_scan_speed` | 策略3扫描和回零速度；界面保存允许1～50整数mm/s，不是链条反馈速度 |

可选项 `continuous_bidirectional_queue_size` 当前文件未设置，内部默认1500；不是遗漏的第四种模式。

### 7.6 ProcessConfig.toml：特征识别和分区

| 参数 | 修改后的作用 |
| --- | --- |
| `y_threshold`、`z_threshold` | 处理阶段分组间隔，与ReadDataConfig中同名键属于不同配置读取点 |
| `beams_threshold` | 横梁候选高度在非空帧中的最低出现比例；提高后需更稳定出现才判梁 |
| `merge_beams` | 邻近候选梁段间距严格小于该值时合并；增大更容易把邻梁合成一段 |
| `beams_width` | 合并后允许的最大梁厚；过小会排除厚梁 |
| `beams_min_valid_frames` | 横梁识别最少非空帧数，整数至少1；提高需积累更多有效帧 |
| `safety_beam` | 枪相对横梁的安全距离，影响上下梁附近目标位置 |
| `beam_y_large_move_threshold` | 连续有梁时，Y目标与反馈差严格超过此值触发X退让及Y到位等待 |
| `jig_threshold` | 最上平面附近挂具分离距离条件；影响挂具与工件边缘划分 |
| `x_range`、`y_range`、`z_range` | 柜体/平板尺寸分类门槛；不同调用点有严格/非严格边界判断，边界样本需单独验证 |
| `find_boundary_type` | 1固定六分区，2自动分区；原注释称随机，不能理解为每次随机采样 |
| `inside_x_use_middle` | 1按整体X中心，0按X最小值加偏移，改变内分区判定界线 |
| `inside_x_min_offset` | 偏移模式界线为x_min加该值，改变内外区分界 |
| `inside_partition_min_y_range` | 内分区最小Y范围，增大将排除更多窄分区 |
| `y_partition_threshold`、`z_partition_threshold` | 分区合并/保留尺寸门槛，影响小分区数量 |
| `send_data_type` | 1按帧组织，2按整块组织处理结果，不改变PLC底层字节协议 |
| `find_y_plane` | 最上Y平面搜索的占比条件；改变边缘/上平面的识别结果 |

### 7.7 SprayConfig.toml：公共规划规则及编辑范围

| 参数 | 修改后的作用 |
| --- | --- |
| `spray_pos_tolerance` | 定位到位公差；越大越容易判到位，但降低定位判定精度 |
| `x_pre_distance` | X提前定位的距离条件，改变预定位时机 |
| `side_2d_cycle_axis` | `"x"`或`"y"`，选择侧面二维往复计次轴 |
| `stage_detect_frame_count` | 策略1/3工件边界连续有效帧数，增大提高稳定性同时延迟判断 |
| `frame_x_interpolation_enabled` | 0静态Y搜索范围，1按当前Y动态逐枪搜索X目标 |
| `frame_x_no_data_target_mode` | 0无数据回安全位；1优先使用本帧其他区域的全局x_min，全帧无数据仍回安全位 |
| `frame_x_dynamic_speed_mode` | 动态搜索时0固定x_pos_speed，1按XY变化计算插补速度 |
| `frame_x_slow_in_out_enabled` | 非跟踪按帧0固定前偏移，1按工件位置慢进慢出 |
| `frame_idle_y_reciprocate_enabled` | 开启设备但空闲时0全轴回安全位，1允许Y在配置范围往复；会改变空闲运动行为 |
| `xn_side_y_mode` | 策略2侧面分枪：0共享Y，1独立Y；修改后重启 |
| `gun_distance` | 分枪用喷枪Y间距，影响各枪覆盖区域 |
| `bottom_recip_y_max` | 兼容外翻转规划底部往复的Y上限，是否有效取决于设备类型 |
| `rect_threshold` | 柜体矩形喷涂四段/六段选择阈值 |
| `y_jump_threshold`、`x_scan_max` | 兼容车厢内端面判定/扫描条件，非所有设备均使用 |
| `fx_mode` | 仿形兼容流程0正常、1二维，依设备规划分支生效 |
| `side_reciprocate_mode` | `"2d"`二维或`"rect"`矩形侧面往复路径 |
| `side_back_end_face_enabled` | 1喷侧面柜体背端面，0跳过中间end_face段 |
| `side_rotate_enabled` | 1使用侧面旋转，0侧面R角度归零；不代表其他轴自动禁用 |
| `min_recip_distance` | 内分区最小往复距离，影响短分区往复路径 |
| `xn_side_flat_handoff_distance` | 相邻平板衔接起喷剩余距离，0关闭；修改后重启 |

以下各对范围键供界面/公共参数校验使用，修改它们主要改变**允许输入范围**，不会自动把每台设备当前值改为该范围端点：

| 范围键 | 对应实际参数 |
| --- | --- |
| `x_status_offset_min`、`x_status_offset_max` | x_status_offset |
| `out_front_x_offset_min`、`out_front_x_offset_max` | out_front_x_offset |
| `out_after_x_offset_min`、`out_after_x_offset_max` | out_after_x_offset |
| `out_up_y_offset_min`、`out_up_y_offset_max` | out_up_y_offset |
| `out_down_y_offset_min`、`out_down_y_offset_max` | out_down_y_offset |
| `out_z_front_offset_min`、`out_z_front_offset_max` | out_z_front_offset |
| `out_z_after_offset_min`、`out_z_after_offset_max` | out_z_after_offset |
| `search_front_z_offset_min`、`search_front_z_offset_max` | search_front_z_offset |
| `search_after_z_offset_min`、`search_after_z_offset_max` | search_after_z_offset |
| `outside_total_cycles_min`、`outside_total_cycles_max` | outside_total_cycles |
| `in_front_x_offset_min`、`in_front_x_offset_max` | in_front_x_offset |
| `in_after_x_offset_min`、`in_after_x_offset_max` | in_after_x_offset |
| `in_up_y_offset_min`、`in_up_y_offset_max` | in_up_y_offset |
| `in_down_y_offset_min`、`in_down_y_offset_max` | in_down_y_offset |
| `in_z_front_offset_min`、`in_z_front_offset_max` | in_z_front_offset |
| `in_z_after_offset_min`、`in_z_after_offset_max` | in_z_after_offset |
| `origin_pos_min`、`origin_pos_max` | origin_pos编辑值；数组和设备类型规则另行校验 |
| `inside_total_cycles_min`、`inside_total_cycles_max` | inside_total_cycles |
| `recip_reduce_distance_min`、`recip_reduce_distance_max` | recip_reduce_distance |

### 7.8 MachineConfig1/2/3.toml：每台设备实际参数

`[0]`、`[1]`等表代表设备SN；`MachineConfig2`中的 `[1.flat]`、`[2.flat]` 是平板专用覆盖值，按相关分枪/规划分支使用，不是另一台设备。修改公共值前检查是否被flat值覆盖；有键不代表当前设备一定执行对应动作。

| 参数 | 修改后的作用 |
| --- | --- |
| `sn` | 设备编号，需与表名、界面及规划匹配 |
| `type` | 选择分枪和运动规划类型；新增字符串不会自动新增算法或轴映射 |
| `install_orietation` | 左右安装方向，决定左右轴映射，保留原拼写 |
| `axis_type` | 设备轴名称组织；PLC实际下标由MachineAxisMap确定，不是改列表即可重排PLC轴 |
| `spray_num` | 设备喷枪数量；需与原点列表、分枪和实际输出一致 |
| `x_position`、`z_position` | 安装位置/设备到激光原点的定位基准 |
| `tracking` | 0不跟踪、1跟踪；仅对应支持的规划分支生效 |
| `y_move_min`、`y_move_max` | Y往复范围，改变行程和覆盖高度 |
| `spray_radius` | 喷枪半径 |
| `origin_pos` | 喷枪Y原点 |
| `safe_pos` | 安全返回目标列表 |
| `max_limit_speed` | 各轴速度上限 |
| `min_limit_pos`、`max_limit_pos` | 各轴位置限位 |
| `x_status_offset` | 出粉相关X偏移 |
| `x_front_status_offset`、`x_after_status_offset` | 前/后出粉偏移，部分策略2设备使用 |
| `out_front_x_offset`、`out_after_x_offset` | 外侧前/后X目标偏移，改变枪到工件距离或进出位置 |
| `in_front_x_offset`、`in_after_x_offset` | 内侧前/后X目标偏移 |
| `out_up_y_offset`、`out_down_y_offset` | 外侧上/下Y边界偏移 |
| `in_up_y_offset`、`in_down_y_offset` | 内侧上/下Y边界偏移 |
| `out_z_front_offset`、`out_z_after_offset` | 外侧沿Z的前/后定位偏移，改变喷涂起止窗口 |
| `in_z_front_offset`、`in_z_after_offset` | 内侧沿Z的前/后定位偏移 |
| `search_front_z_offset`、`search_after_z_offset` | 数据搜索Z窗口前/后扩展，不等于实际运动目标偏移 |
| `x_pos_speed`、`y_pos_speed` | X/Y定位速度，最终仍受速度上限约束 |
| `x_recip_speed`、`y_recip_speed` | X/Y往复速度 |
| `z_back_speed` | 支持Z反喷的设备返回喷涂速度；无独立Z轴的设备不据此增加轴 |
| `z_zeroing_speed` | 支持Z轴设备的归零/返回速度 |
| `outside_total_cycles`、`inside_total_cycles` | 外/内往复次数 |
| `recip_reduce_distance` | 往复缩减距离，改变实际往复覆盖范围 |
| `z_spray_position` | flat子表中的平板Z喷涂位置 |
| `top_chain_hold_enabled` | 兼容xn_updown2顶部停链喷涂开关 |

当前20轴映射：左顶Y1/X1/Y2/X2=0/1/2/3，左底=4/5/6/7，左二维Y/X=8/9；右顶=10/11/12/13，右底=14/15/16/17，右二维=18/19（下标从0开始）。四轴inout设备的限位/速度/安全位列表：两元素按Y/X共用，四元素按Y1/X1/Y2/X2读取；`origin_pos`遵循枪原点规则，不要机械套用这个列表顺序。

不同项目的偏移公式与坐标方向不同，因此“偏移增加100mm”不保证物理上远离工件100mm。先用固定数据核对目标值及方向，再做现场小范围验证。手动改文件也不能绕过机械和PLC层面的约束。

## 8. 更新SDK与常见问题

SDK升级使用新的发布包版本，如 `0.1.1`；仍保持 `from acquisition_sdk import ...`，不要手动给模块加 `_v0_1` 后缀。ABI文件名中的 `cp311-win_amd64` 必须保留。先退出主程序和全部子进程，备份旧pyd/pyi，再成对替换；保留项目定制源码和现场TOML。回退时同样成对恢复。进程间对象应来自同一套SDK，不支持运行中热替换或跨版本保留旧队列对象。

| 问题 | 优先检查 |
| --- | --- |
| 找不到acquisition_sdk / DLL加载失败 | pyd与main同目录、Python3.11 x64、第三方依赖/原生运行库；不要混放源码SDK包 |
| 更改TOML没有效果 | 是否改当前策略对应文件；是否flat覆盖；是否重启全部进程；当前设备分支是否读取该键 |
| TXT无法导入 | main中的DATA_PATH/DATA_NAME是否存在；独立原点数据是否按left_/right_方向组织 |
| 按钮不能使能 | PLC连接、PC自动反馈、停止状态、安全回位条件；不要删除联锁来解决 |
| 保存缺失或缓冲不足 | data目录可写、磁盘容量、共享块容量、ACK回收和停机排空日志 |
| 配置自检通过但设备不动 | 自检不验证设备type/轴布局适配，核对MachineAxisMap和运动分支 |

