# Acquisition SDK Stage 3 Compatibility Spike Implementation Plan

执行状态：已于2026-11-13完成，见[实测报告](../../sdk-stage3-result-2026-11-13.md)。独立审查补强了队列直接写入、不同工件/ACK竞态、白名单和证据审计；原产品源码未修改。报告日期以实际完成日为准，原计划中的2026-11-12报告文件名相应改为2026-11-13。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in the current session. Steps use checkbox (`- [ ]`) syntax for tracking. This is a disposable compatibility spike, not the production migration.

**Goal:** 在不修改现有业务源码的前提下，证明单个 .pyd、开放工具/报文、三策略队列类型和 Windows spawn 的代表性组合可运行，或给出可复现的具体阻碍。

**Architecture:** 在 output/sdk-spike/ 内创建独立源码副本、编译目录和干净运行目录，只复制代表性实现与公开依赖。私有模块只改导入，PlcCommon 的三个协议常量在副本中搬到开放报文；原项目源码不搬迁、不改算法。源码参考与二进制分别在新进程中验证，不让原仓库目录进入二进制运行的 sys.path。

**Tech Stack:** CPython 3.11.0 Windows AMD64、Nuitka 2.5.9、现有 MSVC/Windows SDK、unittest、multiprocessing spawn、NumPy；不连接设备，不安装或升级全局依赖。

**Spec:** [已确认设计](../specs/2026-11-12-acquisition-sdk-design.md)，[utils 范围](../../sdk-utils-scope-2026-11-12.md)，[基线](../../sdk-stage1-baseline-2026-11-12.md)。

## Global Constraints

- 最终范围为 22 个实现：lidar 4、plc 2、dataprocess 7、formats 4、pointcloud 5。当前阶段仅做代表性试验，不声称全部 22 个已经完成编译。
- MovingFrameData.py、分枪、control/view/motionplan 以及除 FrameQueueManager/PointsFileUtil 之外的 utils 保持开放；不能编译或复制成隐藏实现。
- 配置保留 model/tomls，内容不变；当前 main.py 开发设置不变。
- 固定导入 acquisition_sdk，版本 0.1.0，SDK_API_VERSION=1，不在模块基名增加业务版本后缀。
- 不更改业务计算体、状态机、默认值、异常行为、PLC 报文值、队列和保存语义；副本仅允许路径/import 与协议常量归属适配。
- 真实运行的进程仅为测试 worker/保存 worker；不启动现场采数或 PLC 进程，测试入口禁止外发设备网络。
- 基线已知 6 失败、2 错误原样记录；不在试验中修复，不删除测试或扩展现有功能。
- 不调用旧 build_extensions.py，不创建生产 SDK 目录，不删除或覆盖现场文件；scratch 文件操作校验绝对路径均位于 output/sdk-spike/。
- 不自动下载编译器、不自动安装/升级 Nuitka；若本机组合不支持，记录阻碍并等待路线确认。

## Review Focus

1. 开放报文先导入/后导入都应使用同一编译基类，避免延迟导出与循环导入失效：Task 1/2 双顺序测试。
2. .pyd 看似能导入，但 spawn 在无源码环境下找不到嵌套类：Task 3 真实队列往返与真实编译保存进程。
3. 编译器悄悄纳入公开工具或报文，导致修改不生效：Task 2 编译报告检查与同一二进制外部源码变更测试。
4. 假 __file__ 或系统搜索路径让测试意外读取仓库源码：Task 2 运行目录文件清单、模块来源和 sys.path 审计；不能只检查 __file__。
5. FrameQueueManager 的三策略在编译后仍可被开放层读取/修改原属性：Task 1/3 三策略固定输入差分，保持帧字段、None 和队列顺序。

---

## 执行环境与文件结构

已只读核对：解释器为 `C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe`；MSVC 工具位于 VS 18 Community，版本 14.51.36231；Windows SDK 10.0.26100.0。Nuitka --help 支持 module/include-package/nofollow-import-to/msvc/report。这只说明工具存在，不证明旧 Nuitka 支持当前 MSVC。

当前仓库为普通 checkout，当前分支 sdk_package。本试验的隔离方式为创建自包含 scratch 源码/运行副本，不在生产源码上实施，不需要先创建 Git worktree。正式产品开发前再按 using-git-worktrees 技能检查隔离方式和用户偏好，不因试验计划擅自切换分支。

