# 官方与 Boa Beta 4 的 Clip 连接差异

对照时间：2026-10-26。背景：官方 App 可以连接，Mac 上 Boa Voice Beta 4 连接不可用。本轮按用户要求，只根据两边代码核对；不依赖实物、固件文件或现场报错。

对照版本：Seeed `reSpeaker_Clip/main` 的 `c6ffe47`、SenseCraft `sensecraft-voice/main` 的 `9099feb`、Boa 已发布 Beta 4 的 `ef6c089`。本次本地未发布的扫描修复另列，不混入 Beta 4 对比。

## 核心结论

**扫描结果的 BLE 连接代码沿用官方 SDK。差异主要在新建的桌面页面及 Mac 平台适配，尚未证明具体连接失败的根因。**

| 环节 | 官方实现 | Boa Beta 4 | 对本次问题的含义 |
| --- | --- | --- | --- |
| 底层插件 | flutter_blue_plus 1.36.8、Darwin 7.0.3 | 相同版本 | 没有插件版本差异 |
| GATT UUID | 服务 6E400001，命令 002、响应 003、文件 004 | 完全相同 | 未更换协议 UUID |
| 点击扫描结果连接 | connect → MTU → discoverServices → 订阅响应与文件通知 | 相同 SDK 实现 | 不能将失败直接归因于我们重写了配对或通知订阅 |
| 按已记住 ID 重连 | return _buildConnection(device) | return await _buildConnection(device) | 我们增加 await，使异步初始化失败进入原有 catch；不影响点击扫描结果的路径 |
| 连接可用性确认 | 手机控制器在连接后验证 AT+GSTAT，失败进入断开/故障处理 | 桌面先显示“蓝牙已连接”，再查 VERSION/GSTAT；查询失败只写到原始响应 | 桌面缺少“已连接且 AT 可用”的成功条件；但此差异不能解释 SDK 返回前的连接失败 |
| AT 验证失败后清理 | 取消连接/JSON/电量监听，断开 BLE，清除连接状态 | 查询异常被 _query 捕获，不调用 disconnect、不清除 _connection | 半可用连接仍会保留，录音和配网操作入口也会出现 |
| 已记住设备重连 | 先检查旧连接是否可用；失败时清理；直接连接失败后断开、等待 800ms 并重试一次 | 调一次 connectByDeviceId；失败只提示重新搜索 | 桌面没有沿用官方的重连恢复流程 |
| 配对故障处理 | 手机控制器包含 iOS 配对信息失效的恢复与提示 | 桌面没有对应控制器流程；SDK 显式 createBond 仅适用于 Android | Mac 配对失败需要单独适配，不能直接照搬 Android 或 iOS 分支 |
| 诊断日志 | bootstrap 将 SdkLog 接入 AppLog | desktop_main 未绑定 SdkLog；页面统一显示“操作失败” | 缺少连接、服务发现、通知订阅分别失败的证据 |
| Mac 权限声明 | 官方 Mac 模板未配置这些设备能力 | 已加蓝牙 entitlement 和 NSBluetoothAlwaysUsageDescription | 声明已存在；签名变化仍可能要求系统重新授权 |
| AT 数据协议 | 原有命令写入与 JSON 回复处理 | 仅增加敏感命令的日志、超时脱敏 | 未改变蓝牙报文内容 |

两个官方仓库中的 BLE client、UUID 和 MTU 源文件相同；本文涉及的手机 `connect(ScanResult)` 控制流程也相同。Seeed 手机设备控制器在 Boa 中保留，桌面入口没有调用它。

## 已确认的代码缺口

| 优先级 | 缺口 | 源码位置 | 应有行为 |
| --- | --- | --- | --- |
| P1 | 桌面未把 AT 通道验证作为连接成功条件 | desktop_clip_page.dart 的 _connect、_query；对照官方 DeviceController.connect | 同一 AtTransport 验证 GSTAT 通过后再开放设备操作；失败时清理连接 |
| P2 | 桌面未接入 SDK 日志 | desktop_main.dart；对照 bootstrap.dart 中 SdkLog.bind | 能定位建立连接、服务发现、响应通知、文件通知和 AT 验证失败，保持敏感参数脱敏 |
| P2 | 桌面已记住设备重连缺少恢复流程 | desktop_clip_page.dart 的 _connect(null)；对照 DeviceController.connectById | 清理旧连接，限定次数重试，失败后返回扫描入口 |
| P2 | 官方 SDK 的蓝牙就绪等待仅覆盖 iOS，直接复用于 Mac 时漏掉初始化等待 | Beta 4 ble_client.dart 的 startScan | Mac 也等待 on；关闭、拒绝授权、不可用、超时分别结束操作 |

