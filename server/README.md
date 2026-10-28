# Boa Server + Web

一个 Python 服务管理 Web、API、Clip DTLS 接收、用户绑定与音频存储，共用一个持久数据目录。

| 入口 | 默认地址 | 用途 |
|---|---|---|
| Web HTTPS | `https://SERVER:9529/` | 网页录音、设备配置、固件管理；`/api/` 同源转交同一后台 |
| API HTTPS | `https://SERVER:9528/` | App 与业务 API、上传及鉴权下载 |
| Clip DTLS/UDP | `SERVER:9528` | 设备凭证认证、断点续传、整文件校验 |

## 安装与启动

从仓库根目录或解压包根目录执行，使用 Python 3.12+。所有 Server 依赖统一锁定在 `server/requirements.txt`：

```sh
python3 -m venv .venv-boa
.venv-boa/bin/python -m pip install -r server/requirements.txt
.venv-boa/bin/python -m server --help
.venv-boa/bin/python -m server.boa.manage --help
```

首次登记用户和设备时，凭证只写入指定的私有文件，不输出到终端：

```sh
.venv-boa/bin/python -m server.boa.manage --data-dir /path/to/persistent-data add-user USER --token-out /private/path/user.token
.venv-boa/bin/python -m server.boa.manage --data-dir /path/to/persistent-data add-device DEVICE --owner USER --token-out /private/path/device.token
```

已有部署升级时直接复用原数据目录和原凭证，不重复登记。启动统一服务：

```sh
.venv-boa/bin/python -m server --data-dir /path/to/persistent-data --host 0.0.0.0 --port 9528 --web-port 9529 --tls-root /path/to/tls
```

TLS 目录需要 `private/server-chain.pem` 和 `private/server.key`。DTLS 使用 ECDSA P-256 证书，设备须信任对应 CA；HTTPS 证书 SAN 须覆盖访问地址。可使用 `--https-certfile` 与 `--https-keyfile` 为两个 HTTPS 监听指定已有证书，DTLS 仍使用 TLS 目录内的证书。

放通 TCP 9529、TCP 9528 和 UDP 9528。一个进程持有数据目录锁，不使用多个 worker 共用目录。`--web-port 0` 可关闭独立 Web 监听。

本机 HTTP 验证：

```sh
.venv-boa/bin/python -m server --data-dir /tmp/boa-local-test --host 127.0.0.1 --port 9528 --web-port 9529 --http-only
```

该模式不启动 DTLS。可信开发网络可显式增加 `--allow-id-login`；ID 仅选择已登记账户，不证明身份，正式多用户环境使用真实用户认证。网页会话不授予开发者权限。

## 源码布局

| 目录或文件 | 职责 |
|---|---|
| `__main__.py` | 统一启动入口 `python -m server` |
| `boa/` | 用户、设备绑定、同源 Web/API、DTLS 归属、固件库 |
| `storage/` | 按用户挂载的 HTTP 分片上传、SQLite 索引、Range 下载 |
| `web/` | 无构建依赖的网页静态资源与 JavaScript 模块 |
| `dtls_*.py`、`resume_store.py` | 共享 DTLS v3、持久检查点与文件校验核心 |
| `requirements.txt` | 唯一 Server 依赖安装入口 |

设备 UID 登记、客户端确认、解绑与开发者清理锁见 [业务配置说明](boa/README.md)。部署、systemd 和数据迁移见 [部署说明](boa/DEPLOYMENT.md)。网页操作见 [Web 说明](web/README.md)，HTTP 存储协议见 [存储说明](storage/README.md)。

## 数据、升级与回退

数据目录中的 `registry.sqlite3`、`device-configurations.json`、`users/`、`clip/`、`firmware/` 需整体保留；证书、私钥和凭证放在源码与代码包之外。停止旧服务后备份 SQLite 和文件，保留旧代码及虚拟环境，再切换新代码入口。目录整合不会自动移动、删除或重新分配既有数据。

原单用户存储的数据必须由开发者核对归属后迁入已登记用户目录，不能直接当作新的统一数据根目录。设备换用户前必须撤销旧凭证，并明确确认旧录音、Wi-Fi、上传配置和配对已处理；清理锁不能通过重新登记绕过。

`server.dtls_upload_server` 是底层协议测试/维护入口；正常部署统一使用 `python -m server`，不另起独立接收或存储进程抢占端口与数据目录。

## 验证与代码包

```sh
.venv-boa/bin/python -m pytest server/boa/tests server/storage/tests -q
.venv-boa/bin/python -m unittest tools.upload.tests.test_dtls_receiver -v
node --test server/web/tests/*.test.mjs
```

完整仓库还可运行 `tools/upload/tests` 的固件主机测试。代码包只携带必要的 DTLS 测试辅助文件，不携带固件 SDK 或构建产物；真实 DTLS 用例需要锁定的 pyOpenSSL 依赖，Web HTTP 集成用例需要 Node.js。

从完整仓库执行 `bash scripts/package-boa-server.sh` 生成 `dist/Boa-Server-Web-beta.8.tar.gz` 及 SHA-256。解压后先核对归档 SHA-256，再在包根目录运行 `shasum -a 256 -c MANIFEST.sha256`。`BUILD.json` 标记源码提交及工作区快照；代码包不包含用户数据、录音、固件二进制、证书或凭证。

软件测试、打包和固件编译不等于远程部署或真实 Clip 验收。收件验收需要实际上传、完整哈希与鉴权下载；配置确认仅记录客户端读回证据。