```text
output/sdk-spike/
    prepare.py                  # 清单复制、导入适配、AST/哈希证明
    build.py                    # 固定解释器调用 Nuitka、记录编译报告
    validate.py                 # 模式选择、隔离运行、汇总
    checks/
        __init__.py
        test_contracts.py       # 报文/队列固定输入与公开扩展
        test_spawn.py           # 真实 spawn 及保存
        test_isolation.py       # 冷导入、来源、公开依赖排除
    source/                     # 改造副本，不是原仓库
        acquisition_sdk/
        model/utils/
        model/MovingFrameData.py
        model/tomls/
    build/                      # C、编译日志、XML，不进入运行目录
    run-a/                      # .pyd + 公开源码 + 配置，无 SDK 源码
    run-b/                      # 同一 .pyd，公开报文/工具测试变体
    evidence/                   # JSON、运行日志、参考结果、清单
docs/sdk-stage3-result-2026-11-12.md
```

代表性私有副本共 9 个：PlcFrame、PlcCommon、AxisFrameDataFormat、BlockDataFormat、FrameQueueManager、PointCloudSaveBuffer、PointCloudSaveProcess、PointCloudSaveService、PointsFileUtil。保留原相对子目录对应关系。正式采数、整件识别、分枪和运动算法不在本阶段搬迁。

公开副本为 model/__init__.py、model/utils/__init__.py 与除两个待迁移文件外的 13 个 utils 实现、开放 MovingFrameData，以及十份配置。配置和公开工具副本按字节复制；报文副本仅改基类 import 并添加三个原协议常量。测试变体只能改 run-b，不能改 source 或现场源文件。

## Task 1: 建立代表性源码试验与可检查的参考结果

**Files:** Create output/sdk-spike/prepare.py、validate.py、checks/__init__.py、checks/test_contracts.py、checks/test_isolation.py；生成 source/ 与 evidence/。不 Modify 原 model/control/view/tests/main。

**Interfaces:**
- prepare.py 消费仓库原文件，命令参数 `--repository <absolute-path> --workspace <absolute-path>`；只允许 workspace 为本仓库 output/sdk-spike。
- 生成 evidence/source-manifest.json：每个原文件/副本路径、原字节哈希、改写后哈希和改写类别；没有未经声明的副本改写。
- validate.py 接受 `--mode source|binary --workspace <absolute-path> --suite contracts|isolation|spawn|all`，输出日志和 JSON，任何测试失败退出非零。
- 参考输出为 evidence/reference.json：三个队列策略的可序列化状态、报文字节十六进制、公开对象字段；类型身份另列，不通过丢弃字段掩盖差异。

- [x] Step 1：记录原 181 个源码/测试/配置当前哈希，确认与第一阶段基线相同；若用户期间改动，先记录新基线并报告，不能覆盖修改。
- [x] Step 2：编写最小 validate.py 测试启动器及 test_contracts.py 的报文与队列断言，暂不生成试验 SDK；约束：`sdk.__version__ == '0.1.0'`、`sdk.SDK_API_VERSION == 1`；`BlockData is type(BlockData())`；开放 Send/Receive 原帧 `len(to_bytes()) == 134`，20 个 AxisData；to_bytes 与明确 struct 字段顺序相同，from_bytes 字段往返保持。
- [x] Step 3：编写三策略队列输入断言：逐帧 stack_size=3，依次 push 帧 A/B 后顺序为 B/A/空帧，repeat_count=2 后前两项保持原重复语义；整件队列使用有效 BlockData 先插入索引0，修改原对象不改变已深拷贝项，shift 后尾项为 None；连续策略初始化三个 None 位，整趟写入位0且非空位拒绝覆盖。以初始 plc_status=0 写入，依次更新状态 `4, 8, 16, 32, 64`，对应第0位放行完成、第1位到位、第1位放行完成、第2位到位、第2位放行完成，返回掩码依次为 `0, 4, 0, 8, 0`，点云按 0→1→2→清空。另测启动时完成位为1须先降0再升1，防止旧反馈误确认。
- [x] Step 4：编写 test_isolation.py 的源模式冷导入断言：版本与纯数据/PlcFrame 导入不加载 LoggerUtil/Open3D，不创建日志和进程；两种独立进程顺序 `model.MovingFrameData → sdk.PlcManager` 与 `sdk.PlcManager → model.MovingFrameData` 均能解析同一 ReceiveMovingFrameData。
- [x] Step 5：运行尚未准备副本的源模式，确认因缺少 trial acquisition_sdk 而失败；失败原因不能是测试语法错误或误用现场源码。
- [x] Step 6：实现 prepare.py。只复制清单内文件，重写内部 import；SDK 门面使用延迟导出；公开 utils 不改动。PlcCommon 的 START/END/ReadCommon 从副本搬到 model/MovingFrameData，字节值不变，内部引用外部报文类。不得改函数计算体、默认值和签名。
- [x] Step 7：记录 AST 等价检查：除 import 节点和三常量所在模块外，9 个私有副本与原文件对应 AST 相同；公开配置/工具字节相同。测试夹具预先故意改变一个副本的业务数值时，该审计必须失败；恢复副本后审计通过。
- [x] Step 8：运行 source contracts/isolation，通过后保存 reference.json。若原实现对夹具存在既有错误，先修正夹具的项目假设，不修改原算法；若需改变业务预期，记录为阻碍并停在本任务。

