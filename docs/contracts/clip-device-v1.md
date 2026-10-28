# Boa Voice 与 Clip 设备交互契约

> 历史协议/设计背景：旧 HTTPS/V2、AP/UDP 及待开发状态按文中版本保留。当前实现采用 Roger DTLS v3，Server 用户隔离、统一文件索引及可选绑定见 [扩展约定](roger-base-extension-v1.md)；不要以旧草案作为当前运行状态。

**当前功能入口：**见 [设备与音频文件总览](../product/boa-voice-overview.md) 和 [Roger 基础与 Boa 扩展约定](roger-base-extension-v1.md)。当前 HTTPS profile 的基础录音控制为 START/STOP，联网/上传配置走 USB；下表同时保留原桌面基线的命令映射。

**性质：桌面当前接入范围、固件事实与后续联调规则。** 不是给固件新增命令，也不表示已经通过真机联调。

源码基线：固件 `applications/clip` 内容树 `f78e227180db84a08c292ce946c2fd0fa72caa74`；Flutter SDK 内容树 `e3c3c09aa362f8c1584582f47f026c2f40f62381`。收到的实物需记录 VERSION、刷入包的构建来源/校验值及实际板型。只知道“roger/官方固件”名称，不足以判定兼容。

另有 cfff605 实验固件已实现 [STA/HTTPS 直传核心](../design/2026-10-22-clip-direct-server-upload-design.md)，但未进入本文的桌面/固件基线；[App/Server 桥接](clip-ingest-app-server-bridge.md) 尚未实现。实验 USB 配置命令不自动加入本文白名单，AP/UDP 语义保持。

## 1. 分层与所有权

```text
App 用例 -> DevicePort -> Clip SDK适配器 -> BLE GATT -> 固件AT服务
                                  \-> 未来设备文件传输适配器
```

UI 只使用 scan/connect/query/recordingCommand 等类型化接口。一个设备连接只建立一个 AtTransport 串行队列；页面轮询、操作按钮和未来文件同步共享它，不能各建一个队列争用回应。断开只改变连接状态，不向用户保证 Clip 停止录音。

规范参考：[固件 AT 文档](../protocol.md)、[UDP 文档](../udp_protocol.md)、[SDK 文档](../../mobile/sdk/flutter/docs/DEVICE_BLE_PROTOCOL.md)。文档冲突项见第 5 节，修改前以 pin 住的源码与实物抓包验收。

## 2. BLE 与消息约定

| 角色 | UUID 后缀（完整基础 UUID：`6E40000x-B5A3-F393-E0A9-E50E24DCCA9E`） | 方向 |
| --- | --- | --- |
| Service | x=1 | 服务发现 |
| Command | x=2 | App 写入 AT 文本 |
| Response | x=3 | 设备 Notify JSON，应答与主动事件共用 |
| File Data | x=4 | 设备 Notify **二进制帧**，不是业务层可直接拼接的 WAV |

MTU 由连接协商，不能硬编码单个 Notify=一个完整 JSON。SDK JSON framer 按对象边界重组，再区分 event 与 ack；二进制流交给自己的帧解析器，不进入 JSON parser。命令写入的 BLE 链路确认不等于固件业务成功。

当前 wire 没有 request id、numeric error code 或协议版本协商。连接后默认发送 VERSION/GSTAT 获取快照；任何新增能力查询命令必须先获固件支持，不能因设计需要便直接发送。

## 3. 当前桌面命令白名单

| 调用 | 命令 | 成功条件/后置确认 |
| --- | --- | --- |
| firmwareVersion | AT+VERSION | ok=true；当前固件字段 firmware 位于顶层 |
| status | AT+GSTAT | ok=true + data；更新采样时间；失败不覆盖为假空闲 |
| start | AT+START | ack 匹配且 ok=true；随后查询状态，recording/state 与目标对账 |
| pause | AT+PAUSE | ack ok=true；随后观察 PAUSED |
| resume | AT+RESUME | ack ok=true；随后观察 RECORDING |
| stop | AT+STOP | ack 匹配会话；随后查询退出录音；不能拿主动状态 event 当 ack |
| mark | AT+MARK | ok=true 表示设备确认；不向此命令附加任意文本或自动生成转写标记 |

SDK 默认回复等待 5 秒；桌面当前均使用默认值。协议设计建议 STOP 独立预算并覆盖 SD 卡慢写情形，但这还不是已配置行为。排队、分块写和回复等待是不同阶段，端到端预算需另定义。

写操作超时结果为 **unknown**，不能认定失败后再次发送 START/MARK。先查询 GSTAT/会话；如无法消歧，提示用户状态待确认。串行队列可减少歧义，但在无 request id 的旧协议上不能彻底消除迟到应答。

### GSTAT 字段映射

```json
{
  "ok": true,
  "data": {
    "state": "PAUSED", "recording": false, "session": "session-example",
    "duration": 65, "battery": 0, "charging": false,
    "free_space": 512, "mode": "normal", "bitrate": 64000,
    "temp": 25, "voltage": 3800, "device": "Clip"
  }
}
```

