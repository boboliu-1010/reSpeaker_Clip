# Boa Server 模块接口与存储约定

**v0.2｜2026-10-26｜Beta 4 实现约定。** [产品功能与 endpoints](../product/boa-voice-overview.md)。

## 模块

| 模块 | 实现 | 输入/输出 |
| --- | --- | --- |
| 服务入口 | services/boa_server/run.py、boa_app.py | 一个生命周期，HTTPS/TCP 与 DTLS/UDP；默认同一端口 9528 |
| 身份与归属 | registry.py | user token→user_id；device token→设备绑定/owner/epoch；数据库仅保存凭证哈希 |
| App 存储 | services/audio_storage | 每个用户一个独立 Store；进程内 ASGI 分发，复用分片上传、完成、查询、取消、Range 下载 |
| Clip 接收 | receiver.py + tools/https_poc/dtls_upload_*.py | OPEN 验证设备凭证，按绑定选独立 ResumeStore；原协议控制续传、校验和 COMPLETE |
| 文件列表 | boa_app.py | 合并本人已 complete 的 App 文件和 ready 的 Clip 原件；created/id 倒序分页 |
| 开发者操作 | manage.py | 登记用户、登记设备、撤销设备凭证；凭证通过私有文件交付 |

外层验证用户后，才把 /api/audio 请求交给对应用户的存储应用；内部随机凭据只用于进程内调用，不下发给 App。不同用户的上传 ID、文件 ID、metadata、content、HEAD/Range、取消操作均不会进入其他用户的 Store。

## Clip 上传协议

DTLS 1.2，应用协议 v3。使用证书校验、设备 token 和 8 字节 transfer nonce。OPEN 包含 device、14 位 session、segment、size、SHA256 和 token；1 KiB DATA，单个 segment 上限 8 MiB。

ACK 区分连续 received、选择性接收位图和 durable confirmed。QUERY 强制检查点；重连按 Server 的持久偏移恢复。整文件 SHA256 验证和最终文件发布完成后发送 COMPLETE。仅 received 不代表落盘或完成。

接收会话固定一个设备绑定；同设备新的合法连接接管旧 writer。设备凭证在 OPEN 和后续 DATA/QUERY 中验证，撤销后不能继续写入。文件存储位于 clip/<binding_id>，与 App HTTP 写入目录分离；不改变基础 object_id 和 checkpoint 格式。

## 落盘与索引

```text
registry.sqlite3
  users(id, token_hash, active)
  bindings(id, device, owner, token_hash, epoch, active)
  sources(id, owner, binding, device, session, segment,
          size, sha256, object_id, created, state)
users/<user_id>/audio/{metadata.sqlite3,parts/,files/}
clip/<binding_id>/{object_id}.identity/.checkpoint/.partial/.bin
```

1. 合法 OPEN 在写入字节前持久登记 source，固定 owner、绑定、大小和 SHA。
2. 同 binding/session/segment 的重复来源复用 ID；大小或 SHA 不同返回冲突。
3. DTLS 基础完成后将索引标记 ready；更新失败仍保留 receiving 来源记录。
4. 周期任务和文件列表查询会对账 receiving：最终 .bin 长度及 SHA 一致才转 ready。
5. App 使用原上传 ID，原存储在重启后支持重新 complete；仅 complete 文件可见。
6. Server 重启保留 ID、来源、归属。缺失/校验失败的原件不会新发布到列表。

## HTTP 边界

所有 App API 使用 Authorization: Bearer <user_token>。无效凭据 401；其他用户的资源 ID 404。列表 offset≥0，limit 默认50、范围1..100，按 created DESC/id DESC。列表字段见产品文档；原始 Clip content 为 application/octet-stream，SHA256 ETag，支持 GET/HEAD/单段 Range。

App 上传保持 2 GiB 单文件上限与 5 MiB 分片；整文件长度和 SHA 校验后才 complete。取消不删除成品。上传续传缓存和桌面备份队列按服务地址与账户凭证摘要区分。

## 配置与维护

App 填 HTTPS 根地址与用户凭证；Clip 通过加密 BLE 填同一 Server 的 DTLS host/port、device/token。NETCFG/UPLOADCFG 自动保存；使用 NETCHECK、UPLOADAUTO、UPLOAD? 及 upload/wifi_check 事件管理状态。命令长度必须满足一次 GATT 写入，日志和超时不含配网密码与设备 token。

HTTPS 与 DTLS 同属一个服务；证书需要受 App 与 Clip 信任，SAN 和时间必须有效。开发证书由用户显式导入 App，不关闭 TLS 校验。DTLS 使用 ECDSA P-256。

换绑前处理旧上传与未上传录音，撤销旧凭证，再建立新绑定和新命名空间；历史文件归原用户。旧共享存储的归属迁移由开发者明确指定，不能自动推断。

服务持有进程锁，单进程单 worker。备份需停止服务并整体保存文件与 SQLite。基础来源固定 a2319ce88cbf274612d0cc68a004c1cdafe2bdbe；applications/clip 和 tools/https_poc 保持该版本，新增实现位于 services/boa_server。