验证命令（以下 `$sdkPython` 仅为 PowerShell 本地变量）：

```powershell
$sdkPython = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe'
& $sdkPython -B output/sdk-spike/prepare.py --repository $PWD.Path --workspace (Join-Path $PWD 'output/sdk-spike')
& $sdkPython -B output/sdk-spike/validate.py --mode source --workspace (Join-Path $PWD 'output/sdk-spike') --suite contracts
& $sdkPython -B output/sdk-spike/validate.py --mode source --workspace (Join-Path $PWD 'output/sdk-spike') --suite isolation
```

期望退出码均为0，且参考结果与 AST/哈希证据存在。这是源码副本参考，尚不证明二进制成功。

## Task 2: 单 .pyd、公开源码依赖及无私有源码运行

**Files:** Create output/sdk-spike/build.py；扩展 test_isolation.py/test_contracts.py；生成 build、run-a、run-b。

**Interfaces:**
- build.py 参数 `--workspace <absolute-path>`，固定使用 sys.executable 调 Nuitka，stdin=DEVNULL，输出 evidence/build-result.json，记录完整参数、版本、耗时、退出码、产物 SHA-256 和报告位置。
- run-a 只能来自正向清单：一个 acquisition_sdk*.pyd、公开 model 包及 model/tomls。不复制源码 acquisition_sdk、旧五包、C、build 缓存或测试副本。
- validate.py 二进制模式通过 `-I -B` 新进程运行 checks；测试入口显式添加 run-a 和 checks 路径，不能添加仓库根、source、build，不能通过 PYTHONPATH 回退。

- [x] Step 1：在没有编译产物时运行 binary isolation，断言失败点为“没有可加载的 .pyd”，证明不能回退源码获得绿灯。
- [x] Step 2：实现 build.py，优先用已装 MSVC。Nuitka 参数：`--module acquisition_sdk --include-package=acquisition_sdk --nofollow-import-to=model --nofollow-import-to=control --nofollow-import-to=view --msvc=latest --jobs=2 --output-dir=<workspace>/build --report=<workspace>/evidence/compilation-report.xml`；cwd 为 source。不得使用 assume-yes-for-downloads。编译日志写文件，持续报告有意义的进展。
- [x] Step 3：若当前 MSVC 与 Nuitka 不兼容，记录具体编译器检测错误和命令。可以核对本机已有 vcvars64 环境是否解决检测，但不得安装工具、修改注册表或升级包；无法用现有环境编译则以阻碍报告结束试验，不能改成源码加载宣称通过。
- [x] Step 4：编译成功后生成 run-a 清单，解析 XML 检查没有 model/utils、model/MovingFrameData、control、view、motionplan、gun_distributors 的编译实现；导入记录可以存在，但编译/嵌入实现不得存在。检查 run-a 仅一个自有 .pyd，无私有 .py/.pyc/.pyx、旧五包或源码包。
- [x] Step 5：运行 binary contracts/isolation，对比 reference.json，检查所有公开工具和报文来源为 run-a 的 .py，SDK 加载器为原生扩展；内部模块即使提供模拟 .py __file__，也不能据此误判源码来源。记录 sys.path、spec loader 和真实文件清单。
- [x] Step 6：测试先报文/先PlcManager两种导入顺序；用开放 dataclass 增加独立测试帧，包含 Int16/UInt16/Int32/UInt32/Float32/FixedStr/Repeat 及嵌套帧，固定输入按 struct 字节和 get_type_hints(include_extras=True) 验证。不修改当前项目帧字段。
- [x] Step 7：复制 run-a 正向清单到 run-b，保持 .pyd SHA-256 相同。只在 run-b 的公开报文模块添加测试帧并替换测试帧头尾/读命令，fake socket 验证解析与发送确实使用新外框；无真实网络连接。
- [x] Step 8：只在 run-b 的开放 StrategyUtil 测试副本中增加一个返回固定标记的可控 wrapper，三策略原逻辑不改。新进程创建 SDK FrameQueueManager 时能观察该外部函数调用/标记，证明工具未被嵌入；run-a 行为不变。不能用预先向 sys.modules 注入替身代替磁盘源码变更。
- [x] Step 9：确认 run-a/run-b 二进制哈希完全一致，保存变更前后公开文件哈希与结果。证据中不打印完整现场配置或密码。