展示映射：duration 秒 → 领域 durationMs；free_space 保留 firmware 单位 MB，不能直接标成字节；battery=0 和 charging=false 都要保留。state 可为 UNINITIALIZED/IDLE/RECORDING/TRANSMITTING/WIFI_SYNC/PAUSED/ERROR/OTA；未知枚举显示未知并保留 rawState。不得以 recording=false 覆盖 PAUSED 或固件的过渡状态。

字段缺失、非法值或请求失败都返回 unknown/null；不要填 0、false 或“空闲”。快照带 observedAt；断开后 UI 不把旧值显示为“实时在线”。

典型错误：`{"ok":false,"msg":"..."}`。Device 适配器目标归一化优先读取 msg，再兼容 error/message，未知保留安全的原始描述。目前桌面 checkedClipReply 缺 msg 映射，需后续专项修复。

## 4. 后续文件传输边界（未接入桌面）

设备下载归 DeviceTransfer 适配器，完成长度/CRC 后交 Library 导入，不让 UI 把二进制帧直接写入业务库。CRC32 保证设备传输完整性，导入/HTTP 侧的 SHA-256 是另一层检查，不能互相替代。

| 项目 | BLE 当前源码 | UDP 当前文档/固件 profile |
| --- | --- | --- |
| DATA 类型 | 0x01 | 0x01 |
| DATA 头 | type:u8 + seq:u16LE + len:u16LE，共 5 字节 | type:u8 + seq:u16LE + len:u16LE + payloadCRC32:u32LE，共 9 字节 |
| DATA 片 CRC | 无应用层逐片 CRC | 有，覆盖 payload |
| FILE_START | 0x10 + fn_len:u8 + filename UTF-8 + size:u32LE | 同形状；长度须按字节读取 |
| FILE_END | 0x11 + fullFileCRC32:u32LE | 同形状；完整文件独立校验 |
| TRANSFER_DONE | 0x12 + sid_len:u8 + session UTF-8 + file_count:u32LE | 同形状 |
| 确认/恢复 | 当前 BLE 无 FILE_ACK，依赖链路和完整文件检查 | FILE_ACK 0x03 OK/NACK；旧客户端整文件重传，bitmap恢复要单独验证 |

UDP 热点的实际 IP/port/凭据应取 WIFI? 返回，不把常见 `192.168.4.1:8089` 作为永恒配置。连接热点后无互联网是设备链路属性；自动备份/模型网络任务要感知网络切换，不在失去外网时无限重试。

UDP 文档指出有效序号空间 4096 帧、payload 上限 1024，超过覆盖范围不能假设 bitmap 可修复；需要按该固件的切片大小与抓包验证大文件策略。不能套用“HTTP 2 GiB 文件支持”宣称 UDP 同样支持。原始 Opus 分片/尾片、封装与解码属于独立适配器契约，验证后才承诺可播放或可交给 ASR。

## 5. 文档与实现差异清单

| 差异 | 当前事实与处理 |
| --- | --- |
| error vs msg | SDK 文档描述 error；固件文档/处理器主要返回 msg；桌面解析未覆盖 msg。先补兼容样例与错误映射设计 |
| AT+PURGE | SDK 文档列出，但当前固件注册表无 PURGE；不发送。需要批量删除必须重新设计确认与命令能力 |
| raw file bytes vs 帧 | SDK 部分描述为 raw bytes，固件 BLE 实际 5 字节 DATA 头；必须按 profile 解析，不能简单 append 所有 Notify |
| GSTAT 错误回应 | SDK matcher 的 looksLikeGstatOkReply 要求 ok=true，错误回应可能无法作为请求完成；需要失败应答测试，不能只测成功 JSON |
| 固件版本适配 | 尚未确认实物刷入的具体构建，无法据本地代码宣布官方/roger 全面兼容 |

## 6. 真机验收与协议冻结条件

新增需求的 OTA、升级互斥、结果确认与恢复规则见 [固件管理接口草案](firmware-http-v1.md) 和 [设计](../design/2026-10-22-firmware-management-design.md)。本节原有“未开放”状态仍保留，设计草案不等于桌面已接入 OTA；BLE SMP 与 `AT+DFU` USB 恢复不能混用。

每个固件 profile 单独保存：固件包校验值/源码版本、手机或桌面平台、SDK 内容版本、MTU、命令/应答原始样例及二进制帧样例（日志去掉热点密码）。至少覆盖：

1. 扫描连接、拒绝权限、连接占用、断链重连、只读快照与有效的 0/false 字段。
2. START/PAUSE/RESUME/STOP/MARK 各命令成功、明确拒绝、超时及迟到回应；按钮端操作与 App 状态同步。
3. 手机与桌面不能同时认为自己独占控制；恢复连接后先查询，不自动重放旧写命令。
4. 后续启用下载时验证 BLE/UDP 各自帧布局、序号、CRC、断片、尾片、取消、Wi-Fi 网络切换及真实解码。
5. 删除、格式化、恢复出厂和 OTA 另设产品确认及失败恢复契约，本轮不开放。

桌面目前只宣称白名单范围的接入与离线解析测试，未把这些真机验收项写成完成。规范和样例评审后再进入实现计划。
