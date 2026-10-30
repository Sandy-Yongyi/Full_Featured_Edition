# Qt 开发运行方式

运行方式 `control_type` 与 `ModeConfig.toml` 中的 `strategy_name` 相互独立。直接在 main.py 顶部设置运行方式和点云路径，不保存到生产 TOML，也不增加操作员界面选择控件。

## 直接修改代码

修改 main.py 顶部集中设置区后，直接运行 main.py 即可：

```python
CONTROL_TYPE = 2  # 1=TXT联调PLC，2=实时采数与运动，3=只画图
DATA_PATH = r"D:\draw_points\JRQC"  # 改成实际TXT文件或目录
DATA_NAME = None  # 可填 "sample.txt" 指定数据集；None自动查找
```

方式 2 忽略以上点云路径设置，交付前保持 CONTROL_TYPE=2。方式 1/3 使用 DATA_PATH、DATA_NAME；方式 3 启动窗口后等待人工点击“导入 TXT 点云”，不会自动读取。命令行参数继续可用，并优先覆盖代码中对应的设置。

## 启动命令

在项目目录中使用 Python 3.11 运行：

```powershell
# 使用 main.py 顶部设置；正常交付保持 CONTROL_TYPE=2。
python main.py

# 开发方式 1：TXT 联调 PLC。点击启动按钮后启动联调流程。
python main.py --control-type 1 --data-path 'D:\draw_points\case'

# 目录中指定一组数据，匹配 combined_/left_/right_/left_upper_/right_upper_ 前缀。
python main.py --control-type 1 --data-path 'D:\draw_points\case' --data-name 'sample.txt'

# 开发方式 3：只画图。窗口启动后点击“导入 TXT 点云”加载。
python main.py --control-type 3 --data-path 'D:\draw_points\sample.txt'

# 只画图也可导入目录；未指定 data-name 时合并目录内全部 TXT，不递归。
python main.py --control-type 3 --data-path 'D:\draw_points\case' --data-name 'sample.txt'
```

示例路径需要替换为实际文件。命令行相对路径按应用初始化后的项目/应用目录解析，建议使用绝对路径。代码中也可调用 `qt_main.build_controller(control_type=..., data_path=..., data_name=...)`；该函数只构建控制器，不自动启动进程。

## 进程组合

以下均不包含 Qt 主进程：

| 运行方式 | 策略 | 子进程 |
| --- | --- | --- |
| 1：TXT 联调 | 1：逐帧 | DataProcessWorker、PLC |
| 1：TXT 联调 | 2：完整工件 | DataProcessWorker、DataProcessingProcess、PLC |
| 2：实时采数，自动模式 | 1 / 3 | 激光采集、PLC、独立保存 |
| 2：实时采数，自动模式 | 2 | 激光采集、工件处理、PLC、独立保存 |
| 3：只画图 | 任意现有策略 | PointCloudFileProcess（只读文件导入） |

方式 1 会联调真实 PLC，仍经过原有启动授权。保留旧 DataProcessWorker 已实现的策略 1/2；策略 3 尚无 TXT 回放实现，启动前明确报错，不启动任何业务进程。方式 2 的 `spray_mode=1` 仍按原实现跳过激光及保存。

## TXT 联调数据约定

- 同一原点配置（`translate_data_origin=1`）：支持 `combined_*.txt` 及普通名称的 TXT；方向前缀文件不重复计入同原点数据集。
- 独立原点配置（`translate_data_origin=2`）：使用与启用激光方向对应的 `left_*.txt`、`right_*.txt` 等文件。指定其中一个文件会按共同后缀查找同目录的其他方向。
- `DATA_NAME=None` 或空字符串：按文件名自然顺序处理目录内的数据集，例如 2 在 10 前，时间戳名称按相同规则排序；独立原点的同后缀方向文件合为一组。指定 `DATA_NAME` 则只处理对应名称的数据集，继续按原点配置匹配来源。
- 逐帧策略每次加载当前文件，当前帧播放完后切换下一组，跨文件不重置 PLC FIFO；目录播放完后仍按旧行为发送空帧，直到停止。完整工件策略将数据集按同样顺序提交给工件处理进程。界面显示沿用原点变换和预览逻辑。

## 只画图数据约定

- 接受 XYZ 三列或 XYZRGB 六列 TXT，支持单行点云和混合导入。源数据保留读取的 RGB；Qt 显示统一使用与深色背景有明显区别的明亮蓝—青冷色渐变，不显示原文件的暖色 RGB。
- 显示预览与方式 1/2 使用相同原点规则：同一原点且选择右侧原点时，显示副本按 `X显示=workpiece_origin_reference_x-X原始` 转换；左侧原点或独立原点保持原输入坐标。TXT 文件不改写。不执行分区、分枪或运动规划，不启动 PLC、激光和保存服务，设备状态均保持未启用。
- 三种运行方式统一从显示坐标的 X 负方向观察工件，Y 轴竖直向上、Z 轴水平；网格位于 X–Z 地面平面，并以轻微俯视角显示深度。首次显示及“适配视图”均恢复该方向；拖动仍可自由旋转。不改变文件 XYZ 或 PLC 运动控制坐标。
- 文件读取在独立子进程完成，界面通过原有可视化队列显示；失败通过告警反馈。导入完成后该进程等待，避免被监控误判为异常退出。
- 设备配置和扫描参数只读，后端也拒绝扫描参数保存与设备控制命令。点击“停止查看”会清空场景并退出导入进程；之后可重新导入同一路径的最新内容。

`qt_preview.py` 继续用于空场样式预览，不负责导入文件；它与方式 3 的用途不同。

## 最近事件与识别框配色

最近事件只显示最近 5 条标准输出打印行，过滤 logger、授权和其他系统事件；筛选发生在截取最近条数之前。打印的文本片段会合并为完整行，避免一次 print 被拆成多条。运行记录页和原文件日志继续按各自原有来源保留，不读取日志文件回灌最近事件。

识别框采用：外框绿色、内框红色、挂具亮黄色；点云按当前点云的 X 最小/最大值归一化，采用蓝色（X 小）→青色（中间）→青绿色（X 大）的高对比冷色渐变。相同 X 值颜色相同，Y/Z 和相机旋转不改变颜色；X 全相同时使用中间青色。显示区仅保留点云、外框、内框、挂具四个图层开关，不再显示“喷涂路径待接入”。配色仅作用于显示，不修改识别、分枪或运动数据。

验证边界：已通过独立 TXT 导入子进程到 Qt 画布的自动测试。TXT/PLC 分支测试验证了进程组成和队列连接，未启动真实 PLC 或激光；实际机械联调仍需现场验收。