这些缺口均可通过代码确认，但不能仅凭静态对比指定某一次连接失败的唯一根因。尤其是最后一项属于扫描前阶段，不解释“已扫描成功后连接失败”。

## 双方共有的限制

- SDK 的 `connect(ScanResult)`、`_buildConnection` 和 `_setNotifyWithRetry` 已逐段比对，一致；UUID、MTU、权限辅助模块及 Seeed 手机设备控制器已做整文件哈希比对，一致。见[核对结果](evidence/2026-10-26-clip-connection-audit.json)及[原始 diff](evidence/2026-10-26-official-beta4-ble.diff)。
- SDK 在返回连接对象之前，必须找到命令、响应和文件三个特征，并成功订阅响应和文件通知。因此底层建链成功不一定意味着 SDK connect 已成功返回；这是双方相同的条件。
- SDK 显式建立/修复 bond 的分支仅适用于 Android；官方控制器中的旧配对信息恢复适用于 iOS。不能据此认定 Mac 少发了某条 AT 配对命令，也不能把 iOS 的配对恢复直接视作 Mac 已有能力。
- `connect(ScanResult)` 的 GATT 初始化失败时，SDK 没有统一的连接资源回滚。这是双方共有的实现，不是 Boa 新增差异。官方控制器明确清理的是 AT 验证失败路径，不应泛称为所有连接失败都会自动清理。
- 底层 flutter_blue_plus 的 connect 本身有默认 35 秒超时；不能只看到 SDK 的 connected 状态等待没有显式 timeout，就宣称整个连接永不超时。

## 独立验证记录

- 先前本机旧安装与 Beta 4 均复现了首次扫描 `CBManagerStateUnknown`；系统蓝牙本身开启。这里只作为独立扫描问题记录，不作为用户那次连接失败的证据。
- 本机 TCC 日志显示 `kTCCServiceBluetoothAlways` 的旧签名要求匹配失败并进入权限请求。它只证明当前本机环境存在重新授权问题，不能代替用户那次连接错误的证据。
- 本地已补 Apple 平台扫描前等待蓝牙就绪的修复，SDK 全部 63 项测试通过，定向静态分析通过，Mac Debug 构建成功。尚未发布到 DMG，也未完成 Clip 真机连接验收。
- App 全套测试为 40 通过、1 失败：`widget_test.dart / App boots smoke test` 未找到“设备”文字；恢复未修改的 SDK 后单独运行该用例仍失败。不能将本轮描述为 App 全套测试通过。

## 修复顺序

1. 沿用官方 SDK，补齐桌面 AT 验证、失败清理和限定重连；不要复制整个手机业务控制器及其数据库、自动下载等依赖。
2. 补桌面阶段状态与 SDK 日志；一个连接共享同一个 AtTransport 串行队列，命令参数继续脱敏。
3. 不依赖硬件验证以下分支：GSTAT 超时/拒绝时不显示可用、不开放操作且会断开；重连次数有界；旧连接清理；权限状态处理。
4. 硬件具备后再验收 Mac 首次配对、GATT 服务发现、加密通知、断开重连和实际录音命令；这部分不计入代码对比完成条件。

关键源码：[官方手机连接控制器](../../mobile/app/lib/src/features/device/presentation/device_controller.dart)、[桌面连接页](../../mobile/app/lib/src/features/desktop/desktop_clip_page.dart)、[共用 SDK](../../mobile/sdk/flutter/lib/src/ble/ble_client.dart)。

以上差异冻结于 Beta 4，原始对比证据不随工作区修改。后续底层连接修复、回归测试和验证边界见 [Beta 5](../releases/boa-desktop-v1.0.1-beta.5.md)。
