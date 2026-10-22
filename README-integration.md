# Boa 桌面端 / Server / HTTPS 固件集成分支

分支：`boa/desktop-https-integration`。桌面与实验固件已完成代码集成；音频 Server 后续已部署至开发机并通过服务器内验证。未发布 App 安装包、未安装本分支 App、未刷机。

开发机为 `bobo@100.58.19.213`。Boa 音频库现使用 **`https://100.58.19.213:9528`**，Mac 上桌面同一客户端已完成真实跨机器音频传输；不依赖 SSH 转发。见 [当前部署与证书说明](docs/development/server-100.58.19.213.md)、[桌面 HTTP 验证](docs/development/2026-10-22-desktop-http-status.md)。Roger 的 9527 仍是独立 Clip 接收端；已安装 GUI App 尚未配置这份开发证书。早期 [部署验证记录](docs/development/2026-10-22-server-deployment-verification.md) 保留当时的 loopback 状态。

## 集成来源

| 组件 | 固定来源 | 本次处理 |
| --- | --- | --- |
| Clip STA + HTTPS 实验固件、USB 配置工具、接收端 | `experiment/https-runtime-0.1.2`，`cfff60539d94c6d3e43f788592b97a76547278fe` | 作为分支基线，保持代码不变 |
| Boa macOS Beta 3、Flutter SDK 修复、音频 Server | `boa/desktop-beta3`，`c69830b` | 按原顺序 cherry-pick 13 个桌面提交，提交信息保留来源 |
| 模块、AI 和直传桥接协议文档 | 同上 | 一并迁入；设计状态不等于已开发 |

本分支基于实验固件，**没有合入 main/release 分支的其他固件变更**。桌面版本保持 `1.0.1-beta.3+3`，音频 Server 保持自身 Beta 版本。原桌面分支保留。

后续开发机适配只为 Server launcher 增加可选 TLS 参数；桌面 `StorageClient` 明确在下载完成后关闭该次下载连接，避免下一次上传复用对端已退出的连接。`/api/audio`、持久存储逻辑、上传重试与哈希校验保持不变。测速程序可通过环境变量在当前进程信任开发证书，未改已安装 App 或系统证书设置。

## 保留的功能与边界

- 桌面端：麦克风录音、输入选择、暂停/继续、暂存恢复、本地音频导入/播放/重命名/回收站、本地/远程来源显示、时间倒序、自动备份队列、服务器配置、Clip 连接设置和状态页。详见 [桌面使用说明](README-desktop.md)。
- 音频 Server：`/api/audio` 分片上传、SHA-256 校验、持久化、列表、HTTP Range 下载与续传。仍是单用户令牌模式，文件与 SQLite 存在本机磁盘。详见 [Server README](services/audio_storage/README.md)。
- 实验固件：STA 联网、HTTPS 分块续传、USB 配置、空闲自动上传及录音优先机制，保留实验基线的限制。其构建以 STA 替代设备 AP，USB 不暴露录音磁盘；旧 App 的 AP/Wi-Fi 同步路径不能直接当作该固件可用功能。

**两套 Server 尚未打通：**

```text
麦克风 / App 已支持的本地文件 → Boa 桌面端 → /api/audio → 本地磁盘 + SQLite
Clip 实验固件 → HTTPS /v2/devices/.../recordings/... → 实验接收端 → 原始录音分段
```

Clip 的 `stored` 回执仅表示原始字节已接收；不会自动进入 App 的音频列表，也不能直接保证标准音频播放。尚需 SourceRecord 元数据、设备与用户归属、可靠出站队列、原始 Opus 解码/封装和标准音频入库桥接。转写、摘要、自定义模型 endpoint 的 Server 执行仍是协议设计。本次不新增这些运行时功能。

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

实验 HTTPS 接收端单独启动，证书、设备令牌、存储目录也与音频服务分别配置；按 [实验工具 README](tools/https_poc/README.md) 的凭据生成与接收端命令执行。设备配置通过 USB 工具完成，当前桌面界面尚未提供这一配置流程。请先阅读该文档和 [实机限制](docs/https-prehardware-test-results.md)，不要直接照搬历史证书或私有配置。

## 后续接入顺序

新增完整首版需求：先读 [固件管理审阅清单](docs/product/firmware-management-review.md)，再看 [设计](docs/superpowers/specs/2026-10-22-firmware-management-design.md) 与 [HTTP 契约 draft.2](docs/contracts/firmware-http-v1.md)。已按确认方向补齐 endpoint、独立 start/cancel/resolve、设备/授权/profile/策略接口及 [请求响应样例](docs/contracts/examples/firmware-http-v1.json)。范围覆盖自建固件库、版本分发、角色权限、App BLE 手动升级和审计；未部署固件 API 或刷机，硬件验收条件仍待核实。

1. 审核 [Clip → App/Server 桥接契约](docs/contracts/clip-ingest-app-server-bridge.md) 与 [直传设计](docs/superpowers/specs/2026-10-22-clip-direct-server-upload-design.md)。
2. 在 Server 实现原始录音接收、归属、可恢复转换与标准入库；保留现有 `/api/audio` 接口。
3. 在 App 加入设备直传状态、来源、处理失败与重新获取内容流程；硬件联调 BLE 命令差异。
4. 按 [AI HTTP 契约](docs/contracts/ai-http-v1.md) 实现转写、摘要、模型 endpoint 配置与凭据管理。

本次实际验证及未通过项见 [集成验证记录](docs/product/boa-desktop-https-integration-verification.md)。历史 Beta 安装验收只属于原版本，不等于本分支重新完成实机验收。
