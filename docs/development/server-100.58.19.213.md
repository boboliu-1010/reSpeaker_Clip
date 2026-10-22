# Boa 开发服务器

用户指定后续开发与部署测试使用 `ssh bobo@100.58.19.213`（主机名 `sun-dev-node001`）。这是开发环境，未部署 AI 或 Clip 原始上传桥接。

## 目录与服务

| 项目 | 路径/设置 |
| --- | --- |
| 代码版本 | `/home/bobo/apps/boa-voice/releases/<完整提交 SHA>/services/audio_storage` |
| 当前版本 | `/home/bobo/apps/boa-voice/current` 符号链接 |
| Python 环境 | `/home/bobo/apps/boa-voice/venv`，Python 3.12，按 requirements.lock.txt 安装 |
| 持久数据 | `/home/bobo/.local/share/boa-audio-storage`，独立于代码与测试目录 |
| API 令牌 | 数据目录的 `token`，0600，勿提交/输出 |
| 用户服务 | `~/.config/systemd/user/boa-audio-storage.service`，模板见 `deploy/systemd/boa-audio-storage.service` |
| 监听 | `127.0.0.1:18765`，HTTP；公网不开放 |
| 生命周期 | `systemctl --user enable --now boa-audio-storage`；`loginctl show-user bobo -p Linger` 应为 yes |

无免密 sudo；部署未安装系统包。原有服务不变。未重启服务器验收开机启动；已启用用户服务和 linger。

## Mac / App 连接

```sh
ssh -N -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:18765:127.0.0.1:18765 bobo@100.58.19.213
```

保持连接后，在 App 的服务器配置中使用 `http://127.0.0.1:18765`，令牌取远端数据目录的 `token`。可以在自己终端用下面命令复制到剪贴板，勿粘贴到聊天或源码：

```sh
ssh bobo@100.58.19.213 'cat ~/.local/share/boa-audio-storage/token' | pbcopy
```

本机已有转发时再次运行会提示端口占用；先复用已有连接，或显式选择其他本地端口。连接 Mac 上的这个 localhost 实际访问远端，退出隧道后连接断开；服务器仍继续运行。

## 日常运维与更新

```sh
ssh bobo@100.58.19.213 'systemctl --user status boa-audio-storage --no-pager'
ssh bobo@100.58.19.213 'journalctl --user -u boa-audio-storage -n 60 --no-pager'
ssh bobo@100.58.19.213 'systemctl --user restart boa-audio-storage'
```

更新前固定 Git 提交，使用 `git archive <SHA> services/audio_storage` 导出纯源码，再通过 SSH 解包至新的 `releases/<SHA>`；不要 rsync 带上本地 `data/`、`.venv/`、`artifacts/` 或令牌。安装该版本锁定依赖并测试后，切换 `current` 链接，再重启服务。保留旧版本。若依赖变化，回滚代码时也需恢复对应依赖；当前单独 venv 不是任意版本间完整环境回滚机制。

数据使用 SQLite 和磁盘文件。备份前停止服务，将整个数据目录一起备份，然后启动；不要只备份数据库。不得运行多个 worker 共享同一目录。测试夹具与验收证据另放 `~/apps/boa-voice/verification/`；服务中的测试上传文件仍占用持久空间，不要误当作用户录音删除。

具体部署提交、依赖、验收结果另见本目录的部署验证记录。签名公证、App 发布、实机 Clip、原始 Opus 入库和模型任务不属于本轮部署。
