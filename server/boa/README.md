# Boa Server + Web Beta

一个服务、一个数据目录：**网页 HTTPS 9529；后端 API HTTPS 与 Clip DTLS/UDP 9528**。9529 的同源 `/api/` 请求直接交给同一个后台实例，鉴权、上传和 Range 下载保持一致。App 用户凭证与设备凭证分开，每个用户的音频独立存储。

## 安装与登记

从仓库根目录执行（Python 3.12+）：

```sh
python3 -m venv .venv-boa
.venv-boa/bin/pip install -r server/requirements.txt
.venv-boa/bin/python -m server.boa.manage --data-dir "$HOME/.local/share/boa-server" add-user bobo --token-out "$HOME/.config/boa-user.token"
.venv-boa/bin/python -m server.boa.manage --data-dir "$HOME/.local/share/boa-server" add-device clip01 --owner bobo --token-out "$HOME/.config/boa-clip.token"
```

凭证只写入指定的私有文件，数据库保存凭证哈希。App 填用户凭证，Clip 填设备凭证。登记和换绑由开发者执行；换绑前完成旧上传并确认设备未上传录音，再撤销旧凭证：

```sh
.venv-boa/bin/python -m server.boa.manage --data-dir "$HOME/.local/share/boa-server" revoke-device clip01
```

完成下文的开发者清理确认并释放交接锁后，再执行 add-device，使用新凭证。历史文件保留原所属用户。相同录音 session/segment 在新绑定中使用新的存储命名空间。

## 启动

证书目录需要 `private/server-chain.pem` 和 `private/server.key`。DTLS 使用 ECDSA P-256 证书，证书 SAN 必须包含访问的主机名/IP，Clip 固件需包含对应 CA。不要提交私钥和凭证。

```sh
.venv-boa/bin/python -m server --data-dir "$HOME/.local/share/boa-server" --host 0.0.0.0 --port 9528 --web-port 9529 --tls-root /path/to/tls
```

防火墙放通 TCP 9529、TCP 9528、UDP 9528。打开 `https://SERVER:9529/` 进入网页；App 与 Clip 的目标仍为 9528。两个 HTTPS 入口使用同一证书，一个实例持有数据目录进程锁；不支持多个 worker 共用目录。App 导入开发证书后仍校验证书链和主机名。`--web-port 0` 可关闭独立网页监听。

仅在本机验证 App 上传时，可用 `--http-only --host 127.0.0.1` 替代 `--tls-root`，该模式没有 DTLS 接收。

## App 与设备操作

### 网页自动配置

用户在网页登录并连接 Clip 后，由 Server 自动提供所属设备的上传配置；无需填写设备 ID、设备令牌或上传地址。开发者首次为已登记设备导入原凭证：

```sh
.venv-boa/bin/python -m server.boa.manage --data-dir "$HOME/.local/share/boa-server" configure-device clip01 --name "Clip C7BB" --endpoint YOUR_SERVER:9528 --token-file "$HOME/.config/boa-clip.token"
```

配置存于数据目录 `device-configurations.json`，权限 0600；含设备凭证，需随数据目录私密备份，不提交或分发。登记操作不轮换凭证、不改变文件归属。撤销/换绑会阻止旧配置继续下发。免密码 ID 登录仍仅用于可信开发网络。

`POST /api/boa/v1/devices/configuration` 接收 `{"device_name":"Clip C7BB"}`，按当前登录身份返回已分配配置；不接收 owner 或用户指定目标。Cookie 请求沿用同源、X-Boa-User 检查，响应不缓存。

旧固件使用上述名称配置接口；名称相同的多个设备不能通过此接口区分，Server 会拒绝歧义请求。支持绑定协议的固件按完整 UID 获取配置，不依赖 BLE 名称；上传开关保持原值，设备忙时等待空闲后自动重试。新设备未登记时联系开发者。

开发者从设备 `AT+IDENTITY?` 获取完整硬件 UID 后，显式登记到原设备 ID 和原绑定（不从短名称推断 UID）：

```sh
.venv-boa/bin/python -m server.boa.manage --data-dir "$HOME/.local/share/boa-server" configure-device clip01 --name "Clip C7BB" --uid FULL_LOWERCASE_HARDWARE_UID --endpoint YOUR_SERVER:9528 --token-file "$HOME/.config/boa-clip.token"
```

UID 为 16–64 个小写十六进制字符且长度为偶数，首次登记固定到原设备 ID。已有绑定、epoch 和令牌保持不变；同值导入不改变 revision，实际配置变化递增 revision。重新导入不带 `--uid` 的旧命令会保留已经登记的 UID。

新接口沿用用户 Bearer 或同源 Cookie 与 `X-Boa-User` 校验，配置响应 `Cache-Control: no-store`：

- `GET /api/boa/v1/devices`：只列当前用户分配的设备，包含 UID、binding_id、epoch、revision、provisioning_state 和设备清理状态，不含令牌。
- `POST /api/boa/v1/devices/{id}/binding`：请求 `{ "device_uid": "..." }`，核对归属和 UID 后下发原凭证；不创建归属或轮换令牌。
- `POST /api/boa/v1/devices/{id}/binding/confirm`：请求 `{ "device_uid": "...", "binding_id": "...", "revision": 1, "saved": true }`，记录客户端读回确认，不能据此宣称硬件或上传已验证。
- `DELETE /api/boa/v1/devices/{id}/binding`：立即撤销 Server 凭证；离线设备返回 `device_cleanup_pending: true`，不会声称远程清理硬件。

