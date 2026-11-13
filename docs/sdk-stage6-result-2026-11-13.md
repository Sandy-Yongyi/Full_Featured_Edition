# 第六阶段：0.1.0发布产物

已生成CPython3.11 / Windows AMD64版本包，包含完整22实现的单个pyd、acquisition_sdk.pyi、开放model/control/view/main、原配置、依赖说明和SHA-256清单。共108个受清单保护文件，另有manifest自身。

不包含私有SDK源码、原五个底层目录、测试、C文件或构建缓存。保留开放MovingFrameData、全部分枪规则、其余utils和model/tomls。第三方Python包及原生依赖未捆绑，须在目标环境安装；requirements原范围与实际测试版本差异在SDK_USAGE中说明。

声明覆盖40个SDK导出及原类方法、构造参数、数据字段和构造中声明的实例属性。原源码未提供类型的信息保留Any，没有猜测算法参数；声明经AST语法及导出覆盖检查，尚未完成独立静态类型检查器验收。

实测从ZIP解压后：108文件哈希一致，40导出可获取、公开报文134字节、真实spawn传递SDK类型成功；main.py --check-deployment通过。未用私有源码回退。

本阶段没有更改业务算法或现场配置。既有六项业务测试问题、第四阶段独立审阅未完成、实机和独立机器验收限制仍保留。此为内部验收候选包，不代表所有业务已通过生产验收。

- [版本包](../output/releases/acquisition_sdk-0.1.0-cp311-win_amd64.zip)
- [类型声明](../output/releases/acquisition_sdk-0.1.0-cp311-win_amd64/acquisition_sdk.pyi)
- [清单](../output/releases/acquisition_sdk-0.1.0-cp311-win_amd64/manifest.json)
- [解压验收结果](../output/releases/acceptance-result.json)
- [打包工具](../tools/package_sdk.py)

下一阶段：最终交付审查、完整发布声明静态检查、开放扩展和所有规则的进一步差分及实机待验收清单。
