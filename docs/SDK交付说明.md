# SDK 0.1.0 交付说明

当前可交付候选为[20261113-102535-211086精简开发包](../output/releases/20261113-102535-211086/acquisition_sdk-0.1.0-developer-minimal-cp311-win_amd64.zip)：固定21声明入口，不含内部manifest；108文件哈希、运行导出、开放报文、spawn及部署自检通过。显式复用原已验收二进制，私有实现未变。SHA-256：`195f535a612b7dd985426d59618027c8d2519e29c81d19ea13b32bf680eeba3d`。15项SDK/布局/声明测试通过，脚本规范检查通过。

后续交付ZIP不再包含manifest.json；同名`.manifest.json`在ZIP旁作为内部验收证据保留，程序运行不依赖该文件。新编译二进制在本机加载时遇到应用控制策略拦截：编译成功不等于交付验收成功，默认一键流程会报错退出；不得将此候选当成已验收版本。原已验收二进制可在私有源码及版本未变化时显式复用，用于验证开放代码/文档交付。

后续默认交付规则已固化：`tools/sdk_public_api.json`保存已批准21入口及类方法集合；新增上层导入不能自动扩大声明。`tools/package_sdk.py`默认选择开发指南与精简声明；内部完整声明生成不作为默认交付。双击根目录release_sdk.cmd或运行`py -3.11 tools/release_sdk.py`，执行重新编译、精简打包和离线解压验收，输出到独立时间戳目录。只交付生成的ZIP；脚本及验收文件留在内部仓库。详细条件及复用二进制限制见根README“内部一键交付”。本变更不修改运行时导出或业务逻辑。

最新推荐项目开发交付为[精简声明开发包](../output/releases/acquisition_sdk-0.1.0-developer-minimal-cp311-win_amd64.zip)，命令 `python tools/package_sdk.py --developer --minimal-stub`。声明公开接口从40项缩减为当前开放代码直接导入的21项；必要关联类型以下划线命名保留，类方法按开放代码引用的成员名保守筛选，保留构造函数及数据字段。动态名称扫描存在局限，同名成员可能额外保留。运行时仍为原40导出，二进制和业务逻辑不变，精简声明不构成运行时隐藏。

精简版本新增两项声明契约测试，连同原SDK/目录测试共13项通过；Pyright零错误零警告，打包脚本规范检查通过，ZIP的108文件哈希、40运行导出、报文、spawn和部署自检通过。验收结果为output/releases/acceptance-result-developer-minimal.json。此前完整声明包保留作历史候选，不应误发为精简版。

适用环境：Windows x64、CPython3.11。交付包：

[acquisition_sdk-0.1.0-cp311-win_amd64.zip](../output/releases/acquisition_sdk-0.1.0-cp311-win_amd64.zip)

面向项目开发人员的中文指南版交付包：[acquisition_sdk-0.1.0-developer-cp311-win_amd64.zip](../output/releases/acquisition_sdk-0.1.0-developer-cp311-win_amd64.zip)。包含control/view/model、main.py、requirements.txt、pyd/pyi、manifest及独立README，不含docs/tools/tests/output或SDK私有源码。其README源文件为根目录README_DEVELOPER.md，覆盖十份TOML现有全部参数名、开发流程、架构和验收限制。

开发包验证：108文件哈希、40导出、公开报文、真实spawn和部署自检通过；README滤波示例通过，开放代码/配置与当前仓库逐文件字节一致。SHA-256：`00accb623f2632e5b96d07fe754c61ebb255e8de839c2c13444e1eed473b60a2`。证据：output/releases/developer-acceptance-result.json。开发包仅更换交付说明，SDK二进制版本和业务逻辑未变。

解压整个包，使用匹配的Python和第三方运行依赖，再运行 `python main.py`。本机已装依赖的验收环境与requirements范围差异见包内SDK_USAGE.md；依赖未捆绑，不能仅复制pyd到没有依赖的机器就运行。

上层开发从 `acquisition_sdk` 获取底层算法、进程和数据类型。报文使用 `model.MovingFrameData`，分枪使用 `model.gun_distributors`；其余公开工具、界面、控制和运动源码可直接查看和修改。配置仍为 `model/tomls`。

版本号通过 `acquisition_sdk.__version__` 查询，文件模块名不随版本改变。更新前退出应用和全部工作进程，备份旧pyd/pyi；替换匹配文件，保留项目定制源码和现场配置，再重启。回退时成对恢复旧pyd/pyi。不支持运行中热替换。

## 本轮最终验收

- 22个实现编译为单pyd，开放项目代码未编译。
- 原生产文件审计：业务AST变化0；main、配置、留存utils字节保持。
- 最新源码280项测试274通过，完整二进制274项268通过；剩余均为原有5项第三策略断言和1项旧配置字段错误，没有新增失败。
- 中文/空格路径、其他cwd、开放报文/工具/默认分枪变更，以及父/子进程生效已验证。
- 40导出类型声明经Pyright检查，0错误、0警告；原未注解信息保留Any。
- 最终ZIP的108文件哈希、40导出、公开报文、真实spawn、部署自检均通过。

## 明确保留的限制

- 第四阶段独立审阅现已补做，其构建范围校验发现已修复并回归，见[补充闭环](sdk-stage4-completion-2026-11-13.md)。
- 11个分枪文件已补96个合成用例迁移差分，输出一致；不代表真实工件样本或所有项目规则实机全覆盖。
- 已完成当前交付二进制的PLC实机只读通讯：三次142字节回包、20轴解析成功，控制帧零次，见[只读验收](sdk-plc-readonly-acceptance-2026-11-13.md)。尚未完成雷达/PLC实机全链路、长时间稳定性、独立机器或其他Python/架构验收。
- 用户于2026-11-13确认第三模式暂不用于现场；其实现和原配置保留。当前第三模式旧四设备配置与新20轴映射不兼容，未来现场启用前须完成布局适配及安全返回验证。相关五项失败及一项旧配置字段错误继续保留，见[根因记录](sdk-remaining-failures-diagnosis-2026-11-13.md)。本轮未改变其算法或配置来消除失败。
- 单pyd隐藏交付目录并提高逆向成本，不保证内部名称不可观察或算法无法逆向。

本包可用于团队集成和内部验收；生产上线需完成上述现场验收。测试和构建证据保存在开发仓库output下，不在交付ZIP内。

证据：[业务审计](../output/sdk-migration/audit-result.json)、[源码回归](../output/sdk-migration/regression/summary.json)、[二进制回归](../output/sdk-migration/binary-regression/summary.json)、[公开扩展验收](../output/sdk-paths/result.json)、[声明检查](../output/releases/stub-typecheck.json)、[ZIP验收](../output/releases/acceptance-result.json)。
