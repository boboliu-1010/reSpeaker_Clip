# Roger 固件与 Boa Voice 集成

当前开发分支：`boa/roger-integration`。固件基于 Roger 的 DTLS 分支 `feature/dtls-upload-core-0.1.2`，固定提交 `c8d72c01468ef0765ea94db8429a927d7f05d12d`。Roger 原生 OTA、上传、显示、电量及板级配置作为基础，Boa 用户绑定与录音归属保护通过可选 `applications/clip/boa-binding.conf` 启用。

[产品功能](docs/product/boa-voice-overview.md) · [桌面使用说明](README-desktop.md) · [模块与扩展约定](docs/contracts/roger-base-extension-v1.md) · [Server 安装](server/boa/README.md) · [网页使用说明](server/web/README.md)

## 模块与归属

| 目录 | 职责 |
|---|---|
| `applications/clip/`、`boards/`、`tools/upload/` | Roger 固件、硬件与主机工具；可选 Boa 绑定/录音保护 |
| `server/` | DTLS 接收核心、统一依赖锁 `requirements.txt` 和进程入口 |
| `server/boa/` | 用户认证、设备绑定、固件目录、音频来源索引与业务 API |
| `server/storage/` | 每用户独立的 HTTP 分片上传、持久存储与 Range 下载 |
| `server/web/` | 登录、设备配置、固件升级和录音页面 |
| `mobile/` | Flutter App 与 BLE SDK；桌面入口为 `mobile/app/lib/desktop_main.dart` |

App 与 Clip 连接同一个 Boa Server。App 使用用户凭证，Clip 使用设备凭证；两种凭证不能互换。Server 将 App 文件写入对应用户的独立 Store，将 Clip 文件按绑定/epoch 固定归属，`/api/boa/v1/audio-files` 合并返回本人的完整文件。旧共享存储只能由开发者明确指定归属后迁移。

```text
App  ── HTTPS /api/audio ──────────┐
                                  ├─ Boa Server ─ 用户/设备归属 ─ 文件索引与下载
Clip ── DTLS v3 上传与断点续传 ────┘
```

DTLS v3、检查点格式和原始音频保持兼容。客户端配置确认、Wi-Fi/DHCP 测试、Server 整文件收件校验是不同证据，不能相互替代。转写/摘要与部分历史协议草案仍是后续能力，不因统一文件列表而自动实现。

## 本地启动

从仓库根目录执行，使用独立数据目录：

```sh
python3 -m venv .venv-boa
.venv-boa/bin/python -m pip install -r server/requirements.txt
.venv-boa/bin/python -m server.boa.manage --data-dir "$HOME/.local/share/boa-server-dev" add-user localuser --token-out "$HOME/.config/boa-user-dev.token"
.venv-boa/bin/python -m server --data-dir "$HOME/.local/share/boa-server-dev" --http-only --host 127.0.0.1 --port 9528 --web-port 9529
```

本机网页入口为 `http://127.0.0.1:9529/`，App 根地址为 `http://127.0.0.1:9528`，使用登记的用户凭证。本机 HTTP 模式没有 DTLS 接收；Clip 联调需配置受信 HTTPS/DTLS 证书，再按 [Server 安装说明](server/boa/README.md) 启动。ID-only 登录仅供显式开启的可信开发环境。

桌面调试另开终端运行 `bash scripts/run-desktop.sh`。固件另需 Nordic NCS / Zephyr 工具链；桌面或 Server 测试不能替代固件编译及实机验收。

## 固件与绑定

Roger 原生 BLE SMP OTA 保持上游行为；可选 Boa profile 仅增加完整 UID、原子绑定配置、检查后清理和不可变录音归属。用户登录并连接后，网页按完整 UID 获取该用户已分配设备的配置，在空闲时自动写入并读回，保留 Wi-Fi、录音及自动上传开关。设备忙时自动重试。

换用户前须撤销旧凭证，处理旧录音、Wi-Fi 和配对，并由开发者确认清理后再分配；旧云端文件仍归原用户。新绑定不自动接管归属未知的旧录音。详见 [绑定设计](docs/design/2026-10-28-clip-user-binding-design.md)。

本次代码整合、软件测试和固件构建的结果不等于线上部署或实体 Clip 已验收。历史 Beta 发布仅证明对应旧制品，不能证明当前分支已经安装、刷写或完成新硬件流程。
