# 第五阶段：路径和公开依赖验收

日期2026-11-13，验收通过。本阶段仅新增隔离验收工具与副本，未修改产品算法或现场配置。

使用第四阶段完整22实现的同一个pyd，将公开上层、原model/tomls和测试复制到中文且带空格的独立目录，从另一个中文带空格目录启动。

实测结果：

- 原prepare_environment正确定位应用目录；PipelineRuntime继续读取应用根model/tomls，不需要旧五个私有源码目录。
- 仅在验收副本修改公开MovingFrameData帧头，编译通信实现观察到新值。
- 修改公开StrategyUtil，三种策略的编译FrameQueueManager均调用到修改后的公开实现。
- 修改开放默认分枪规则，通过开放GunDistributor实例访问的规则返回新结果。
- 父进程和真实Windows spawn子进程观察结果一致，子进程退出码0，无设备网络操作。
- pyd SHA-256前后保持 `e1eed1a75456fc05d6636ed793622053393d9a3d16c9d7d00af8fa4086dc0eac`；十份配置字节均不变。

本轮分枪验证覆盖默认规则的可修改性，不等于全部分枪规则业务差分或实机验收。任意config_dir全链路支持不是本轮目标，既有默认路径行为保持。第四阶段尚未完成的独立审阅限制和六项既有业务测试问题仍保留。

证据：[验收结果](../output/sdk-paths/result.json)、[完整日志](../output/sdk-paths/acceptance.log)、[可复现脚本](../output/sdk-paths/accept.py)。控制台可能按宿主编码显示中文乱码，JSON文件以UTF-8保存；路径操作和断言使用原Unicode字符串。

下一阶段：制作正式类型声明、版本化发布包和正向文件清单；本验收目录含测试及故意修改的公开副本，不作为交付包。
