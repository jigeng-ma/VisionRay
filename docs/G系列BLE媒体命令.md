# G1/G3/G6 BLE 媒体方法

实现：`studio/ble_commands.py` 的 `BleMediaCommands`，复用已有 Android 会话。

```python
from studio.ble_commands import BleMediaCommands
media = BleMediaCommands(android)
media.take_photo()                       # 拍照 1 次
media.take_photo(count=3)                # 拍照 3 次
media.record_video()                     # 录像 1 次，15 秒
media.record_video(count=2, duration=60)  # 录像 2 次，每次 60 秒
media.record_audio(count=2, duration=90)  # 录音 2 次，每次 90 秒
```

- 仅接受配置中 G系列的 G1/G3/G6。count 必须为正整数，默认 1。
- duration 单位是秒，默认 15；录像最多 720 秒（12 分钟），录音最多 7200 秒（120 分钟）。非法参数操作前报错。
- 录像、录音一次为一个开始/结束组合。每个按钮只点一次，不因结果不确定而重发。多次操作间隔 1 秒。
- 录制前读取当前上限：录像走首页 Capture → Video Duration；录音走首页 System Settings → Recording Duration。即使默认时长也校验。当前上限足够则保留，不足则选择满足要求的最小选项，读回校验后执行；修改后保留新设置。
- 自动进入 我的 → BLE_COMMAND_TEST，必要时上滑一次定位媒体按钮。
- 长录制每 20 秒进行只读会话保活。录制等待异常时仍尝试点击结束；开始点击本身报错时不重试，需检查设备是否已开始。断连/驱动失效时无法保证停止成功。
- 保留 start_video()/stop_video()/start_audio()/stop_audio() 四个底层单次点击方法，供需要自行管理时长的流程使用；这些底层方法不执行时长准备。
- duration 是开始点击返回后的等待时间；UI 指令传输存在延迟，文件精确时长及生成数量需要另行检查。

## 验证和待办（2026-09-17）

已确认实机调试页及五个按钮 ID：btn_start_photo、btn_start_video、btn_stop_video、btn_start_audio、btn_stop_audio。已有页面 XML 确认 Video Duration、Recording Duration 设置行及 tv_hint，录音选项 tv_label 为 30Min/60Min/120Min。

本轮手机首页显示 Add Device，无法进入设备设置。当前逻辑测试覆盖次数、默认值、上限、异常结束、设置足够不修改、不足选择与读回失败；这些测试不代替实机验收。

待眼镜连接后：核对录像选项 tv_label 是否与录音一致、选择后是否自动返回（不符合会阻断，不会盲点）；验证调高与读回、实际照片数量及录像/录音文件时长；验证 G3/G6。尚未完成实际拍摄或长时录制验收。
