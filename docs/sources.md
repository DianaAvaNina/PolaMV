# 实现参考

- 完整用户需求：同目录 `requirements-v1.0.md`，取自用户指定的 ChatGPT 对话最终 V1.0。
- 海康官方 MVS 4.3.0 本机 SDK：`C:/Program Files (x86)/MVS/Development/Samples/Python/MvImport`，使用其 ctypes 结构、函数声明和枚举。参数读写、采集和同位深转换参考同目录官方 `GrabImage`、`ConvertPixelType` 示例。
- [海康机器视觉官方下载中心](https://www.hikrobotics.com/cn/machinevision/service/download/)：2026-09-28 请求返回 HTTP 403，新版包未获取。
- [Sony 偏振传感器说明](https://www.sony-semicon.com/en/products/is/industry/polarization.html)：传感器四方向偏振背景。
- [Allied Vision / SVS-Vistek EXO GigE 官方手册](https://www.alliedvision.com/assets/support/Camera-Documentation/SVS-Vistek/Manuals/Manual_EXO_GigE.pdf)：同型号传感器四方向排列参考。该参考不能代替海康实际输出方向验收。

软件不包含偏振响应标定、过曝提示和视频录制。显示色图为离散查找表；Viridis/Cividis/Twilight 使用控制点插值近似，不影响定量保存。
