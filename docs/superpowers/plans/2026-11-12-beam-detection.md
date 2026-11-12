# 横梁检测实施计划

**目标：** 按用户确认的旧算法识别横梁，仅返回检测结果，不生成 Y 定位或喷枪命令。

**设计与确认依据：** 本对话用户确认的 Z 搜索区间、上下梁分类、三个旧参数及新增至少 5 个非空帧的约束；旧实现分析见 `docs/2026-11-11-hnxs-beam-algorithm.md`。

**结构：** `model/dataprocess/frame_by_frame/BeamDetector.py` 是无文件读写、无运动依赖的功能块，接收配置和左右帧堆栈。按帧规划器加载一次参数并调用，结果存入 `beam_results[sn]`，后续运动规划可读取。

**约束：** 保留旧算法的非空帧分母、Y 去重、严格小于合并距离、厚度上限、单梁中心分类和多梁首尾分类；不足 5 帧返回未找到；Z/Y 步距独立；无历史结果锁存；不修改其他设备轨迹，不提交代码。

**参数：** ProcessConfig.toml 增加 beams_threshold=0.7、merge_beams=300、beams_width=200、beams_min_valid_frames=5。实际 Y/Z 分层优先使用 ReadDataConfig，与 DataProcessWorker 构帧一致。

**接口：** BeamDetector(process_config).find_for_machine(machine_cfg, frame_stack, runtime_cfg=None)，返回 found、beam_type、y_bottom、y_top；设备类型决定 upper/lower，安装方向决定 left/right，运行时搜索偏移优先。

## 实施步骤

- [x] 编写测试并确认新模块缺失导致失败；覆盖 4/5 帧、空帧分母、每帧去重、噪点、连续层、合并边界、厚度边界、单梁分类、多梁分类、窗口及左右隔离。
- [x] 实现独立检测器与参数，测试通过。
- [x] 接入内外顶/底调用，验证检测不改变安全轴命令，结果不会残留。
- [x] 运行相关运动回归、flake8 与类型检查；记录结果和接口说明。

## 执行记录

本次在用户指定工作目录内直接修改，保留已有暂存和未暂存修改，不创建工作树、不提交。窗口索引采用 ceil(起点/Z步距)、floor(终点/Z步距)，只统计指定范围内的帧，越界窗口不复用边缘帧。

已确认 RED：新测试因 BeamDetector 模块不存在而失败。实现后，横梁测试及 test_motion_2d_xy_servo、test_project_axis_map、test_device_return_enable 共 35 项通过；修改文件 flake8 通过，control/model/view/main.py 和新增测试 pyright 为 0 errors。集成测试最初错误地断言横向二维轴也必须保持零位，已将断言限定到内外顶底 16 根轴。使用说明见 docs/beam-detection.md；未连接 PLC 验证真实点云。
