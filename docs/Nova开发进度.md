# Nova 自动化开发进度（2026-11-10）

原始用例：`C:\Users\CC\Desktop\G1367\VisionRay_冒烟测试用例.xlsx`，Nova Sheet 共 78 条。测试手机 `60c638e1`，USB 眼镜 `B4900PA25JA0F9`，APP 当前绑定名 `Vision Ray A078`。

## 2026-11-11 追加

- `N_Smoke_019`（录音引导，`VisionRay_0195`）和 `N_Smoke_020`（触摸板音乐引导，`VisionRay_0196`）已加入注册表；原始 Excel 的 Nova!B8/B9 已回填。指令分别是录音开始 `2`、结束 `1`；音乐播放/暂停 `10`、前滑 `20`、后滑 `21`。
- 录像结束后的真实下一页为 `Start live/call recording`，已调整 `N_Smoke_018` 的下一页检查，并作为 019/020 的独立前置。
- 实机准备引导时 APP 两次显示 `Binding Failed / Please try again later`。手机 logcat 在 13:49:07 记录 `CLASSIC_PAIRING_FAILED`、经典蓝牙 bond 状态 11→10。切换手机蓝牙后再次尝试仍未进入引导，因此 019/020 尚无业务通过结果，当前 APP 停在 `Add Device` 未绑定页。Appium 临时会话可读取 UI，但本机标准 Appium 初始化仍受 `io.appium.settings` 启动问题影响。后续先恢复 Nova 配对，再实测录音和触摸板动作。

## 已接入注册表

`N_Smoke_014`～`018`、`022`、`025`、`026`、`028`、`029`、`033` 共 11 条，对应 `VisionRay_0179`～`0189`。其余用例尚未实现，不能把注册数量误报为 78 条。

## 实机确认

- 系统蓝牙弹窗公共处理器会自动确认；Nova 配对代码已避免重复点击 Pair。配对已到佩戴引导。
- 眼镜休眠时通过 USB `input keyevent 4`（右键/Back）一次能唤醒测试页；该动作仅在休眠异常场景触发。
- 配对事件先模拟折叠；拍照前必须模拟展开，否则眼镜记录“折叠”而不拍照。展开后拍照，APP 进入录像引导，媒资总数增加。
- 当前 APP 录像停止后进入 `Start live/call recording`，与表中“直接进入音乐引导”不一致；录像用例对此给出明确断言失败。
- 首页连接卡片 `N_Smoke_022`、录音页 `N_Smoke_033`、Wi-Fi 连接 `N_Smoke_025`、两网络往返切换 `N_Smoke_026` 已用手机实操通过。
- 手机和眼镜已重新连接；`N_Smoke_015`、`016`、`017` 独立前置后实机通过。`N_Smoke_028` 在 Nova 首页滚动进入系统设置后，实机完成改名、核对和恢复原名；APP 名称输入有 18 字符限制。
- Wi-Fi A=`QD_clash_5G`、B=`DPVR_Office`，密码存放在 Git 忽略的 `configs/nova_wifi.ini`；模板为 `configs/nova_wifi.example.ini`。
- Nova OTA 配置：167 升级至 V7.33.1，168 降级至 V7.33.0。降级后清空数据、APP 提示解绑属预期。当前眼镜实际固件为 `7.33.2`，不在允许的相邻版本范围，OTA 不应上线任务；尚未实测升级。
- 8 项 Nova 相关框架测试通过。标准工作台整轮尚未跑。

## 表格状态与下一步

15:00 已将 11 个已注册编号直接回填到原始 Excel 的 Nova B 列，并回读核对。原始备份为 `.tools/VisionRay_冒烟测试用例.before_nova_ids.xlsx`。通用表格工具导出的 `.tools/Nova_ids_candidate.xlsx` 丢失图片，因此实际使用原 XLSX 包内定点替换；除 Nova 工作表外，所有 ZIP 部件逐字节一致。

当前 ADB 已识别 Nova 眼镜 `B4900PA25JA0F9` 和手机 `60c638e1`。

继续实现其他 Nova 用例，优先修复配对/引导之间的独立前置和 Wi-Fi 页面稳定性。账号注销 `N_Smoke_077` 仍需可注销的专用测试账号；不要用默认共享账号注销。
