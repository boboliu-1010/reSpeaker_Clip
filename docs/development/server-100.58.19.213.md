# Boa 开发服务器

当前入口：**https://100.58.19.213:9528**。同一 Boa Server 进程提供 HTTPS/TCP 与 DTLS/UDP，App 使用用户凭证，Clip 使用设备凭证。

| 项目 | 当前配置 |
| --- | --- |
| 用户服务 | boa-server-beta4.service，已启用用户服务 |
| 代码 | /home/bobo/apps/boa-server-beta4/code |
| Python 环境 | /home/bobo/apps/boa-server-beta4/venv |
| 身份/设备/Clip 索引与数据 | /home/bobo/.local/share/boa-server-beta4 |
| 已有音频存储 | 新目录 users/bobo/audio 指向 /home/bobo/.local/share/boa-audio-storage，保留原音频和上传 ID |
| 更新前备份 | /home/bobo/apps/boa-server-beta4/backups/audio-pre-beta4.tar 与旧 unit/配置 |
| HTTPS 证书 | 沿用原私有 TLS 文件；到期 2026-11-05 07:00:17 UTC |
| DTLS 证书 | boa-server-beta4/tls/private 中 ECDSA 证书；Clip 需包含对应 CA |

访问凭证和私钥不进入仓库。Mac 已有 HTTPS 凭证/证书保存在 ~/.config/boa-voice，新增设备凭证 development-clip01-beta4.token 与公开 DTLS CA development-clip-dtls-ca.pem（设备 ID clip01）。用户文件归 bobo；旧共享数据此次由开发者明确指定归属。

## 状态与更新

```sh
ssh bobo@100.58.19.213 'systemctl --user status boa-server-beta4 --no-pager'
ssh bobo@100.58.19.213 'journalctl --user -u boa-server-beta4 -n 30 --no-pager'
```

部署使用独立环境。停止服务后备份完整数据目录（包含旧音频目录的实际内容），再切换代码和依赖。不要使用多个 worker 共用目录，也不要只备份 SQLite。

回滚：停止/禁用 boa-server-beta4，启用并启动原 boa-audio-storage.service。旧代码、环境、TLS 与原存储保留。Beta 期间新增的 Clip 文件归属和原件在新数据目录，不应删除。

## 验证记录

- 服务器运行环境：20 项新服务/既有存储测试通过，包括真实 DTLS 握手与恢复。
- 本机到开发机 HTTPS：64 MiB WAV 上传、下载、整文件 SHA256 一致；首轮上行约3.28 MB/s、下行约0.99 MB/s；连接修复后的复测上行约1.30 MB/s、下行约1.03 MB/s（含客户端哈希/落盘与完成确认）。
- 实际 HTTPS 用户隔离：另一用户查不到列表和 metadata/content/HEAD；无效凭据401。
- 2026-10-26 外部 UDP 9528 复测通过：Mac 直连开发机，连续 3 次完成 DTLS 握手、65,553 字节上传、落盘回执、HTTPS 列表查询和下载，SHA256 一致。证书链与 IP 均校验通过。[测试记录](../testing/2026-10-26-udp-9528.md)

[服务安装说明](../../services/boa_server/README.md)
