# Boa 桌面端 / Server / HTTPS 固件集成分支

**先读 [Boa Voice 统一总览](docs/product/boa-voice-overview.md)**：首期仅接收并列出本人音频文件，复用 App/Clip 上传，只新增统一列表接口；转写摘要、模型配置与固件管理均后移。

分支：`boa/desktop-https-integration`。桌面与实验固件已完成代码集成；音频 Server 后续已部署至开发机并通过服务器内验证。未发布 App 安装包、未安装本分支 App、未刷机。

**服务设计：App 与 Clip 都连接同一个 Boa Server，使用同一个 SERVER_URL。** 服务包含 App 上传、Clip 接收、统一鉴权、文件存储和列表接口。开发机为 `bobo@100.58.19.213`；部署参数见 [部署记录](docs/development/server-100.58.19.213.md)，已有跨机器传输证据见 [桌面 HTTP 验证](docs/development/2026-10-22-desktop-http-status.md)。这些记录不代表首期归属与统一列表已经实现。

## 集成来源

| 组件 | 固定来源 | 本次处理 |
| --- | --- | --- |
| Clip STA + HTTPS 实验固件、USB 配置工具、接收端 | `experiment/https-runtime-0.1.2`，`cfff60539d94c6d3e43f788592b97a76547278fe` | 作为分支基线，保持代码不变 |
| Boa macOS Beta 3、Flutter SDK 修复、音频 Server | `boa/desktop-beta3`，`c69830b` | 按原顺序 cherry-pick 13 个桌面提交，提交信息保留来源 |
| 模块、AI 和直传桥接协议文档 | 同上 | 一并迁入；设计状态不等于已开发 |

本分支基于实验固件，**没有合入 main/release 分支的其他固件变更**。桌面版本保持 `1.0.1-beta.3+3`，音频 Server 保持自身 Beta 版本。原桌面分支保留。

后续开发机适配只为 Server launcher 增加可选 TLS 参数；桌面 `StorageClient` 明确在下载完成后关闭该次下载连接，避免下一次上传复用对端已退出的连接。`/api/audio`、持久存储逻辑、上传重试与哈希校验保持不变。测速程序可通过环境变量在当前进程信任开发证书，未改已安装 App 或系统证书设置。

**首期只验收文件可见：**新增 `/api/boa/v1/audio-files` 统一列出完整接收的 App 文件和 Clip 原始片段；统一索引和用户归属待开发，不要求首期播放/解码或 AI。以下是已有代码能力，保留不删。

## 保留的功能与边界

- 桌面端：麦克风录音、输入选择、暂停/继续、暂存恢复、本地音频导入/播放/重命名/回收站、本地/远程来源显示、时间倒序、自动备份队列、服务器配置、Clip 连接设置和状态页。详见 [桌面使用说明](README-desktop.md)。
- 音频 Server：`/api/audio` 分片上传、SHA-256 校验、持久化、列表、HTTP Range 下载与续传。仍是单用户令牌模式，文件与 SQLite 存在本机磁盘。详见 [Server README](services/audio_storage/README.md)。
- 实验固件：STA 联网、HTTPS 分块续传、USB 配置、空闲自动上传及录音优先机制，保留实验基线的限制。其构建以 STA 替代设备 AP，USB 不暴露录音磁盘；旧 App 的 AP/Wi-Fi 同步路径不能直接当作该固件可用功能。

**首期同一服务内的数据流（设计，待实现）：**

```text
App  ── /api/audio/uploads/... ──┐
                                ├─ Boa Server ─ 归属/文件索引 ─ /api/boa/v1/audio-files ─ App
Clip ── /v2/devices/... ─────────┘
```

Clip 的 stored 表示原始片段完整接收；首期在同一个 Server 登记来源、所属用户和元数据后即可显示文件。原始片段不要求首期解码或播放，转写摘要与固件管理不在首期。上述归属与统一列表仍待实现，不以现有上传验证代替完整验收。

## 本地开发启动

开发环境：macOS、Xcode、Flutter，以及 Python。固件另需 Nordic NCS / Zephyr 工具链，不能用桌面构建代替固件编译。

音频服务（使用独立开发数据，避免与已有服务争用）：

```sh
cd services/audio_storage
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python run.py --data-dir ./data/integration-dev --port 18765
```

服务首次启动在上述目录生成 `token`。在桌面端服务器设置中填写 `http://127.0.0.1:18765` 和该文件的令牌。令牌不要提交或贴到聊天。

另开终端，在仓库根目录启动桌面端：

```sh
bash scripts/run-desktop.sh
```

该入口是 `mobile/app/lib/desktop_main.dart`，不是 `mobile/sdk/flutter/example`。本地构建可能使用相同的 App 数据目录；如要清空/隔离已有用户数据，应另外安排，不能直接删除。

上述启动命令仅用于现有音频服务基线，不代表已具备首期 Clip 接收和统一列表。实验 [接收工具](tools/https_poc/README.md) 作为协议/续传实现参考；首期由同一个 Boa Server 提供 V2 接收路由。设备连接参数仍按 [实机限制](docs/https-prehardware-test-results.md) 核实。

## 后续接入顺序

历史完整方案（已移出首期）：开发细节参考 [固件管理审阅清单](docs/product/firmware-management-review.md)，再看 [设计](docs/superpowers/specs/2026-10-22-firmware-management-design.md) 与 [HTTP 契约 draft.3](docs/contracts/firmware-http-v1.md)。已按确认方向补齐 endpoint、独立 start/cancel/resolve、设备/授权/profile/策略接口及 [请求响应样例](docs/contracts/examples/firmware-http-v1.json)。范围覆盖自建固件库、版本分发、角色权限、App BLE 手动升级和审计；未部署固件 API 或刷机，硬件验收条件仍待核实。

1. 在同一个 Boa Server 复用 App 上传与 Clip V2 接收，补设备/用户归属。
2. 增加持久文件索引及只读 audio-files 列表，App 只增加本人文件列表和刷新。
3. 验证两个来源文件可见、断点重传/重启不丢归属、用户之间隔离。

本次实际验证及未通过项见 [集成验证记录](docs/product/boa-desktop-https-integration-verification.md)。历史 Beta 安装验收只属于原版本，不等于本分支重新完成实机验收。
