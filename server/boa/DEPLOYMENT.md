# Boa 统一服务部署

从仓库根目录或解压包根目录运行 `python -m server`。一个进程同时提供 Web HTTPS 9529、API HTTPS 9528、Clip DTLS/UDP 9528，共用用户绑定和持久存储。Web `/api/` 请求交给同一后台；只有后台启动一次 DTLS 和清理任务。

## 安装与监听

```sh
python3 -m venv /path/to/boa-venv
/path/to/boa-venv/bin/python -m pip install -r server/requirements.txt
/path/to/boa-venv/bin/python -m server --data-dir /path/to/persistent-data --host 0.0.0.0 --port 9528 --web-port 9529 --tls-root /path/to/tls
```

防火墙放通 TCP 9529、TCP 9528、UDP 9528。TLS 目录包含 `private/server-chain.pem` 和 `private/server.key`，DTLS 使用 ECDSA P-256 证书，固件信任对应 CA。两个 HTTPS 监听默认复用该证书；若需已有独立 HTTPS 证书，同时传 `--https-certfile` 和 `--https-keyfile`，DTLS 仍使用 TLS 目录里的 ECDSA 证书。

App 使用原 HTTPS 地址与用户凭证，Clip 使用同一主机的 9528 和设备凭证。`--web-port 0` 关闭独立网页监听。本机可使用 `--http-only --host 127.0.0.1` 代替 `--tls-root` 做 HTTP 验证，该模式没有 DTLS。

依赖只有 `server/requirements.txt` 一个安装入口。代码包保留 `server/` 相对路径，包含 `boa/`、`storage/`、`web/` 及 DTLS 核心；不要从子目录执行脚本或设置旧模块路径。

## systemd 用户服务

完整仓库提供 `deploy/systemd/boa-server.service` 模板。它假定代码在 `%h/apps/boa-voice/current`，虚拟环境在 `%h/apps/boa-voice/venv`，数据在 `%h/.local/share/boa-server`，TLS 在 `%h/.config/boa-server/tls`。安装前按实际部署修改这些路径；升级已有实例时必须继续使用原持久目录。

复制模板到 `~/.config/systemd/user/boa-server.service`，核对凭证与目录权限，再执行：

```sh
systemctl --user daemon-reload
systemctl --user enable --now boa-server.service
systemctl --user status boa-server.service
```

模板使用 `UMask=0077`、`Restart=on-failure` 和固定工作目录，不含令牌或私钥。代码包没有仓库 `deploy/` 目录时，可按以下同等配置建立用户 unit：

```ini
[Unit]
Description=Boa Server Web API and Clip DTLS
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=%h/apps/boa-voice/current
ExecStart=%h/apps/boa-voice/venv/bin/python -m server --data-dir %h/.local/share/boa-server --host 0.0.0.0 --port 9528 --web-port 9529 --tls-root %h/.config/boa-server/tls
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
UMask=0077
NoNewPrivileges=true
Restart=on-failure
RestartSec=3
TimeoutStopSec=30

[Install]
WantedBy=default.target
```

ID 登录默认关闭。仅在可信开发网络中通过环境或 drop-in 显式设置 `BOA_ALLOW_ID_LOGIN=1`；ID 不能防冒用，普通 Cookie 会话不授予开发者权限。

## 升级、迁移与回退

1. 保存旧代码、虚拟环境、unit 和配置。停止占用 9528/9529 或原持久目录的旧实例，整体备份 SQLite、音频、检查点、私有配置和固件库；证书与凭证单独私密备份。
2. 解压新代码并核对 `MANIFEST.sha256`。在独立虚拟环境安装统一依赖，执行 `python -m server --help`、管理命令帮助及适用测试。
3. 将 unit 的工作目录切到新代码根目录，保留原 `--data-dir`、证书和凭证。原单用户音频目录需先由开发者确认用户归属，不能直接改名后自动分配。
4. 已有部署若使用旧的 `boa-audio-storage.service` 或 HTTPS drop-in，备份后停止并禁用旧实例，再启用统一 unit；仓库模板的删除不会操作已安装服务。不要同时启动两个服务。
5. 验证两个 HTTPS 入口、用户隔离、分片上传、鉴权 Range 下载及文件 SHA-256。随后验证设备凭证的真实 DTLS 收件，检查外部 UDP 可达性。HTTP 在线检查不能证明整条设备路径。

已有 `registry.sqlite3`、`users/<user>/audio`、`clip/<binding>`、HTTP 分片和 DTLS 检查点保持原布局。旧设备撤销后也需要显式开发者清理确认，迁移不会解除归属或自动把旧录音分给新用户。

发生问题时停止新服务，恢复旧代码、虚拟环境及 unit，并使用停机备份恢复一致的数据快照。不要让旧服务继续写入已迁移且尚未核对兼容性的数据库。新增字段或表不代表旧版本具备新绑定语义。

## 会话与权限

显式启用的 ID 登录会话哈希保存在原 `registry.sqlite3`。保留数据目录即可保留有效会话；7 天过期、退出、用户停用或关闭此模式后拒绝继续使用。Cookie 写请求校验同源 Origin，业务请求校验 `X-Boa-User`，跨页面身份变化返回 `409 session_user_changed`。

普通用户只访问自己的设备与文件；开发者登记通过 `python -m server.boa.manage`。绑定/确认/清理规则见 [业务说明](README.md)。远程部署、证书安装和真实 Clip 验收必须分别记录，不能用本地测试代替。
