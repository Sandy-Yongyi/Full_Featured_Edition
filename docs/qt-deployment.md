# Qt 版本部署检查与构建

生产入口为 `main.py`，空场预览入口为 `qt_preview.py`。`setup.py` 仅构建算法扩展，不生成 Qt 应用 EXE。

## 先进行只读自检

在 PowerShell 中运行：

```powershell
Set-Location -LiteralPath 'D:\Code\Full_Featured_Edition'
$qtPython = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe'
& $qtPython -B main.py --check-deployment
```

自检检查 10 份 TOML（包括三种策略的设备配置）、主要运行库导入、Qt 的 `qwindows.dll` 文件是否存在。配置语法或依赖检查失败时退出码为 1；通过时为 0。它不会构建控制器、启动 QApplication、创建工作进程、连接设备或导入项目文件日志器，也不会更改配置。

配置仍按现有 TomlLoader 的编码兼容规则读取。缺失文件和重复键逐项报告，不自动修复参数。自检不验证所有设备参数的业务语义、实际平台插件加载、OpenGL 上下文或现场通讯。

## Nuitka 独立目录构建

采用独立目录方式，配置与运行输出位于应用目录中；先不用单文件解压运行方式。源码自检和回归通过后，可在有 C/C++ 编译器的构建机运行：

```powershell
& $qtPython -m nuitka `
    --standalone `
    --enable-plugins=pyqt6 `
    --include-package=OpenGL `
    --include-data-dir=model/tomls=model/tomls `
    --nofollow-import-to=wx,wxgl `
    --windows-console-mode=force `
    --output-dir=dist/qt `
    main.py
```

这个命令保留控制台以便部署自检和诊断。中间文件和产物都在已被 Git 忽略的 `dist/qt` 下；编译会产生较多文件，不在应用启动或自检时自动执行。命令尚未经完整 EXE 构建验证。

部署时复制整个 `dist/qt/main.dist` 目录，保留其中的 Qt 插件、DLL 和 `model/tomls`，不能只复制 `main.exe`。配置包含现场地址、参数和操作密码，应使用目标设备所需配置。放置目录需要允许当前用户写入运行日志、采集数据和保存的设备参数。

## 产物验收

1. 在目标机器，从其他工作目录调用 `main.exe --check-deployment`，检查退出码及每项报告。
2. 普通启动 `main.exe`，确认单实例保护、中文参数、五个页面和配置读取；首次查看界面时不要点击设备启动按钮。
3. 现场分别验收三个策略、密码操作、安全停机、通讯异常、真实点云渲染及高 DPI。

当前只验证了源码环境中的自检和自动回归。实际构建、独立机器运行以及设备动作仍需完成验收。

## 可选真实显卡专项

在独立的新进程中运行（不与普通 offscreen 回归合并）：

```powershell
$env:QT_QPA_PLATFORM = 'windows'
& $qtPython -B -m unittest tests.check_qt_graphics -v
```

该检查不显示主窗口、不启动设备、不写图片或数据文件。它创建离屏 OpenGL 上下文，验证 VBO 上传、绘制、复用、更新和释放，并读回像素验证客户端数组绘制；同时检查 20 万合成点上传与绘制是否报错。输出实际驱动名称和一次测量耗时。

2026-10-29 在 AMD Radeon 890M / OpenGL 4.6 Compatibility Profile 上的 3 项专项通过。该检查使用 64×64 离屏缓冲，不能作为生产帧率、完整窗口资源回收或现场点云性能的验收结果。
