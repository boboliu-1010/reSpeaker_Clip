# Boa 固件 Web 原型

网页和后端随同一个 Boa Server 包启动，没有前端构建依赖。前端 HTTPS 9529，业务 API 与 Clip DTLS/UDP 9528，共用一个数据目录和身份体系。

部署入口：`https://SERVER:9529/`；App / Clip 连接同一主机的 `SERVER:9528`。本机验收入口：`http://127.0.0.1:9529/`（HTTP-only，不启动 DTLS）。

## 统一服务启动

从仓库根目录或解压包根目录执行，所有 Server 依赖只从 `server/requirements.txt` 安装：

```sh
python3 -m venv .venv-boa
.venv-boa/bin/python -m pip install -r server/requirements.txt
.venv-boa/bin/python -m server --data-dir /path/to/persistent-data --host 0.0.0.0 --port 9528 --web-port 9529 --tls-root /path/to/tls
```

网页由 `server/web/` 提供，不需要独立前端服务。首次用户/设备登记使用 `python -m server.boa.manage`；TLS、持久目录和 systemd 见 [统一 Server 说明](../README.md) 与 [部署说明](../boa/DEPLOYMENT.md)。本机 HTTP 验证用 `--http-only --host 127.0.0.1` 代替 `--tls-root`，不启动 DTLS。

## 默认连接与简化操作

打开网页自动连接当前同源 Boa Server，无需输入网页后端地址。启用 `--allow-id-login` 的可信开发环境中，只输入已登记的用户 ID 即可进入，不需要密码或凭证文件；7 天内自动恢复会话，退出后重新输入。开发者令牌登录折叠保留。

