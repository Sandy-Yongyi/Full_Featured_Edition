# xn_side 自动路径规划图

白底、黑字，2560×1440，16:9。仅表达 xn_side；主图聚焦柜体场景。

当前配置：xn_side_y_mode=1，side_reciprocate_mode="2d"，side_2d_cycle_axis="x"，side_back_end_face_enabled=0，side_rotate_enabled=1。

1. 总流程：分枪结果 → 自动条件 → 等前外侧 → 前外喷涂 → 收枪 → 各内侧列 → 后外喷涂 → 安全归位。
2. 路径生成：枪组提供Y范围与启用；X范围按工件边界扣偏移及安装位置，执行轴限位；二维模式X/Y同时往复，按反馈换向。
3. 换面与分支：收枪的轴约束、背板开关、漏过工件和无枪分支。

这不是设备仿真或实机通过证明。没有修改运动控制代码。内腔进枪函数存在运行阻断：
name 'inside_z_span' is not defined

已单独提取当前源码中的 _get_inside_enter_threshold 方法，用最小输入执行复现。其返回语句比较了本函数内未定义的 inside_z_span；外层 _can_enter_inside_column 又将其返回值当作阈值使用。图中公式标为设计意图，不能当作当前已可执行行为。

源码：
- model/motionplan/MotionCompleteWorkpiecePlanning.py
- model/motionplan/MotionXNSidePlanning.py
- model/motionplan/MotionReciprocate.py
- model/motionplan/MotionToTarget.py
- model/tomls/SprayConfig.toml
