---
name: visionray-android
description: 编写或维护 VisionRay Android 自动化、接入新手机时，处理环境、安装、APP 启动、权限、配对和设备差异。
---

# VisionRay Android 自动化

适用于包名 `com.dpvr.android.app.Occident` 的自动化用例。

## 新手机接入：先按此顺序排查

1. 记录 ADB 序列号、`ro.product.manufacturer`、型号和 Android 版本，确认 `adb devices -l` 为 `device`。先检查当前系统语言和 APP 语言；重装 APP 可能按手机语言初始化。不要把配置中的 `locale=en` 当成已实际切换手机语言。
2. 用工作台指定版本完成一次卸载安装，核对手机实际 `versionName`。安装失败时保存 ADB 返回码、输出、手机焦点窗口和安装弹窗 XML。不要把安装失败继续归为用例失败。
3. 建立 Appium 会话并读取一次真实 UI 树，再验证 APP 启动、前台恢复、权限弹窗和目标眼镜配对。会话失败先查 `runs/appium-service.log`、Android SDK 路径及手机上的 `io.appium.settings`，再改业务用例。
4. 只对已观察到的厂商差异加分支；优先用资源 ID、当前包名和实际 UI 树定位，并保留已有三星手机路径。涉及媒体时另查相册、分享预览和播放器的真实布局。改完用该手机做最小实机复测，再跑受影响用例。

## 红米 K60 / HyperOS 已处理的差异

- **USB 安装**：`studio/pgyer.py` 在小米设备执行 `adb install` 时同步检查 `com.miui.permcenter.install.AdbInstallActivity`，从弹窗 XML 点击安装确认；失败信息带 ADB 退出码、是否见到弹窗和点击次数。安装长时间等待时先看手机上的“通过 USB 安装”提示，不要直接重试整轮。
- **Appium Settings**：`studio/android.py` 遇到该辅助应用未运行的特定会话错误时，补授粗略位置权限、重启辅助应用并重试一次。若仍失败，检查其位置权限和后台自启动；不要把所有 Appium 错误都当成这一种。`studio/service.py` 还处理了 Appium 继承失效 SDK 路径的情况。
- **权限和配对弹窗**：`studio/popups.py` 识别 `com.lbe.security.miui`，位置权限选择精确定位及允许；系统蓝牙配对框以对应资源 ID 定位，核对弹窗设备名与本轮目标眼镜一致后才确认。`studio/android.py` 的前台检查也识别小米权限控制器。
- **系统设置与媒体**：HyperOS 语言页可能由多个页面处理，语言测试会先停止设置进程再打开语言入口；媒体分享预览的水印位置与三星不同，`studio/gallery.py` 按实际画面区域检查，不能套用三星固定坐标。

以上是 K60 的实测差异，新增手机先采集自己的截图、XML、Appium/ADB 日志，再决定是否需要新分支。

## 前台恢复

- APP 不在前台时，使用启动器 Intent：`adb -s <phone> shell monkey -p com.dpvr.android.app.Occident -c android.intent.category.LAUNCHER 1`。
- 不要用 Appium `activate_app()`，也不要直接启动 `com.dpvr.android.appguide.activity.SplashActivity`。该启动页初始化后会结束，实际设备上可能回到桌面，造成后续元素定位失败。
- 拉起后先等待目标包成为前台，并让公共弹窗处理器关闭 APP 更新、固件更新等非测试弹窗，再继续页面断言。

## 验证

- 涉及前台恢复的改动，至少在连接手机上确认 `mCurrentFocus` 为目标 APP 的首页或当前用例页面；不能仅依赖 Appium 调用未抛异常。

## 自动化编号

- 自动化编号统一使用 `VisionRay_XXXX`，其中 `XXXX` 为四位递增数字，例如 `VisionRay_0001`。
- 已经符合该格式的编号必须保留；新建或修复编号时，从工作簿和用例注册表中现有最大编号继续递增，不能复用编号。
- 将自动化编号回填 Excel 时，只更新自动化编号列，不改动用例编号、步骤、预期结果及其他单元格内容。
