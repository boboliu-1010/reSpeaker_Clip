# Boa HTTP 音频存储模块

本目录是统一 Boa Server 的存储模块。业务服务按已认证用户挂载独立的 FastAPI、SQLite 与磁盘音频存储，App 上传与 Clip 直传在统一文件列表中按用户隔离。正常部署从代码根目录使用 `python -m server`，不单独启动本目录。

## 安装与启动

```sh
python3 -m venv .venv-boa
.venv-boa/bin/python -m pip install -r server/requirements.txt
.venv-boa/bin/python -m server --data-dir /path/to/persistent-data --host 0.0.0.0 --port 9528 --web-port 9529 --tls-root /path/to/tls
```

Web HTTPS 9529、API HTTPS 9528 和 Clip DTLS/UDP 9528 共用一个进程、身份体系和数据根目录。首次登记、TLS、用户凭证与 systemd 见 [统一 Server 说明](../README.md) 和 [部署说明](../boa/DEPLOYMENT.md)。唯一依赖入口是 `server/requirements.txt`。

用户访问 API 使用 `Authorization: Bearer <user_token>`，或由统一网页会话校验身份；不使用设备上传凭证访问 HTTP 音频。已有单用户数据必须由开发者确认所属用户后迁入，不能自动重新分配。

## HTTP 协议

| 方法与路径 | 作用 |
| --- | --- |
| POST /api/audio/uploads | JSON: filename、size、sha256、mime，创建上传 |
| GET /api/audio/uploads/{id} | 状态、分片大小、已收索引/哈希 |
| PUT /api/audio/uploads/{id}/parts/{index} | 分片原始字节；X-Content-SHA256 必填 |
| POST /api/audio/uploads/{id}/complete | 后台校验合并，查询状态至 complete/failed |
| DELETE /api/audio/uploads/{id} | 取消未提交会话，不删除成品 |
| GET /api/audio/recordings?offset=0&limit=50 | 当前用户的已完成列表，limit 最大 100 |
| GET /api/audio/recordings/{id} | 当前用户的文件元数据 |
| GET 或 HEAD /api/audio/recordings/{id}/content | 鉴权内容/元信息，支持单段 Range、ETag、If-Range |
| GET /api/boa/v1/audio-files | 按用户统一列出 App 上传与 Clip 来源 |
| GET 或 HEAD /api/boa/v1/audio-files/{id}/content | 统一鉴权下载 Clip/App 原件 |

默认单文件最大 2 GiB、分片 5 MiB，未完成会话 24 小时过期。成功发布前校验每片及整文件 SHA-256 和长度。相同分片重传幂等，内容冲突 409，缺片 409，过期 410，超限 413，错误哈希 422，写满 507，非法范围 416。finalizing 时拒绝写入/取消；重启后可重试 complete。

接受 WAV、M4A、MP3、Ogg、FLAC、AAC 的标准 MIME；保留字节，不转码或承诺任意同扩展名内容都可播放。没有转写、摘要、成品删除 API 或对象存储适配。大文件按块处理，客户端无需将整文件读入内存。

## 数据与备份

统一数据根目录中的 `users/<user>/audio` 保存对应用户的存储数据库、成品和上传分片；`registry.sqlite3` 保存身份与设备归属，`clip/<binding>` 保存 Clip 来源。绑定撤销或换用户不改变历史文件所属用户。

停止统一服务后，整体备份 SQLite、文件和私有配置，不能只复制数据库或运行中手工移动文件。代码包排除用户数据、录音、证书与凭证。一个进程持有数据根目录锁，不部署多个 worker 共用目录。

## 验证与维护工具

从代码根目录执行：

```sh
.venv-boa/bin/python -m pytest server/storage/tests server/boa/tests -q
```

存储测试覆盖鉴权、限制、分片校验、重复请求、续传下载、完整性与异常状态；业务测试覆盖用户隔离、绑定和统一 HTTP。`python -m server.storage.verify_live` 使用独立临时目录启动统一服务，验证大文件、进程重启续传、哈希及音频解码，结果路径打印在末尾。验证脚本不迁移已有数据，历史报告不能代替新的验收。旧独立启动器和过期平台验证脚本已移除。
