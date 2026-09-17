# 首次设备接入检查

检查日期：2026-09-10。通过 ADB 读取设备信息和当前页面结构，未执行拍摄、升级、解绑或账号修改。

| 项目 | 手机 | 眼镜 |
|---|---|---|
| ADB 序列号 | RFCX916QS9M | B4900PA25JA0F9 |
| 系统型号 | SM-S921U | Vision Ray 1 |
| Android 版本 | 14 | 9 |
| ADB 状态 | device，已授权 | device，已授权 |
| 系统构建标识 | 本次未读取 | G1PV002SP_7.33.2 |

注意：B4900PA25JA0F9 是当前设备的 ADB 序列号，不能直接用作产品或型号名称。Vision Ray 1 为系统上报型号，其与业务产品分类的对应关系仍待确认。系统构建标识不等同于已确认的业务固件版本。

## APP 信息

- 包名：`com.dpvr.android.app.Occident`。
- 版本：`1.2.35_sdk-Occident-debug`，版本代码：`102035`。
- 启动组件：`com.dpvr.android.app.Occident/com.dpvr.android.appguide.activity.SplashActivity`。
- 当前前台 Activity：`com.dpvr.android.home.HomeActivity`。
- 当前页面：英文 `My` 页面，可读取 Account、File History、Permission、About App 等入口。
- 手机系统语言为 `zh-Hans-CN`，当前 APP 页面为英文。因此应分别记录系统语言和 APP 界面语言，不能由系统语言推断 APP 语言。

## 对框架设计的影响

1. 手机与眼镜都有 ADB 连接，所有命令必须显式指定设备序列号，避免误操作另一台设备。
2. 当前 APP 页面可以通过 UIAutomator 读取原生元素结构，具备资源 ID，可作为后续 Android 自动化接入依据；尚未验证 Appium 会话。
3. 列表中的 `title`、`next_iv` 和底部的 `ll_tab_parent` 等资源 ID 重复，不能假定 resource ID 全局唯一。元素库需要支持父容器范围、英文文案组合定位及唯一性检查。
4. 当前页面未观察到 WebView，但不能据此认定整个 APP 不包含 WebView。
5. 眼镜能使用 ADB 不代表拍摄、触控、语音等功能已有可调用接口。后续应逐项确认可用控制与观测方式，不能推定 ADB 输入等效于实体按键。
6. USB 接入状态不证明手机与眼镜已通过 APP 配对或连接，该状态尚未验证。

## 后续工作

本次设备仅作为检查样例。手机和眼镜均可更换，每轮通过可视化窗口扫描并选择设备，将本轮选择的序列号及眼镜名称保存到执行清单，不固定绑定本次设备。真实产品、型号和能力通过独立产品配置维护；建立当前页面元素定义，再验证 Appium 驱动及少量框架验收场景。Excel 样例到位后实现结果列映射。
