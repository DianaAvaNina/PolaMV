# PolaMV Studio 离线版：新电脑使用说明

支持 Windows 10 / Windows 11 **x64**，不适用于 Windows ARM64 原生系统。

## 使用步骤

1. 把 `PolaMV-1.0.0-Windows-x64-offline.zip` 复制到电脑本地，右键选择「全部解压」。不要在压缩包内直接运行。
2. 需要使用真实 USB 相机时，双击 **First-use-Install-USB-Driver.cmd**，在 Windows 管理员权限提示中选择「是」。安装结束会显示结果；如果要求重启，请先重启。这一步通常只需执行一次。
3. 连接相机，双击 **PolaMV Studio.exe**，点击「搜索相机 → 打开 → 开始采集」。

仅试用模拟相机时，跳过第 2 步。

无需另装 Python、Anaconda、Qt 或完整 MVS 客户端。运行不需要联网。请保留整个目录，特别是 `_internal`。

## 包内内容

- 软件和 Python / Qt / NumPy / Numba / TIFF 运行环境。
- 海康官方 MVS 4.3.0 本机安装提供的完整 Win64_x64 SDK 运行库，以及官方 Python 接口声明。
- 海康 USB 相机驱动 4.1.0.1：原始 INF、CAT、SYS、WDF CoInstaller，未修改厂商驱动文件。
- 驱动安装入口、第三方许可文件、SHA-256 文件清单。

驱动 CAT 在打包电脑上通过 Microsoft Windows Hardware Compatibility Publisher 签名检查。安装使用 Windows 自带 PnPUtil，不导入额外信任证书、不关闭驱动签名校验、不强制替换已有更高优先级驱动，也不自动重启。

## 限制与排查

- **首次使用真实相机仍需要安装 USB 驱动**，并获得管理员权限。把 SDK DLL 放进文件夹不能代替系统驱动安装。
- 驱动包来自现有官方安装，版本较早；受管理电脑的驱动策略、某些 Windows 11 安全设置或硬件差异仍可能阻止安装。出现失败时查看提示和 `%LOCALAPPDATA%/PolaMV/usb-driver-install.log`，不要关闭系统安全功能绕过错误。
- 安装成功表示驱动包已进入 Windows 驱动存储。相机未连接时需随后插入；已有其他驱动时最终绑定取决于 Windows 驱动优先级。
- 本机已验证程序加载包内 SDK，不借用本机已安装的 MVS DLL，并完成真实相机五种格式采集、软件触发及四类 TIFF 保存检查。**尚未完成独立干净系统部署、偏振精度和硬件外触发验收**。本机依赖隔离检查不等同于新电脑硬件验收；完整界面高负载下仍可能丢帧。
- 面向 MV-CH050-10UP USB 相机；未打包其他 GigE/采集卡的系统驱动安装流程。

驱动安装方法参考：[Microsoft PnPUtil 示例](https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/pnputil-examples)和[返回值](https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/pnputil-return-values)。
