# 采数 SDK 第三阶段实测报告

完成日期：2026-11-13。结论：代表性单 .pyd 技术路线通过本机编译和运行自测；尚未开始正式业务迁移，不是最终可发布 SDK。

## 实际产物与范围

- 已生成 [试验扩展](../output/sdk-spike/run-a/acquisition_sdk.cp311-win_amd64.pyd)，887,808 字节，CPython 3.11 Windows AMD64。
- SHA-256：`7df9fbb39d5033cd6c57252a5fc8eb17d8d85d45eddcf4556f7f608ef0547359`。
- 本轮实际编译 9 个代表性实现及 7 个包初始化模块，共 16 个编译模块实体，不是全部 22 个。
- 三份二进制 build/run-a/run-b 的 SHA-256 一致；两套运行目录都不包含 acquisition_sdk 源码或原五个底层目录。
- 每套运行目录正向声明 27 个交付文件：一个 .pyd、公开 model 包/工具/报文及十份原配置。测试产生的 data/logs/*.log 单列，不加入可信代码清单。
- 原 181 个源码、测试及配置文件 SHA-256 不变；没有移动原分枪/报文/工具，没有改采数算法、配置或 main.py 开发设置，没有安装升级依赖。

代表性实现：PlcFrame、PlcCommon、AxisFrameDataFormat、BlockDataFormat、FrameQueueManager、PointCloudSaveBuffer、PointCloudSaveProcess、PointCloudSaveService、PointsFileUtil。

## 自测结果

| 运行方式 | unittest 项数 | 通过 | 失败/错误 | 不适用跳过 |
| --- | ---: | ---: | ---: | ---: |
| 隔离源码参考 source-a | 11 | 10 | 0 | 1 |
| 原公开代码 + 编译扩展 run-a | 11 | 10 | 0 | 1 |
| 修改公开报文/工具 + 同一扩展 run-b | 11 | 11 | 0 | 0 |

跳过项仅为“公开源码变更”专项，它只对 run-b 适用。源码模式中的两个二进制专属检查不执行二进制断言，因此不能把上述总数解释成 33 个不同业务场景；真实检查内容见下表。保存格式/策略等子测试组合不另计 unittest 项数。

| 能力 | 实际验证内容 | 结果 |
| --- | --- | --- |
| 固定 SDK 入口 | acquisition_sdk、0.1.0、SDK_API_VERSION=1；无版本文件名后缀 | 通过 |
| 冷导入 | 版本、纯数据、编解码标记导入无 LoggerUtil/Open3D 加载，无日志/子进程创建 | 通过 |
| 开放报文继承 | 公开 dataclass 继承编译 PlcFrame；Annotated、get_type_hints、嵌套帧和列表 | 通过 |
| 现有 PLC 报文 | 当前 20 轴、134 字节；独立 struct 期望字节与编码/解码结果一致 | 通过 |
| 项目报文变化 | run-b 修改帧头尾、请求命令，并添加 UInt16/Int32/UInt32/Float32/FixedStr/Repeat 测试帧；fake socket 验证底层确实使用新公开定义 | 通过，同一 .pyd |
| 导入顺序 | 先公开报文后 PlcManager、先 PlcManager 后公开报文；接收帧类身份一致 | 通过 |
| 公开工具修改生效 | run-b 修改开放 StrategyUtil，父/子进程内 SDK 队列管理器均观察到外部函数调用 | 通过，同一 .pyd |
| 逐帧队列 | FIFO 顺序、重复帧及开放调用方直接写 frame_stack 后后续 SDK 方法观察到修改 | 通过 |
| 完整工件队列 | 插入、deepcopy 隔离、移位、None 尾项及直接写 queues 后的行为 | 通过 |
| 连续双向队列 | 三工位到位/放行搬移、占用拒绝、旧完成位抑制、直接写槽位后状态机可观察 | 通过 |
| 真实 spawn | SDK 逐帧/嵌套工件类型和开放收发报文、NumPy float64 往返；类身份和字段保持 | 通过 |
| 编译保存进程 | 真实 PointCloudSaveProcess，两个不同工件、不同共享块、job_id/块 ACK、相对 Z/绝对 Z × TXT/NPY | 通过 |
| 保存错误 | 同名文件冲突上报，未发送成功 ACK、未生成完成清单、不覆盖原文件 | 通过 |
| 进程退出 | 所有试验 worker 正常路径退出码0；测试入口检查没有遗留活跃子进程 | 通过 |
| 源码隔离 | -I 新进程、去除仓库/source/build 搜索路径；用 Windows GetModuleHandleW 验证实际 .pyd 已加载 | 通过 |
| 公开依赖未编译 | XML 实体集合精确等于 9 个实现 + 7 包；公开工具/报文为运行目录下 .py 来源 | 通过 |
| 清单拒绝未知文件 | 注入未知 .py 必须失败；删除试验注入文件后恢复通过 | 通过 |
| 副本审计 | 原件/副本哈希、业务 AST、配置与公开工具字节；受控修改报文副本后审计失败，恢复后通过 | 通过 |

以上三种模式验证的是队列管理和相关数据/保存行为，不是雷达实机采数三策略全部链路。没有连接雷达或 PLC；测试入口禁止外发设备网络。

## 发现并处理的问题

1. **本机旧 Nuitka 自动检测没有找到编译器。** 已安装 VS 18/MSVC 14.51，使用现有 vcvars64 环境后能进入 C 编译，不需要更改业务或安装新工具。
2. **编译缓存拒绝访问。** 使用 `--disable-cache=ccache` 后编译成功，成功轮耗时49.375秒。正式构建需要记录此环境步骤和参数，不能只照抄最初命令。
3. **加载器检查假设错误。** Nuitka 使用 nuitka_module_loader，且 __file__/spec.origin 显示不存在的模拟 .py 路径；原来的 ExtensionFileLoader 断言误判。现改成实际 .pyd 加载句柄、编译标记、文件白名单及报告联合验证。模拟模块名仍可通过运行时看到，单 .pyd 不等于隐藏全部内部名称或防止逆向。
4. **独立审查发现队列属性可变性漏测。** 已补三策略从开放调用方直接写入槽位，再调用 SDK 方法的断言，并在真实 spawn 中复用差分。
5. **独立审查发现保存任务区分不足及 ACK 检查竞态。** 两工件改用明显不同坐标；先封存全部任务再提交，避免第二次 append 中 poll_acks 抢走首个 ACK；逐 job_id 校验块与输出。
6. **独立审查发现重复暂存会信任残留文件。** 已改为从 source-manifest 推导允许集合、逐文件复制，拒绝未知代码/配置，精确比对 XML 编译实体；运行时也做白名单审计。
7. **审计和观察证据不完整。** 已核验所有 copy_sha256，含开放报文适配副本；记录 sys.path、加载器、公开模块来源、worker 退出、ACK 与合成点云结果。

独立审阅没有 Critical 项，提出的三项 Important 和两项附加证据观察均已在本次单次修正中处理并完整回归。没有再次委派审阅；修改后的结果由覆盖测试和最终证据断言验证，不能把它说成第二次独立审阅。

## 原项目完整回归

再次运行全部 42 个原测试模块，共273项：265通过，6个断言失败、2个运行错误。失败测试标识与第一阶段完全相同，新增失败为0：

- test_module_layout：构建入口位置错误、根目录文件清单不符，共2项。
- test_motion_continuous_bidirectional_planning：安全位置、清理X位置/独立限位、使能保持、伺服告警，共5项。
- test_qt_deployment：旧 top_chain_hold_enabled 字段缺失，共1项。

这些原有问题没有在本阶段修复，也没有删测试或调整现场配置。第三策略的实机适配和旧断言原因仍需后续单列处理。

## 未覆盖及后续门槛

- 22个正式实现中其余13个尚未迁移/编译：lidar全部4个、dataprocess全部7个、formats中的FrameDataFormat、pointcloud中的PointCloudFileProcess。
- 完整采数三策略、Open3D处理链、真实雷达/PLC、长时间运行和性能尚未验证。
- 开放分枪和运动源码的正式目录迁移、逐规则差分及修改扩展验证属于第四阶段以后。
- 13个公开utils文件的来源都已审计，但代表性副本没有提供整个开放应用。MachineConfiguration/UiTaskFeedback等需要其他开放模块，不能宣称本试验包是可运行的完整上层软件。
- 尚未制作完整 .pyi、wheel/zip 发布包、升级/回退流程或独立机器部署验收。
- 只有本机 CPython3.11/Windows AMD64组合通过；没有验证其他Python版本、架构或全部requirements版本范围。

下一步是第四阶段：按已确认的22个实现范围制定并执行正式迁移，保留 model/tomls、开放 MovingFrameData 和分枪、其余公开utils；不能把本轮 .pyd 直接替换进生产项目。

## 复现与证据

```powershell
$sdkPython = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe'
& $sdkPython -B output/sdk-spike/prepare.py
& $sdkPython -B output/sdk-spike/build.py --developer-env --no-compiler-cache
& $sdkPython -B output/sdk-spike/validate.py --mode source --suite all
& $sdkPython -B output/sdk-spike/validate.py --mode binary --suite all
& $sdkPython -B output/sdk-spike/validate.py --mode binary --variant b --suite all
& $sdkPython -B output/sdk-spike/regression.py
& $sdkPython -B output/sdk-spike/finalize.py
```

试验目录内已有记录供直接查看，无需为了查看报告重新编译。prepare 会从原文件重新生成副本，不能在最终生产迁移后不经调整继续使用本阶段旧映射。

- [最终结果与完整性断言](../output/sdk-spike/evidence/final-manifest.json)
- [成功构建记录](../output/sdk-spike/evidence/build-developer-uncached-result.json) / [构建日志](../output/sdk-spike/evidence/build-developer-uncached.log)
- [精确编译模块集合](../output/sdk-spike/evidence/report-modules.json)
- [运行目录正向清单](../output/sdk-spike/evidence/runtime-manifests.json)
- [实际加载与公开依赖来源](../output/sdk-spike/evidence/binary-a-runtime-observations.json)
- [真实spawn结果](../output/sdk-spike/evidence/binary-b-spawn-observations.json)
- [保存ACK及不同工件结果](../output/sdk-spike/evidence/binary-a-writer-observations.json)
- [保存错误结果](../output/sdk-spike/evidence/binary-a-writer-error-observations.json)
- [原项目逐模块回归](../output/sdk-spike/evidence/regression/test-results.json)
- [执行记录与决策](../output/sdk-spike/progress.md)

原业务代码未动。本阶段的执行决定仅涉及独立scratch副本、现有编译器环境、禁用受限缓存和Nuitka专用加载验证；保留证据供用户审阅，不合并、不提交生产分支、不发布到外部。
