# MacBook / iPhone 首次验证

当前阶段提供独立的 iOS 环境检查、Appium 会话、APP 启动、页面 XML 与截图采集。
工作台中的设备选择、Excel 业务执行、配对、OTA、图库等仍走 Android / ADB，尚不能对 iPhone 执行业务用例。
不要以 Android 包名猜测 iOS bundleId；从 iOS 开发者或 Xcode 获取真实值。

## 1. 拉取与 Python 环境

在仓库根目录执行（建议 Python 3.11 或更新版本）：

```bash
git pull --ff-only
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

独立 iOS 入口不依赖 Tk 或 ADB。Windows 的 EXE 和 vendor 目录不作为 Mac 的安装环境使用。

## 2. Mac 与手机准备

安装完整 Xcode，打开一次完成组件安装、许可证确认，并在 Xcode Settings 中登录开发者账号。
用 `xcode-select -p` 检查当前开发者目录指向完整 Xcode；必要时执行：

```bash
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
```

安装与所选 Appium 版本兼容的 Node.js，再安装 Appium 和驱动：

```bash
npm install -g appium
appium driver install xcuitest
python -m studio.ios doctor
```

如果已有 Appium，请先检查版本与驱动兼容性，不要直接覆盖旧环境。
Xcode、iOS、XCUITest 的版本须按官方矩阵匹配：
[系统要求](https://github.com/appium/appium-xcuitest-driver/blob/master/docs/getting-started/system-requirements.md)、
[驱动安装](https://github.com/appium/appium-xcuitest-driver/blob/master/docs/getting-started/installation.md)。

iPhone 通过 USB 连接并解锁、信任 Mac；开启开发者模式，在 Xcode 的 Devices and Simulators 中确认设备可用。
提前手动安装待测 iOS APP。doctor 列出的设备信息可用于查找 UDID。
首次 WDA 构建需要有效开发签名，遇到签名或信任错误请先在 Xcode 解决。
参考 [WDA 签名配置](https://appium.github.io/appium-xcuitest-driver/12.16/getting-started/provisioning-profile/auto-config/)。

## 3. 配置与冒烟

```bash
cp configs/ios.example.json configs/ios.local.json
```

填写 `udid`、`bundleId`、开发团队 `xcodeOrgId`、可签名且唯一的 `updatedWDABundleId`。
如使用自己的签名配置文件，可添加 `xcodeConfigFile`。本地配置已被 Git 忽略。
在单独的终端启动服务并保留日志：

```bash
appium --address 127.0.0.1 --port 4723
```

回到已激活虚拟环境的项目终端：

```bash
python -m studio.ios smoke
```

也可以 `bash 启动iOS检查.command doctor` / `bash 启动iOS检查.command smoke`。
脚本不自动安装或重置 APP，不自动接受系统权限弹窗；首次验证时手动处理权限。
成功后检查 `runs/ios_*/phone.png` 与 `page.xml` 是否为目标 APP 页面；失败详情在对应 `error.txt` 和 Appium 终端。
会话结束会释放 Appium 连接。此步骤只证明基础链路，不代表业务用例通过。

## 4. 后续接入所需信息

保留 Mac/Xcode/iOS/Appium/XCUITest 版本、真实 bundleId、页面 XML、截图和失败日志。
在真机确认登录、权限弹窗、首页和配对入口后，再实现 iOS 页面定位、系统弹窗处理和工作台平台分流。
Android 的 APK 下载重装、ADB、resource-id、BLE 广播命令与 logcat 逻辑不能直接套用到 iOS。

框架回归命令：`python -m pytest framework_tests -q`。
