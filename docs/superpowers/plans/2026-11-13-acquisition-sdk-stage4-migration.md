# Acquisition SDK Stage 4 Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Execute inline and retain the evidence ledger. The user confirmed stage 4 and chose the current sdk_package branch.

**Goal:** 将已确认的22个实现正式迁入SDK，开放报文/分枪与上层继续运行，业务计算体与配置保持。

**Architecture:** acquisition_sdk使用第三阶段验证过的延迟导出和私有子包；MovingFrameData移至model根、分枪集中model/gun_distributors；其余公开工具保留原路径。建立原件快照、AST和字节差异审计，再迁移引用并全量编译检查。

**Tech Stack:** CPython3.11、Nuitka2.5.9、现有VS开发环境、unittest、AST/哈希、spawn。

**Spec:** [已确认设计](../specs/2026-11-12-acquisition-sdk-design.md)、[第三阶段结果](../../sdk-stage3-result-2026-11-13.md)。

## Global Constraints

- 当前sdk_package分支执行，用户已明确选择；不创建worktree、不自动提交或合并。
- 22个实现：lidar4、plc2、dataprocess7、formats4、pointcloud5；不得额外编译公开代码。
- MovingFrameData及START/END/ReadCommon开放；分枪全部开放；FrameQueueManager和PointsFileUtil按确认规则迁入。
- model/tomls十份配置、main.py设置、其余13个utils实现及全部业务计算体不改。
- 只改模块/import与协议常量归属；基线业务失败不顺便修复。
- 不安装升级依赖；编译使用第三阶段已验证的现有VS环境与禁用ccache参数。
- 完整类型声明、发布包、正式版本升级和实机验收仍属于后续阶段。

## Review Focus

- 上层公开import不能引用_internal；真实实现测试允许私有路径。
- 两种AxisData不能混用；开放报文保持同一个类身份。
- 新建包不能导致冷导入日志/设备或循环导入；Task1/3验证。
- 迁移时函数体不得变动；Task2独立AST审计与原文件快照验证。
- 旧位置残留pyd/pycache不能遮蔽新源码；Task2显式清单移除旧源文件，只清理已核对的旧路径。

### Task 1: 接口和迁移约束测试

Files: 新建 tests/test_sdk_contract.py；修改tests/test_module_layout.py的布局契约（不改业务断言）。
Interfaces: acquisition_sdk公开对象、model.MovingFrameData、model.gun_distributors.GunDistributor；tools.build_sdk.get_private_sources()返回22个Path。

- [x] 写冷导入、两种类型身份、开放导入、22源清单、旧五包无源文件和上层无私有import测试。
- [x] 运行并确认SDK/构建工具缺失导致失败。
- [x] 保存output/sdk-migration/before中的原始源码/配置/测试字节及SHA-256，记录基线273项的8个既有不通过项。

### Task 2: 机械迁移与业务等价审计

Files: 新建acquisition_sdk/__init__.py及_internal下22个实现/必要__init__.py；model/MovingFrameData.py、model/gun_distributors/*.py；更新control、motionplan及相关测试import；替换根build_extensions.py为tools/build_sdk.py。
Interfaces: 公开对象和别名严格按设计；原函数参数/返回/运行属性保持。

- [x] 迁入22实现；三协议常量以原字节值搬到开放报文；11分枪实现集中开放目录。
- [x] 内部引用统一SDK私有路径，公开生产引用统一SDK门面/开放报文/开放分枪；不保留原五包兼容源码。
- [x] 测试的实现import、patch字符串和__module__布局预期适配，业务断言保持；构建清单布局测试按22源契约更新。
- [x] 审计原有每个生产模块（包括公开control/motionplan/分枪）：排除import和三常量归属后AST相同；main.py/十配置/留存utils字节相同。记录文件搬迁表和差异。
- [x] 实现构建工具：--inventory只读验证精确22源；--developer-env --output-dir输出单pyd及精确编译XML模块集合，不编译model/control/view。
- [x] 运行Task1测试，预期通过；发现循环或导入错误仅修正机械映射，不改业务。

### Task 3: 回归、全量编译及阶段交付

Files: 复用/适配独立output下审计和测试工具；新建docs/sdk-stage4-result-2026-11-13.md；更新README/docs/module-layout.md的实际入口。
Interfaces: 现有应用入口和CONTROL_TYPE保持；完整SDK类型与数据行为保持。

- [x] 新增明确三策略工厂映射检查，原三策略/两原点保存与进程组合测试继续通过。
- [x] 全部现有测试逐模块运行；布局原有2项问题由新布局修复，第三策略5项/旧字段1项业务不通过仍逐项记录，不能新增回归。
- [x] 全量22源Nuitka编译；报告模块集合等于SDK源集合，公开代码没有进入二进制。
- [x] 在独立运行目录用完整pyd、公开model/control/view、配置运行关键契约、真实spawn/保存及原测试的代表性路径，不使用私有SDK源码回退。
- [x] 独立只读审查本阶段差异，修复影响范围内的问题并完整复验；不把原有业务缺陷混入迁移。
- [x] 记录实测/未测、文件迁移与审计结果；第四阶段完成后等待下一阶段确认。

验证以本机解释器执行unittest及tools/build_sdk.py；证据位于output/sdk-migration。阶段实施已由用户授权，无需逐文件再确认。
