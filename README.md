# PolaMV Studio

用于海康 MV-CH050-10UP 的 Windows 偏振图像采集与定量分析软件。按 `docs/requirements-v1.0.md` 实现，提供真实 MVS 相机和明确标注的模拟相机两种入口。

**下载与安装**：从 [Releases](https://github.com/DianaAvaNina/PolaMV/releases) 下载 `PolaMV-1.0.0-Windows-x64-offline.zip`（不要选择自动生成的 Source code 压缩包）。软件已包含官方 SDK 原生运行库、USB 驱动安装文件和应用运行环境，无需单独安装 Python 或完整 MVS。第一次使用真实相机需运行包内 `First-use-Install-USB-Driver.cmd` 并确认管理员权限。详见 [新电脑使用说明](docs/offline-setup.md)。当前版本为预发布版。

## 启动

下载离线包后完整解压，双击 **PolaMV Studio.exe**，应保留旁边完整的 `_internal` 文件夹，不要只复制 exe。源码开发或本机构建后也可双击项目目录中的 **Start-PolaMV.cmd**；Git 仓库不包含 `.venv`、`dist` 或离线 ZIP。

1. 相机通过 USB 3.0 连接电脑，关闭可能占用设备的 MVS 官方客户端。
2. 点击「搜索相机」，选择真实设备，再点击「打开」「开始采集」。未接硬件时选择「模拟相机」。
3. 在 RAW / Gray / AoLP / DoLP 页面切换；滚轮缩放，拖动平移，「适应」和「1:1」恢复视图。
4. 鼠标指向图像时右侧显示同一帧的 RAW、Gray、AoLP、DoLP，展开查看四方向强度与 Stokes。
5. 点击直方图切换总体 Gray 和四方向原始采样分布。
6. 「软件设置」可设置保存目录、文件名前缀、AoLP 最低 DoLP 阈值、色图、NaN 颜色及同步缩放。
7. 「保存当前显示帧」保存当前页面对应的完整定量数据，不是窗口截图或缩放后的图像。

## 触发

- 连续采集：Trigger Mode = Off。相机支持时选择 Acquisition Mode = Continuous。
- 软件触发：Trigger Mode = On，Trigger Source = Software，开始采集后点击「软件触发」。
- 外部触发：Trigger Mode = On，选择实际输入线路，按实验设置边沿、延时、去抖、缓存和每次触发帧数。
- 节点选项、范围和可写状态从相机动态读取，不支持的功能不显示。改变选择器后刷新关联节点。
- 参数修改会停止并恢复采集；外部触发实验应先配置参数，再开始施加信号，修改期间不承诺接收触发。
- 等待触发是正常状态，不作为断线。断线、SDK 错误和保存错误显示在右侧日志及状态栏。
- 外触发自动保存捕获**接收到该帧时选定的页面和算法设置**，软件触发与连续采集不会触发自动保存。模拟模式提供「模拟一次外部信号」按钮。

## 定量规则

- 采用同偏振方向、位置感知双线性插值；原始测量格点保持原值，边界钳制到同方向最近的有效采样位置。
- 参考传感器排列为左上 `90°`、右上 `45°`、左下 `135°`、右下 `0°`。
- `Gray=(I0+I45+I90+I135)/4`，`S0=2*Gray`，`S1=I0-I90`，`S2=I45-I135`。
- `AoLP=atan2(S2,S1)/2`，水平向右为 0°，逆时针为正，范围 `[-90°,90°)`。
- `DoLP=sqrt(S1²+S2²)/S0`；按照 V1.0 的 0～1 输出范围，对噪声/插值造成的大于 1 的结果裁剪到 1，此规则记入 TIFF 元数据。
- `Gray<0.02*(2^bits-1)` 时 AoLP 与 DoLP 均为 IEEE NaN，Gray 保持有效。
- 可选最低 DoLP 阈值仅把 AoLP 设为 NaN，默认关闭。
- Mono10Packed 与 Mono10p、Mono12Packed 与 Mono12p 是不同的像素格式编码，分别识别并无损解包为 uint16，保留原始有效位深，不会先降成 8 bit。旧式 Packed 解包采用 Numba，并在开始采集前预热。
- RAW / Gray 保存 uint8 或 uint16，Gray 四舍五入；AoLP / DoLP 保存 float32，单位分别为度和 0～1 比例。所有定量图 TIFF 为单通道。
- TIFF ImageDescription 包含帧号、接收时间、设备时标、像素格式、曝光/增益读回值、触发参数、算法规则和无效阈值。设备不提供逐帧 Chunk 时，曝光/增益是接收时主机读回值，并明确标记来源；自动曝光变化时不能将其当作严格的逐帧曝光水印。

## SDK 与依赖

开发与实机验证使用 **MVS 4.3.0 build20231128**，默认安装位置为 `C:/Program Files (x86)/MVS`。项目使用官方 Python 声明和 Windows 64 位运行时。2026-09-29 已在开发电脑恢复官方 USB 驱动绑定并完成部分实机测试；未更新相机固件。

2026-09-28 尝试从 [海康官方下载中心](https://www.hikrobotics.com/cn/machinevision/service/download/) 获取新版安装包，服务器返回 HTTP 403 拦截页，因此**未下载新的 MVS 安装包**。2026-09-29 离线包复用本机官方安装的 SDK，原生 DLL 和原始驱动文件随包携带，来源和许可文件保留在包内。发布版强制加载包内 SDK；源码开发仍可通过 `MVS_HOME` 指向本机 MVS。

应用采用 Python、PySide6 / Qt 6、NumPy、Numba 和 tifffile。依赖安装在项目 `.venv` 内，不修改全局 Python 环境。完整版本记录在 `requirements-lock.txt`。

## 性能和队列

采集、偏振计算、GUI、TIFF 写入分离。Numba 计算释放 Python GIL，允许接收线程继续工作。无自动保存时，处理保留最新预览原始帧，被替代的预览帧在状态栏明确计数。外触发自动保存队列和磁盘队列各限制为 4 帧；无法跟上时明确报告未保存帧号并停止接收。不能保证任意触发频率下无丢帧，应按磁盘性能和实际处理能力设置触发频率。

全分辨率计算基准见 `docs/benchmark.json`。基准包含四方向插值、偏振计算及五组直方图，不包含 USB 传输、显示和磁盘。相机采集不人为限制为处理帧率，但本机 CPU 尚未证明可对每帧执行 74.1 fps 全分辨率处理。

## 实机验证与待验收项目

2026-09-29 在 MV-CH050-10UP（2448×2048）上通过真实连接、曝光/增益读写、五种像素格式采集、五次软件触发以及 RAW / Gray / AoLP / DoLP 的 TIFF 保存检查。独立接收短时测试中 Mono8 约 74.2 fps，Mono10、Mono10Packed、Mono12、Mono12Packed 约 38.1 fps，最后一轮未观察到帧号缺口。

完整界面测试（Mono12）约接收 26.6、处理 25.3、显示 8.4 fps，并有帧号缺口，不能保证全帧率处理或无丢帧。场景为暗场，偏振结果按 2%FS 规则为 NaN；这些检查不能证明实际偏振测量精度。

仍待验证：Packed 解包与独立原始 DN 基准对比、外部线路电平/边沿/延时及硬件外触发自动保存、长时间稳定性、独立干净系统部署、实际偏振阵列位置与 AoLP 正负号。测试记录见 [verification.md](docs/verification.md)。

必须用已知方向线偏振片对 0°、+45°、−45°、90° 核对实际相机输出。当前排列是参考定义，不属于已完成的相机标定；也没有增加用户明确排除的标定模块。若相机在官方软件中预先修改了 ROI、Binning、Decimation 或翻转，本版不禁止这些设置，但固定阵列定义可能不适用；本版 GUI 不提供这些图像几何节点。

具体步骤见 `docs/hardware-acceptance.md`。

## 开发与构建

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt pytest pyinstaller
.\.venv\Scripts\python.exe -m pytest -q tests
.\Build-PolaMV.ps1
```

打包后的离线自检：

```powershell
& '.\dist\PolaMV Studio\PolaMV Studio.exe' --self-test '.\build\packaged-selftest'
```

结果写入该目录的 `result.json`，同时生成四种 TIFF 和窗口图片。正常运行时设置与日志位于 `%LOCALAPPDATA%/PolaMV`。首次处理需编译计算内核，可能等待数秒；后续使用缓存。

## 目录

- `polamv/camera.py`：真实 SDK 与模拟设备。
- `polamv/processing.py`：定量插值、偏振与直方图。
- `polamv/pipeline.py`：有界并发处理和保存。
- `polamv/display.py`、`polamv/gui.py`：图像交互和中文界面。
- `polamv/storage.py`：设置、唯一命名、定量 TIFF 与元数据。
- `tests`：数值、文件、触发流程及 GUI 测试。
