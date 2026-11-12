# 按帧横梁检测功能块

实现：`model/dataprocess/frame_by_frame/BeamDetector.py`。模块只依赖分层帧格式，不读取文件、不修改输入帧、不产生运动或开枪指令。放在 dataprocess 下，便于随私有数据处理代码一起构建扩展库；开放的 motionplan 仅调用接口。

## 参数

在 `model/tomls/ProcessConfig.toml` 设置，重启程序生效：

```toml
beams_threshold = 0.7
merge_beams = 300
beams_width = 200
beams_min_valid_frames = 5
```

出现比例以非空帧数为分母；每帧相同 Y 只计一次。非空帧定义为至少有一行 H_Axis > 0，与旧算法一致。至少有 beams_min_valid_frames 个非空帧才查找，不足时返回未找到。计数针对堆栈帧位置；FIFO 补齐的重复帧也按帧位置计数，不代表独立采样次数。

相邻候选 Y 差等于 y_threshold 时连成段；段间距严格小于 merge_beams 时合并；合并后 y_top-y_bottom 不超过 beams_width 才接受，单层厚度为 0。梁顶、梁底是 Y 分层代表值，不额外加一个层宽。

实际 Y/Z 步距与 DataProcessWorker 构帧一致：优先 ReadDataConfig.toml，缺少时使用 ProcessConfig.toml。Z 不使用 Y 步距换算。

## 调用

```python
from model.dataprocess.frame_by_frame.BeamDetector import BeamDetector

detector = BeamDetector(process_config)
result = detector.find_for_machine(machine_cfg, frame_queue_manager.frame_stack, runtime_cfg)
```

构造时传入配置字典；若 ReadDataConfig 覆盖了 Y/Z 步距，调用方应先合并实际步距。MotionInOutUpPlanning 已完成这一处理，配置仅初始化时读取。

设备规划器也可显式调用方向接口，不依赖设备类型：

```python
result = detector.find_for_side(side, z_position, search_front_z_offset, search_after_z_offset, frame_stack, "upper")
```

设备配置包含 type、install_orietation、z_position、search_front_z_offset、search_after_z_offset。runtime_cfg 可省略；提供时其搜索前后偏移优先。

- inout_up 返回上横梁，inout_down 返回下横梁。
- left/right 只查各自堆栈，不跨方向补结果，不使用 left_upper/right_upper 的 X 分层帧。
- 搜索 z_position-search_front_z_offset 至 z_position+search_after_z_offset，包含两端。索引下界向上取整、上界向下取整，裁剪到实际堆栈；完全越界不使用边缘帧。
- 单梁段按梁中心 > 全部有效 Y 范围中心判上梁，否则判下梁，等于也判下梁。
- 多梁段按首尾取下梁/上梁，不要求它们分别处于中心两边；极端梁超厚时不向内部寻找替代。
- 本周期没有有效目标即返回未找到，无上一周期目标锁存。

返回字典：

```python
{"found": True, "beam_type": "upper", "y_bottom": 2600, "y_top": 2700}
{"found": False, "beam_type": "lower", "y_bottom": None, "y_top": None}
```

## 当前接入范围

`MotionFrameByFramePlanning` 只分发已开启设备，不直接调用检测器，也不存储横梁结果。MotionInOutUpPlanning / MotionInOutDownPlanning 分别通过公用 InOutFramePlanningBase 显式传入方向、Z 定位和搜索偏移，检测结果是设备规划内部的局部变量，对外只返回轴命令。当前不提供横梁结果查询接口。

内外顶/底均已接入独立路径规划，规则分别见 docs/inout-up-planning.md 和 docs/inout-down-planning.md。检测器本身仍不计算运动、不控制开枪。完整工件及其他设备规划不接入此功能。

## 验证

`tests/test_beam_detector.py` 验证 4/5 帧边界、可配置门槛、空帧分母、每帧去重、中心分类、合并与厚度边界、独立步距、窗口边界、左右隔离及无结果锁存。集成测试验证由各设备规划消费横梁结果、不可达下梁关粉，以及设备关闭后不调用顶/底自动规划器。
