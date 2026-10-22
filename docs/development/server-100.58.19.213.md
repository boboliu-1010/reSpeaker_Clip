# Boa 开发服务器

用户指定后续开发与部署测试使用 `ssh bobo@100.58.19.213`（`sun-dev-node001`）。2026-10-22 经用户确认 9528 放通后，Boa 音频库切换为 **`https://100.58.19.213:9528`**。这是开发环境，尚未实现 AI 或 Clip 原始上传入库桥接。

## 目录与服务

| 项目 | 路径/设置 |
| --- | --- |
| 当前代码 | `/home/bobo/apps/boa-voice/current` → `releases/d5768d0d000b12895f94c35da7d1d74c3e56dfe2` |
| Python 环境 | `/home/bobo/apps/boa-voice/venv`，Python 3.12，按 requirements.lock.txt 安装 |
| 持久数据 | `/home/bobo/.local/share/boa-audio-storage`，独立于代码与测试目录 |
| API 令牌 | 数据目录的 `token`，0600，勿提交或输出 |
| 用户服务 | `~/.config/systemd/user/boa-audio-storage.service` |
| HTTPS 配置 | `~/.config/systemd/user/boa-audio-storage.service.d/9528-https.conf`，仓库 deploy/systemd 下有同名模板 |
| 当前监听 | `0.0.0.0:9528` HTTPS；原 `127.0.0.1:18765` 已停止监听 |
| TLS 文件 | 数据目录的 `tls/server.pem`、`tls/server.key`，0600 |
| 生命周期 | 已启用用户服务，Linger=yes；此前已验证异常退出自动恢复，未重启整机验收 |

9527 是 Roger 的独立 Clip 原始接收服务，未修改。9528 提供 Boa `/api/audio`，不是 Clip `/v2` 接收端。系统 SSH 转发策略保持原状，当前测试不依赖隧道。下载连接现由桌面客户端明确退出复用池，以处理大文件下载后的下一次上传断连；延长 Server keep-alive 曾尝试但无效，已撤回，当前保持 Uvicorn 原有 5 秒默认值。失败记录与最终复测见下方桌面 HTTP 验证。

## Mac 客户端测试与证书

9528 使用仅供开发的自签名证书，SAN 为 `IP:100.58.19.213`，SHA-256 指纹：

```text
92:64:F7:DB:7C:C9:69:5A:D5:B1:30:41:E6:07:76:95:D0:54:24:C3:BA:D2:48:1B:29:D2:56:EB:E7:05:AA:3F
```

有效期 **2026-10-22 07:00:17 UTC 至 2026-11-05 07:00:17 UTC**（北京时间到期日 15:00:17）。证书只通过已验证 SSH 主机连接传到本机，随后由测试进程显式信任；并未关闭证书或主机名验证，未改系统钥匙串。

本 Mac 的受保护文件：

- `~/.config/boa-voice/development-100.58.19.213.token`：Boa 令牌。
- `~/.config/boa-voice/development-100.58.19.213-9528.pem`：该开发证书，公开内容也不必混入源码。

重跑桌面同一 `StorageClient` 的测试：

```sh
cd /Users/bobo/code/respeaker-boa-integration/mobile/app
BOA_TEST_CA_FILE="$HOME/.config/boa-voice/development-100.58.19.213-9528.pem" \
  dart --packages=.dart_tool/package_config.json \
  ../../deploy/benchmarks/desktop_audio_http.dart \
  https://100.58.19.213:9528 \
  "$HOME/.config/boa-voice/development-100.58.19.213.token" \
  ../../services/audio_storage/artifacts/tone-101MiB.wav \
  "$HOME/.cache/boa-voice/desktop-http/remote/full" 3
```

上面的 WAV 是已生成的合成测试夹具，未提交到 Git；换机器需先准备音频。工具会新增测试录音，不自动删除。结果与计时口径见 [桌面 HTTP 验证](2026-10-22-desktop-http-status.md)。

**已安装 GUI App 没有配置这份证书或修改服务器设置。** 默认信任连接这份自签名证书会失败。本轮验证是 Mac 上桌面生产客户端类的真实跨机器传输，不是点击 GUI 或发布版本验收。后续 GUI 接入需正式受信任证书，或另外设计受控开发证书配置；不要使用跳过 TLS 验证的回调。

## 日常运维与更新

```sh
ssh bobo@100.58.19.213 'systemctl --user status boa-audio-storage --no-pager'
ssh bobo@100.58.19.213 'journalctl --user -u boa-audio-storage -n 60 --no-pager'
ssh bobo@100.58.19.213 'systemctl --user restart boa-audio-storage'
```

更新前固定 Git SHA，通过 `git archive <SHA> services/audio_storage deploy/systemd` 导出纯源码，SSH 解包到新 `releases/<SHA>`。不要带上本地 `.venv/`、`artifacts/`、数据或令牌。按锁定依赖安装并运行测试，通过后切换 `current`、重启。TLS 私钥和用户 drop-in 不随代码发布，切换代码仍会保留。

证书到期前需要换新并经 SSH 核对、分发新的公开证书，再重启服务与测试进程。没有设置自动续期，不能把当前开发证书当作长期部署。后续可换成正式域名与受信任证书。

数据为 SQLite + 磁盘。备份时停止服务，整体备份数据目录再启动；不要只备份数据库。禁止多个 worker 共享同一目录。测试上传也占用持久空间，不要混同用户录音删除。

## 回滚与历史

9528 配置是 drop-in；撤销它并重启后，基础 unit 恢复 `127.0.0.1:18765` HTTP。若还要回滚代码，可将 `current` 指回 `releases/50bc0706aaa4d81f7e9fa857662f07f86c01c707`；必须先撤销 TLS drop-in，因为旧 launcher 不接受 TLS 参数。当前依赖未变；任意未来版本回滚仍需核对依赖兼容性。

[原始部署验收](2026-10-22-server-deployment-verification.md)、[早先 SSH/回环速度](2026-10-22-throughput-verification.md)、[9527 端口检查快照](2026-10-22-server-port-inventory.md) 均保留历史时点，不代表当前仍监听 18765。没有改防火墙、系统 SSH、Roger 服务、已安装 App 或用户录音；没有发布、推送或打包 DMG。
