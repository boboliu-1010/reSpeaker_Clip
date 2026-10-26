# Boa Server Beta 4

一个服务：App 使用 HTTPS，Clip 使用 DTLS/UDP。两种监听默认使用同一端口 9528。App 用户凭证与设备凭证分开，每个用户的音频独立存储。

## 安装与登记

从仓库根目录执行（Python 3.12+）：

```sh
python3 -m venv .venv-boa
.venv-boa/bin/pip install -r services/boa_server/requirements.txt
.venv-boa/bin/python services/boa_server/manage.py --data-dir "$HOME/.local/share/boa-server" add-user bobo --token-out "$HOME/.config/boa-user.token"
.venv-boa/bin/python services/boa_server/manage.py --data-dir "$HOME/.local/share/boa-server" add-device clip01 --owner bobo --token-out "$HOME/.config/boa-clip.token"
```

凭证只写入指定的私有文件，数据库保存凭证哈希。App 填用户凭证，Clip 填设备凭证。登记和换绑由开发者执行；换绑前完成旧上传并确认设备未上传录音，再撤销旧凭证：

```sh
.venv-boa/bin/python services/boa_server/manage.py --data-dir "$HOME/.local/share/boa-server" revoke-device clip01
```

新绑定重新执行 add-device，使用新凭证。历史文件保留原所属用户。相同录音 session/segment 在新绑定中使用新的存储命名空间。

## 启动

证书目录需要 `private/server-chain.pem` 和 `private/server.key`。DTLS 使用 ECDSA P-256 证书，证书 SAN 必须包含访问的主机名/IP，Clip 固件需包含对应 CA。不要提交私钥和凭证。

```sh
.venv-boa/bin/python services/boa_server/run.py --data-dir "$HOME/.local/share/boa-server" --host 0.0.0.0 --port 9528 --tls-root /path/to/tls
```

防火墙同时放通 TCP 和 UDP。一个实例持有数据目录进程锁；不支持多个 worker 共用目录。App 导入开发证书后仍校验证书链和主机名。

仅在本机验证 App 上传时，可用 `--http-only --host 127.0.0.1` 替代 `--tls-root`，该模式没有 DTLS 接收。

## App 与设备操作

1. App「服务设置」填 HTTPS 根地址和用户令牌；开发证书可通过文件选择器导入。
2. 「Clip 设备」连接并配对，在「联网与自动上传」填写 Wi-Fi。
3. 填同一个 Server 的主机:端口、设备 ID、设备令牌，保存后检查 Wi-Fi。
4. 同步设备时间，开启自动上传。停止录音后等待设备空闲上传。
5. 「服务器音频」刷新查看 App 和 Clip 来源；原始 Clip 文件可下载导出，标注为原始录音。

配置命令要求一次 GATT 写入能容纳 UTF-8 字节；过长时 App 会阻止发送。上传通知为尽力投递，重连/丢事件后查询实际状态。Wi-Fi 检查只验证关联/DHCP；最终整文件校验及 COMPLETE 才证明上传完成。production 固件可能在确认整段录音上传后删除设备副本。

## 接口与数据

- `/api/audio/uploads` 及分片、完成、查询、取消接口：按用户复用大文件上传。
- `/api/audio/recordings` 及 metadata/content/HEAD/Range：按用户隔离。
- `GET /api/boa/v1/audio-files?offset=0&limit=50`：App/Clip 统一列表，created/id 倒序。
- `GET/HEAD /api/boa/v1/audio-files/{id}/content`：Clip 原始文件，支持 Range 和 SHA256 ETag。
- Clip：DTLS v3 `OPEN/DATA/QUERY/ACK/FINISH/COMPLETE/ERROR`，1 KiB DATA、单段最大 8 MiB。

列表在原有必要字段之外携带 sha256/mime/state，便于下载校验。所有 HTTP API 使用 `Authorization: Bearer <user_token>`。未知用户返回 401，其他用户的文件/上传 ID 返回 404。

数据目录包含 registry.sqlite3、users/<user>/audio、clip/<binding>。先持久记录设备来源和归属，再接收文件；完整落盘校验后才进入列表。重启及周期对账补齐“文件已落盘、索引未完成”。DTLS 与 App 不向同一目录写入。备份时停止服务，整体备份数据目录。

## 验证

```sh
.venv-boa/bin/python -m pytest services/boa_server/tests services/audio_storage/tests -q
.venv-boa/bin/python -m unittest discover -s tools/https_poc -p 'test_dtls_*.py'
```

基础固定版本：a2319ce88cbf274612d0cc68a004c1cdafe2bdbe。基础固件/接收目录保持该版本，业务扩展位于 services/boa_server。

维护已有 HTTPS 证书时，可额外传入 `--https-certfile /path/server.pem --https-keyfile /path/server.key`。HTTPS 继续使用指定证书，DTLS 使用 tls-root 下的 ECDSA 证书；仍由同一服务管理。已有单用户数据只能由开发者确认归属后，将 `users/<user>/audio` 指向原数据目录；旧文件不自动分配给新用户。