`last_received_at` 为已通过文件校验的该 binding/epoch 的来源时间（Unix 秒），与客户端配置确认独立；DTLS v3 不携带 revision，`last_upload_revision` 始终为 null。云端历史录音继续归原用户。

所有设备（包括尚未登记 UID 的旧设备）撤销后，`add-device` 都会被持久清理锁阻止；旧数据库中没有清理证据的撤销记录也会在迁移时锁定。开发者确认旧录音已经同步或经授权清理，并完成旧 Wi-Fi、上传设置和蓝牙配对清理后，才执行显式确认命令释放交接锁：

```sh
.venv-boa/bin/python -m server.boa.manage --data-dir "$HOME/.local/share/boa-server" complete-device-cleanup clip01 --uid FULL_LOWERCASE_HARDWARE_UID --binding-id REVOKED_BINDING_ID --confirm-old-data-wifi-and-pairing-cleaned
```

旧设备尚无 UID 时，开发者必须先读取完整硬件 UID；此确认会将 UID 固定到原设备 ID。此命令只记录开发者确认，不在设备执行任何清理。之后才可 `add-device` 分配新用户，再将相同 UID 导入新绑定；新绑定使用新 epoch 和凭证。旧云端录音及清理历史保留。

### App 操作

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
.venv-boa/bin/python -m pytest server/boa/tests server/storage/tests -q
.venv-boa/bin/python -m pytest tools/upload/tests server/boa/tests server/storage/tests -q
```

统一服务使用 `python -m server` 启动；业务位于 `server/boa`、HTTP 存储位于 `server/storage`、网页位于 `server/web`，DTLS 核心位于 `server/`。唯一依赖入口是 `server/requirements.txt`。完整仓库的固件与主机测试位于 `applications/clip` 和 `tools/upload`。

维护已有 HTTPS 证书时，可额外传入 `--https-certfile /path/server.pem --https-keyfile /path/server.key`。HTTPS 继续使用指定证书，DTLS 使用 tls-root 下的 ECDSA 证书；仍由同一服务管理。已有单用户数据只能由开发者确认归属后，将 `users/<user>/audio` 指向原数据目录；旧文件不自动分配给新用户。

## 固件 Web 原型

工作台由同一服务的 `/firmware/` 提供。示例固件不可刷写，演示模式禁止 OTA。接口位于 `/api/boa/experimental/firmware`，现有音频与 DTLS 接口保持原有路径。

使用、权限、可信公钥配置及真实设备限制见 [网页操作说明](../web/README.md)。部署此版本时须包含 `server/web/` 静态资源目录。

## 我的录音与播放

网页使用当前用户会话读取文件，按上传时间倒序，点击后鉴权下载并校验原件 SHA-256。Clip 原始 Opus 在网页封装为 Ogg，由 Chrome 解码；Server 保留原件，不安装转码服务。支持播放、暂停、继续和拖动；退出会停止播放并释放浏览器缓存。Clip 单段上限 8 MiB，标准音频网页播放上限 64 MiB，更大文件使用现有下载功能。

## 集成包

仓库根目录执行 `bash scripts/package-boa-server.sh`，生成 `dist/Boa-Server-Web-beta.8.tar.gz` 和 SHA-256。包中只包含 `server/` 源码（含 Web、业务、存储与 DTLS 核心）、必要 DTLS 测试辅助文件、唯一依赖清单 `server/requirements.txt`、使用说明和逐文件校验清单；用户数据、证书和凭证另行保存在持久目录。解压后按上面的命令安装和启动。

## 网页用户 ID 登录（可信开发网络）

启动增加 `--allow-id-login`，或显式设置 `BOA_ALLOW_ID_LOGIN=1`。该模式默认关闭，部署时须显式选择是否启用。

打开网页自动连接当前 Server，输入已登记的用户 ID即可进入，不需要密码或凭证文件。浏览器保存 7 天 HttpOnly、SameSite=Strict 会话，HTTPS 下为 Secure；刷新和重新打开会自动恢复，退出会撤销会话。网页不使用 localStorage 保存令牌。

ID 是账户选择器，不提供防冒用认证，只用于可信开发网络。录音仍按所选用户查询和存储；开发者权限继续使用折叠入口中的 Bearer 令牌，ID 会话始终为普通用户。App Bearer 与 Clip DTLS 设备凭证保持原协议。

| API | 功能 |
|---|---|
| `GET /api/boa/v1/health` | 无身份信息的在线检查 |
| `POST /api/boa/v1/session` | 同源 JSON `{"user_id":"bobo"}`，设置会话 Cookie |
| `GET /api/boa/v1/session` | 恢复当前会话身份 |
| `DELETE /api/boa/v1/session` | 退出并撤销当前会话 |

Cookie 身份访问业务接口必须带 `X-Boa-User`，Server 原子核对是否与 Cookie 用户一致；网页间切换账户时，旧页面清空本地身份与播放器，避免错标用户。Cookie 写操作必须通过同源 Origin 校验。原 Bearer 请求不受此扩展影响。

设备上传地址和设备凭证放在折叠的高级设置；已有配置无需重复填写。新用户仍由开发者登记，不提供匿名访问或自助设备认领。