验证：`& $sdkPython -B output/sdk-spike/build.py --workspace (Join-Path $PWD 'output/sdk-spike')`，随后 validate.py 的 binary contracts/isolation；成功要求退出码0、参考一致、外部变更生效且二进制不变。只产生一个 .pyd 不足以通过本任务。

## Task 3: 真实 spawn、保存资源及阶段报告

**Files:** Create output/sdk-spike/checks/test_spawn.py；扩展 validate.py；Create docs/sdk-stage3-result-2026-11-12.md。

**Interfaces:**
- 真实 worker target 定义在测试入口的顶层，使用 multiprocessing.get_context('spawn')，不使用 lambda/nested target；测试入口的网络禁用与运行路径设置也在子进程导入阶段生效。
- spawn 结果包括 worker exitcode、队列类型/字段摘要、ACK、输出清单；加入 evidence/validation-result.json。超时或子进程非零必须让父测试失败。
- 产出阶段报告列每一检查为通过/失败/未执行，保留工具限制，不升级成正式 SDK 完成声明。

- [x] Step 1：为真实 spawn 测试准备固定数据：AxisFrameData/FrameAxisData、嵌套 BlockData/InsideData/SubInsideData、开放 SendMovingFrameData/ReceiveMovingFrameData、numpy float64 点云。断言子进程往返字段、数组、类型身份和 deepcopy 后独立性，父/子只使用同一 run-a 二进制与公开源码。
- [x] Step 2：加入三个 FrameQueueManager 策略的子进程创建/调用，使用 Task1 相同输入，全部摘要与 reference.json 一致；验证公开 frame_stack/queues 属性可读写，原方法可调用。
- [x] Step 3：在 run-a 启动真正编译的 PointCloudSaveService.worker。使用小共享内存池和临时目录，提交两份不同工件任务；检查保存进程 ready、ACK job_id/blocks 匹配，旧待保存块不被覆盖，正常 drain 返回空错误且 worker exitcode=0。
- [x] Step 4：保存夹具覆盖相对 Z 回绕与 absolute_sorted，TXT 与 NPY 各跑一次；输出点数、顺序、TXT 原精度及 NPY float64 值与源模式参考一致；成功才有 .complete.json，不遗留 .part。预览处理与保存数据不混淆。
- [x] Step 5：加入可控写盘失败夹具，必须收到错误，不能出现成功完成清单/错误ACK；保留原失败语义，不吞掉编译进程异常。finally 按原 abort 语义退出试验 worker、关闭队列和共享内存；不操作非本次创建的进程或目录。
- [x] Step 6：运行 source 和 binary 的 spawn suite，先有 source 正向参考，再比 binary。同一二进制 run-b 下的开放报文/工具变更也做一次新 spawn 验证，确认不是仅父进程生效。
- [x] Step 7：执行完整试验 `validate.py --mode binary --workspace <...> --suite all`，单模块超时120秒；若长时间阻塞，记录模块名，终止本次创建的进程树后报告失败，不能留后台试验进程。
- [x] Step 8：重新计算原181文件的哈希，配置和保留工具未变化；生成 evidence/final-manifest.json，记录 pyd 与副本依赖来源、9个代表性模块和未覆盖的13个正式实现。
- [x] Step 9：写阶段报告和更新计划勾选项。若通过，只结论“代表性技术路线可行”；列出尚未迁移/编译全部22个、尚无正式.pyi/发布包、尚未三策略实机/全链路验证。若失败，列出最小复现命令、错误、已尝试的本机环境和建议下一步，等待用户确认，不擅自切换到别的架构。

验证命令：

```powershell
& $sdkPython -B output/sdk-spike/validate.py --mode source --workspace (Join-Path $PWD 'output/sdk-spike') --suite spawn
& $sdkPython -B output/sdk-spike/validate.py --mode binary --workspace (Join-Path $PWD 'output/sdk-spike') --suite all
```

期望退出码0，全部 worker 已退出，比较结果一致且原源码哈希未变。报告审核后暂停，用户确认才进入第四阶段正式开发计划。

## 计划自检与执行方式

本计划覆盖设计第三阶段要求及用户新增的 FrameQueueManager/PointsFileUtil 范围；全部22个的正式迁移、全功能差分、开放分枪/运动修改验证、完整类型声明和版本发布属于后续阶段，不混入本试验。

建议由当前会话执行者依序实施三个任务，理由是它们共享同一试验副本、参考输出和二进制，无需并行改写共同状态。独立审阅可在阶段结果后检查证据；本阶段不自动提交scratch产物或修改生产分支。计划经用户确认后开始执行。
