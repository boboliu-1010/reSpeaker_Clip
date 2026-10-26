# Boa Voice：设备与音频文件

**v0.9｜2026-10-26｜设计约定，新增接口尚未实现。**

## 1. 基础与扩展

**Roger 的固件和 Server 是 Clip 基础，按固定版本原样使用。Boa 在其上增加 App 功能、用户归属和统一文件列表。**

| 层 | 内容 |
| --- | --- |
| Roger 固件 | 录音、BLE 控制、联网、HTTPS 上传 |
| Roger Server | 原始片段接收、续传、校验、落盘与回执 |
| Boa 扩展 | 同一个服务内的用户/设备映射、文件索引和列表 API；App 设备页与文件页 |

扩展实现放在新增目录，通过子类/适配层调用基础能力；模块接口、落盘索引和恢复规则见 [Roger 基础与 Boa 扩展约定](../contracts/roger-base-extension-v1.md)。

## 2. 功能

### 设备

| 功能 | 用户看到或执行什么 | 交互方式 | 当前情况 |
| --- | --- | --- | --- |
| 扫描与连接 | 搜索附近 Clip、连接、断开、重连已保存设备 | BLE / Flutter SDK | 桌面已有入口 |
| 查看设备状态 | 名称、版本、电量、充电、剩余空间、录音状态和时长 | BLE：VERSION / GSTAT | 桌面已有查询与展示 |
| 控制录音 | 开始、停止；操作后刷新实际录音状态 | BLE：START / STOP | App 命令与 HTTPS 固件基础已有 |
| 配置联网与上传目标 | Wi-Fi、同一个 SERVER_URL、设备标识和设备凭据；保存配置 | USB：NETCFG / UPLOADCFG / UPLOADSAVE | Roger 固件命令已有，使用 USB 配置工具 |
| 自动上传与状态 | 设置自动上传，查询当前/最近任务阶段、偏移和错误 | USB：UPLOADAUTO / UPLOAD? / UPLOADSTATE | Roger 固件命令已有，App 展示待接入 |
| 查看设备上传的文件 | 刷新文件列表，查看 Clip 来源的原始片段 | HTTP：audio-files | 统一索引与列表待实现 |

开发者登记设备归属，并通过 USB 工具写入联网/上传配置；host/port 从同一个 SERVER_URL 提取。蓝牙标识用于本机重连，服务端归属取设备凭据的登记关系。基础能力的当前状态依据源码，实际设备逐项联调验收。

### 音频文件

**录音上传到同一个 Server，App 能看到自己的音频文件。**

App 显示文件名、大小、时间、来源（App / Clip），支持手动刷新，按时间倒序。Clip 原始文件标注“原始录音”。

![接收录音并显示本人文件](images/boa-audio-files-mvp.png)

## 3. 服务与接口

**App 和 Clip 都连接同一个 Boa Server，配置同一个 `SERVER_URL`。** Boa Server 以 Roger 接收基础为底层，扩展 App 上传、身份校验、文件索引和统一列表查询，按一个服务部署和维护。

| 同一服务内的模块 | 职责 |
| --- | --- |
| App 上传 / Clip 接收 | App 上传复用现有实现；Clip V2 接收调用 Roger 基础，完整校验后登记文件 |
| 身份与归属 | 验证用户或设备凭据，固定所属用户 |
| 文件存储与索引 | 统一保存两种来源的原件和元数据 |
| 文件列表 | 按当前用户查询同一份索引，返回 App 展示 |

`SERVER_URL` 是 Server 的 HTTPS 根地址。下列所有路径都追加到同一个 `SERVER_URL`；App 用用户 token，Clip 用设备 token。

| 功能 | API | 必要信息与成功条件 | 当前状态 |
| --- | --- | --- | --- |
| App 查看自己的文件 | GET `/api/boa/v1/audio-files?offset=0&limit=50` | 用户 token；返回完整接收的文件元数据，见下节 | 待实现 |
| App 上传本地录音 | POST `/api/audio/uploads`；PUT `/api/audio/uploads/{id}/parts/{index}`；POST `/api/audio/uploads/{id}/complete`；GET `/api/audio/uploads/{id}` | 创建带 filename/size/sha256/mime；分片带 X-Content-SHA256；查询到 complete 才列入文件清单 | 已有上传；用户归属/列表索引待补 |
| Clip 上传原始录音 | GET/PUT `/v2/devices/{device}/recordings/{session}/{segment}` | 设备 token；整片大小/SHA，PUT 另带 Content-Length/Upload-Offset/本块 SHA；stored 后登记列表 | 复用 V2 接收实现；归属/索引待补 |

上传分片和 Clip 续传字段见 [存储基线](../contracts/storage-http-v1.md)、[Clip 接收基线](../contracts/clip-ingest-app-server-bridge.md)。

`/api/boa/v1/audio-files` 统一返回 App 文件与 Clip 原始片段的元数据；现有 `/api/audio/recordings` 返回 complete 标准音频。

## 4. 文件列表协议

请求带 `Authorization: Bearer <user_token>`。offset 默认 0 且 ≥0；limit 默认 50、范围 1..100；按 created DESC、id DESC 排序。200 响应示例：

```json
{
  "items": [
    {
      "id": "f_0dcaed10342c49d689a6f32ecb3e409e",
      "filename": "Clip-20261023090000-1.bin",
      "size": 160044,
      "created": 1792720800,
      "source": "clip_direct"
    }
  ]
}
```

- id：Server 生成的稳定文件标识。
- filename：显示名称。size：字节。created：Server 建立记录的时间，单位为 Unix 秒。
- source：`app_upload` 或 `clip_direct`。空列表返回 `{"items":[]}`；不足 limit 表示当前页已到末尾。
- 清单返回完整落盘且校验通过的文件元数据。原件、SHA 和来源键保存在 Server。
- App 文件沿用上传 ID 建索引；Clip 以 `(device_id,binding_epoch,session,segment)` 建唯一来源索引。沿同一来源键重传且大小/SHA 一致时复用原记录，不同内容返回冲突；App 每次创建上传会生成新来源。Server 持久保存索引和文件。

## 5. 归属规则

| 来源 | Server 如何确认归属 |
| --- | --- |
| App 上传 | user_token → user_id；创建上传时固定 owner_user_id |
| Clip 上传 | device_token → 已登记设备与用户绑定；核对路径设备一致，首次接收时固定 owner_user_id 和 binding_epoch |
| App 查列表 | Server 按认证用户的 owner_user_id 过滤 |

开发者通过受控 CLI 登记用户、设备和凭据。换绑前核清旧数据和未完成上传，再撤销旧凭据；历史文件归原用户。未绑定设备拒绝上传，缺失或无效 token 返回 401。

**当前实现使用共享音频 token；独立用户凭据、owner 索引和按用户过滤待实现。** 历史原始文件由开发者核实归属后登记。

## 6. 验收

1. App 文件或 Clip 原始片段上传完成后，刷新能看到一条记录，名称/大小/时间/来源正确。
2. 完整校验后进入列表；同来源键重传复用原记录，Server 重启后仍可查询原文件及归属。
3. 两个用户分别看到自己的文件，无效 token 返回 401。
4. App 与 Clip 使用同一个 SERVER_URL；App 上传和 Clip 直传的完整文件都能在同一个列表查到。
5. 设备可连接、读取状态并开始/停止录音；USB 配置后，Clip 上传的文件出现在本人列表。
6. Roger 固件与接收基础相对固定版本一致，扩展逻辑通过适配层接入。