ID 仅选择账户，不能防冒用已知 ID，该模式默认关闭。网页文件按所选用户隔离，Cookie 会话始终是普通用户。连接 Clip 后按当前用户自动取得已登记设备的上传配置，无需填写地址、设备 ID 或令牌。开发者登记方式见 [Server README](../boa/README.md#网页自动配置)。Wi-Fi 只在首次使用或换网时设置。

支持绑定协议的 Boa 固件连接后，网页按完整硬件 UID 取得所属用户配置，原子覆盖上传目标与凭证，读回 binding_id/epoch/revision 后上报客户端确认。保留 Wi-Fi、录音和自动上传开关；设备忙时等待空闲再自动重试，无需用户关闭上传。设备唯一标识在页面只读展示，方便开发者首次登记。

旧固件通过 IDENTITY 的“不支持命令”响应进入兼容模式；开启自动上传时保留原配置，需要升级固件才支持无缝覆盖。权限错误、busy 或部分新协议缺失不会退回旧命令覆盖。未登记设备提示开发者登记，不自行认领。

“我的设备”按当前用户显示绑定、配置和最近收件信息。解绑先撤销 Server 凭证，再对匹配的在线设备做受控清理；离线或清理失败保留“本地清理待完成”，重连可重试。Wi-Fi、设备录音和云端历史文件保留。Server 收件证据对应绑定，不能证明某个配置 revision。

服务在线不代表 Clip 已联网或上传成功；需要实际文件收件和哈希验证。

## 我的录音

- 使用当前登录身份，只显示该用户的文件；按上传时间倒序，支持翻页。
- 点击播放才下载，先校验长度和 SHA-256；Clip 原始 Opus 在浏览器封装为 Ogg，由 Chrome 解码。支持播放、暂停、继续、拖动和结束后重播。
- Clip 内存播放上限 8 MiB，标准音频 64 MiB；原文件保留。退出清空播放器并取消未完成请求。
- 真实 Clip 录音 23,901 字节 / 495 包 / 9.90 秒，已在 Chrome 实际播放；本轮迁移后的验证见 [集成验证](../../docs/development/2026-10-28-roger-integration.md)。

## 集成验证

当前分支采用 DTLS 基线的原生 SMP/OTA；`boa-binding.conf` 只启用用户绑定扩展。旧 `dtls-upload` profile 代表历史上禁用应用 DFU 的制品；支持当前 OTA 的签名镜像使用 `boa-dtls-ota-v1` 兼容 profile。Profile 是导入时核对的兼容性声明，不能让旧设备自动获得 OTA 能力。

本轮软件、构建及硬件验收边界见 [集成验证](../../docs/development/2026-10-28-roger-integration.md)。

## Server 怎么管理版本

| 信息 | 当前规则 |
|---|---|
| `release_id` | 每次导入生成独立制品 ID；新包不覆盖旧包 |
| `version` | 从 MCUboot 镜像头提取，不以文件名充当版本号 |
| `sha256` / `image_hash` | 分别校验整个下载文件和设备内的 MCUboot 镜像，不能混用 |
| `profile_id` | 区分标准 BLE、旧 DTLS、`boa-dtls-ota-v1` 和演示制品；profile 不改变设备已有能力 |
| 状态 | 草稿 → 发布 → 撤下；撤下后禁止下载，旧记录保留 |
| 权限 | 开发者导入/发布/撤下；用户查看共享的已发布固件，各自的升级记录按登录身份隔离 |

数据在 Boa Server 的 `<data-dir>/firmware/`：`index.sqlite3` 保存版本和升级记录，`<release_id>.bin` 保存制品，`trusted-key.pem` 保存验签公钥。签名私钥不进入 Server 或网页。进程重启两次后，发布/撤下状态、用户权限和下载内容均已验证保留。

## 网页操作步骤

1. **开发者准备**：取得目标板型对应的 MCUboot 应用核 `signed.bin`，核对源码提交、应用/网络核组合、签名公钥和镜像容量。目前页面不导入 ZIP/HEX，也不更新网络核。
2. **导入**：使用开发者身份登录 `/firmware/`，选 BIN 和真实 profile，点击“导入并校验”。验签通过后才可发布；演示包即使验签通过也不能刷写。
3. **发布**：点击该版本“发布”。用户可以看到并下载；下载后页面再次核对整文件 SHA-256。
4. **蓝牙连接**：Clip 开机，断开其他 App 的连接；网页点击“选择并连接 Clip”，在浏览器选择器中选择设备。
5. **升级**：仅对已具备 OTA 能力的设备，选择匹配固件并核对板型/网络核，再点击“开始升级”。旧 DTLS 需先通过 USB 安装支持 OTA 的固件；本次已完成 `0.1.2+201` 首装。
6. **核实**：上传结束只记为“待重连核实”；设备重启后点击“重连并核实目标版本”，要求目标镜像正在运行、哈希匹配且已确认，才记录成功。
7. **撤下**：发现版本问题时由开发者撤下，阻止后续下载；不会撤销已经刷入设备的版本。回退旧固件必须另行核对签名、兼容性和启动器防回退策略。

## 升级约束

`boa-dtls-ota-v1` 使用 RSA-2048 应用核包，Server 另设 954,368 字节的保守容量上限。构建时仍须核对分区和 MCUboot 元数据空间；不能将 8 MiB HTTP 限额或 983,040 字节备用槽容量当作可运行 BIN 大小。

只更新应用核，不导入 ZIP/HEX，不写 bootloader、网络核、Wi-Fi patch，不格式化存储。SMP 应用上传使用 group 1 / command 1 / image 0；USB bootloader 的 image 编号与 BLE 不能混用，应按实际 bootloader 实现核对。

## 刷写失败后的恢复

板级默认是 RSA-2048 签名、overwrite-only，没有自动回滚。Server 只保存验签公钥；私钥留在构建环境。

- 应用损坏但 bootloader 和 USB 恢复有效时，使用 bootloader USB SMP 上传匹配签名的应用。BLE 备用槽与 USB 主槽编号不能混用。
- bootloader 损坏或 USB 恢复失效时可能需要 SWD；恢复可能清除配置和配对，录音应事先备份。
- 不承诺任意失败均可恢复。本次集成不烧录硬件；实际验收需重新验证升级、重启读回、Wi-Fi 和录音完整性。

参考：[仓库 USB 操作](../../docs/usb_dfu.md)、[板级配置](../../boards/seeed/clip/Kconfig.sysbuild)。

## 本地验证

```sh
python -m pytest server/tests server/boa/tests server/storage/tests -q
node --test server/web/tests/*.test.mjs
```

软件 HTTP 测试会模拟 BLE 字节链路，用于验证绑定协议和文件隔离；不会写入真实设备升级记录。演示制品 `demo-offline` 永远不能刷写。可执行固件必须固定源码、配置、依赖和签名链后重新编译，不可修改已经签名的 BIN 版本字段。

## Wi-Fi 手动配网

网页直接通过蓝牙连接 Clip、读取设备已保存的 Wi-Fi、手动填写名称和密码并保存测试，不依赖 Boa Voice 桌面端。保留密码显示/隐藏及本页输入；当前固件未提供实时 Station 在线字段，因此设备已保存配置与最近检测分别显示。

Wi-Fi 周边列表和 Mac 当前网络匹配由桌面原生 Clip 页提供。网页不再启动或调用本机扫描助手，CSP 仅允许同源 API。录音列表、播放、设备配置和固件功能继续保留。

见[集成验证与限制](../../docs/development/2026-10-28-roger-integration.md)。
