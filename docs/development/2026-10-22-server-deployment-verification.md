# Boa 开发服务器部署验证

日期：2026-10-22。目标：`bobo@100.58.19.213`，主机名 `sun-dev-node001`。代码来自本地 `boa/desktop-https-integration`。

本页保留初次部署的快照。后续以 `2b832d6` 开通 9528 HTTPS，目前为 `d5768d0`（中途无效的 keep-alive 调整已撤回），原 18765 停止监听；当前配置见 [开发机手册](server-100.58.19.213.md)，跨机器测试见 [桌面 HTTP 验证](2026-10-22-desktop-http-status.md)。

## 已部署

- 固定部署提交：`50bc0706aaa4d81f7e9fa857662f07f86c01c707`。其 Server 运行时代码与原桌面来源 `c69830b` 一致；共 11 个受控 Server 文件逐一 SHA-256 比对通过。代码通过 `git archive` 传输，无本地数据、虚拟环境或令牌。
- Ubuntu 24.04.4、Python 3.12.3。用户目录 venv 使用 PyPI 官方元数据 SHA-256 核验的 pip 26.2.2 wheel 引导，未安装系统软件；依赖严格按原 `requirements.lock.txt` 安装，`pip check` 无错误。
- `boa-audio-storage.service` 使用 `systemd --user` 托管，enabled / active；`Linger=yes`。数据独立存于 `/home/bobo/.local/share/boa-audio-storage`，token 权限 `0600`；服务只监听 `127.0.0.1:18765`，未授权列表请求返回 401。
- 原有 9527 服务未修改。App、固件和 API 运行时代码未改；没有发布、刷机或 AI 部署。

## 服务器内实际 HTTP 验证

| 项目 | 结果 |
| --- | --- |
| Linux Server pytest | 12 通过；1 条 TestClient/httpx 弃用警告 |
| 六份标准音频 | WAV、M4A、MP3、Ogg、101 MiB WAV、1 GiB WAV 全通过 |
| 上传与持久化 | 分片校验、首片重复幂等、后台合并完成、完整 SHA-256 和长度一致 |
| 崩溃与恢复 | 大文件上传两片后 SIGKILL 服务进程，再 stop/start，已确认分片仍可查询并续传 |
| 下载 | HEAD、ETag / If-Range、Range 206、前缀后续传、整文件 SHA-256 一致 |
| 可解码 | FFmpeg 本地全文件解码与认证 HTTP seek 解码通过；不是真人听音或 App 播放验收 |
| 服务重启 | 重启后列表持久化；自动重启独立验证另见下方 |
| 内存 | 本轮服务采样峰值 RSS 51.36 MiB，仅代表本轮数据，不作生产容量承诺 |

原始结构化结果：[HTTP 报告](evidence/2026-10-22-server-http.json)。测试在**实际部署的 systemd 服务**上运行，不是另外创建替代服务。

验收脚本与生成夹具保留在远端 `~/apps/boa-voice/verification/2026-10-22/`。脚本复用既有 `verify_live.py` 的六格式用例，将 start/stop 指向已部署 unit；HTTP seek 解码使用只读 loopback 测试代理注入凭据，不把 Bearer token 放进 FFmpeg 参数。测试数据与代码版本目录分离，上传成品仍保存在服务数据目录，占用约数 GiB；没有删除任何已有用户音频。

## Dart 客户端验证

运行地点为服务器内部。额外用户目录工具链 Dart 3.13.6，官方 SDK ZIP 的 SHA-256 核验通过。复制原 App 的 `storage_client.dart`、`local_library.dart`、`backup_queue.dart`，不改这三份代码；独立纯 Dart 验证包使用原锁定版本 `crypto 3.0.7`、`path 1.9.1`，不等同于服务器构建 Flutter App。现有验证工具仅把测试端口从 8765 改为 18765，使用独立会话和下载目录。

六份音频的真实 HTTP 上传、下载、断点恢复后 SHA-256 和重复上传去重全部通过。自动备份队列 → 实际 HTTP → 服务端哈希 → 重载防重复通过。见 [Dart 报告](evidence/2026-10-22-server-dart.json) 和 [备份报告](evidence/2026-10-22-server-backup.json)。这些是 Linux 上运行相同 Dart 客户端源码的结果，不是 Mac 跨机器测试。

## 当前连接阻塞与未验收

SSH 登录与文件传输成功，但 SSH 的 `direct-tcpip` 明确返回 `administratively prohibited`。本机虽能创建监听套接字，HTTP 随即被重置，故已停止无效隧道。`bobo` 无免密 sudo，且 `/etc/ssh/sshd_config.d/50-cloud-init.conf` 不可读，无法检查完整有效配置。未绕过限制或开放公网 HTTP。

因此，**Mac/App → SSH 隧道 → 远端 Server 的整条链路尚未通过**。需要管理员确认允许仅转发 `127.0.0.1:18765`，重新建连并验证；操作建议见 [服务器使用说明](server-100.58.19.213.md)。

未重启整机验证开机恢复，未做公网压力、实机 Clip、原始录音入库桥接、自定义模型 endpoint、ASR/摘要或 App 安装验收。服务器内测试通过不能替代这些项目。

## 异常拉起与最终运行状态

在所有客户端测试完成后，单独 SIGKILL 托管进程，没有手动启动；systemd 在 3.44 秒内自动拉起新进程，`NRestarts` 增长，HTTP 恢复 401，13 个已完成测试录音保留。之后关闭测试 SSH 会话，再通过新的 SSH 连接确认进程仍 active。未重启整机。

[部署状态报告](evidence/2026-10-22-server-deployment.json) 记录了代码提交、运行目录、新旧 PID、权限、恢复结果及仍失败的隧道状态。首次自动恢复验证误用了系统 Python，因缺少 httpx 在杀进程前退出；随后改用服务 venv 正确执行并通过，未改任何应用代码。

## 部署审查与边界决定

独立只读审查覆盖 unit、运行参数、版本及验证日志。未发现运行时部署问题；发现 SSH 诊断示例把 `host` 写成服务端主机名。该参数影响 Match 规则评估，已按 OpenSSH 官方手册改为明确的客户端主机名/源地址占位符并解释语义，检查引用与命令结构；未据此修改远端 SSH。

审查只读取本地证据，作者已通过 SSH 逐文件核对部署代码并复核 PID、unit 和权限；这不是独立审查者的远端复验，后续状态仍可能漂移。以下边界保留：

- 不重启整机，避免影响已有服务；因此开机恢复仍需另行验收。
- 不修改已有 App/Server 业务逻辑、固件、AI/桥接；这些功能的既有缺陷或未实现状态仍保留。
- 不开放公网，不做生产容量、物理 Clip 或 App 安装验收；本轮结果不能推广为对应功能已通过。
- SSH 有效策略和修改授权仍待管理员处理；Mac/App 访问仍未打通，不能用服务器内验证替代。
