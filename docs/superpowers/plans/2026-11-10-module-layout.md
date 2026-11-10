# Module layout migration

按用户指定目录执行；修改留在当前工作区，不提交。

- control 保留 ControlCenter、PipelineRuntime、PlcCommunicationProcess、DataProcessWorker、DataProcessingProcess。
- model/runtime 接收健康监控、停止协调和根目录启动辅助、预览、部署检查模块；环境根路径改为项目根目录。
- model/telemetry 接收公共状态和状态收集器；model/pointcloud 接收点云文件、保存、缓冲和保存管理模块。
- model/lidar 接收采数进程和策略；model/utils 接收 ConfigurationService、MachineConfiguration。
- view/qt 接收 QtUiBridge、MachineConfigSchema。
- 根目录仅保留 main.py；构建入口为 python -m model.build_extensions build_ext --inplace。
- 删除无运行时引用的 model/plot 源码，移除编译项。
- 同步更新源码、测试的导入与模拟路径，以及当前用户文档。
- 检查 Windows spawn 导入、跨工作目录路径、参数配置路径、flake8、生产源码类型和测试；原有第三策略轴映射与旧配置测试问题单独报告。

根目录 CONTROL_TYPE、DATA_PATH、DATA_NAME 及 TOML 配置不做更改。
