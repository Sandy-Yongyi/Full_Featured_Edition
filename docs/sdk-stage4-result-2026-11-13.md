# SDK 第四阶段正式迁移结果

2026-11-13：正式源码迁移及全量编译完成。完整发布包、接口声明和实机验收仍待后续阶段。

## 已完成

- 22个私有实现迁入 acquisition_sdk/_internal，统一 acquisition_sdk 延迟导出40个支持对象。
- PLC报文及原值协议常量公开在 model/MovingFrameData.py；11个分枪实现集中在 model/gun_distributors。
- FrameQueueManager、PointsFileUtil分别迁入私有formats、pointcloud；其余utils保持原路径和字节。
- 旧五个私有源码目录及逐文件构建入口移除，构建入口改为 tools/build_sdk.py。
- model/tomls、main.py设置、其余公开工具保持，未修复或调整业务算法。

## 验证

| 项目 | 实测结果 |
| --- | --- |
| 原181文件审计 | 114份字节一致、55份排除import/协议常量归属后AST一致、12份明确布局变化；业务AST变化0 |
| 保护文件 | 27份main/requirements/配置/留存工具等字节一致 |
| 源码回归 | 279项：273通过、5失败、1错误；无新增失败 |
| 完整编译 | 22实现加11包初始化，精确33模块；118.969秒成功 |
| 无私有源码回归 | 完整pyd配公开上层，274项：268通过、5失败、1错误；无新增失败、无超时 |
| 加载与接口 | 实际加载完整pyd、40个导出均可获取、开放报文保持源码，运行搜索路径不含原SDK源码 |

两项原布局/构建失败随正式布局更新解决。剩余5项连续双向运动规划断言及1项旧配置字段错误与基线相同，未删除断言或修改现场配置。三策略相关采数保存、TXT回放、进程组合、真实spawn/保存回归继续通过，但不能替代硬件全链路验收。

## 使用

```powershell
python main.py
python -m tools.build_sdk --inventory
python -m tools.build_sdk --developer-env
```

开发目录使用SDK源码；输出完整扩展位于 output/sdk-full。不要将源码包与扩展混合放置进行交付验收。修改开放报文、分枪及工具后重启使用；修改私有实现后重新编译。

## 审阅与限制

首次独立审阅因额度限制未完成，现已补做，并修复构建范围校验发现；补充96个分枪差分用例、原件哈希审计和完整回归。最新状态见[第四阶段补充闭环](sdk-stage4-completion-2026-11-13.md)。

原设备问题、完整类型声明、正向发布包、公开扩展逐规则差分、独立机器和现场验收仍需后续完成。当前runtime目录包含测试，仅用于验证，不是交付包。

## 证据

- [迁移与原件映射](../output/sdk-migration/migration-map.json)
- [AST及字节审计](../output/sdk-migration/audit-result.json)
- [源码回归](../output/sdk-migration/regression/summary.json)
- [完整编译](../output/sdk-full/build-result.json)
- [二进制回归](../output/sdk-migration/binary-regression/summary.json)
- [完整扩展](../output/sdk-full/acquisition_sdk.cp311-win_amd64.pyd)
- [无源码运行元数据](../output/sdk-migration/binary-metadata.log)
