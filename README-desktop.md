# Boa Voice macOS Beta 5

桌面版本：**1.0.1-beta.5+5**。当前源码分支为 `boa/roger-integration`；服务地址由部署配置决定。

- 本地录音、播放、导入/导出、回收站和自动上传。
- Clip BLE 连接、状态、开始/停止录音、配网、上传目标配置、时间同步、自动上传与进度。
- App/Clip 统一服务器文件列表，按时间倒序；用户之间隔离。Clip 原件可导出。

安装 DMG 后拖入 Applications，再从应用程序打开。未经过 Apple 公证；首次若被阻止，打开一次后到「系统设置 → 隐私与安全性」点击 Boa Voice 旁的「仍要打开」，由本人完成系统确认。

「服务设置」填 HTTPS 根地址、用户令牌；使用开发证书时点「导入 CA / 开发证书」，再连接并保存。凭据保存在当前用户的私有配置文件中，不使用钥匙串。设备令牌用于 Clip，不能填成 App 用户令牌。

「Clip 设备」连接并配对 → 保存 Wi-Fi → 保存 Server 主机:端口、设备 ID/设备令牌 → 检查 Wi-Fi → 同步时间 → 开启自动上传。Clip 固件需要信任对应 DTLS CA。开发机外部 UDP 传输已复测通过，Clip 真机连接仍需验收。

[Server 安装与登记](server/boa/README.md) · [功能与协议](docs/product/boa-voice-overview.md) · [Beta 5 连接修复](docs/releases/boa-desktop-v1.0.1-beta.5.md) · [Beta 4 验收](docs/releases/boa-desktop-v1.0.1-beta.4.md)

[Roger 基础与 Boa 扩展边界](docs/contracts/roger-base-extension-v1.md)

---

# Boa Voice：macOS 桌面端与音频存储服务

本分支在 reSpeaker Clip 工程中增加个人音频工作台。桌面端使用 Flutter，服务端使用 Python / FastAPI、SQLite 和磁盘文件；两者通过 HTTP 通信，可独立启动。普通音频管理不需要 Clip 硬件。

## 模块与协议设计评审

功能以当前代码和对应版本验收为准。产品规划可先看 [基于官方 App 的修改与增强清单](docs/product/official-app-customization.md)：明确自定义 endpoint、权限、存储、模型等要改什么，区分 App、服务端与固件责任。范围确定后，再评审 [模块边界与协议设计](docs/design/2026-10-21-boa-voice-module-protocol-design.md) 并写实现计划。外部接口分别见 [现有存储 HTTP v1](docs/contracts/storage-http-v1.md) 与 [Clip 设备契约](docs/contracts/clip-device-v1.md)。草案接口不表示已实现，也不授权开始重构。

服务端 AI 规划已改为官方流程：App 上传 → Server 转写/摘要 → App 获取结果。新增 [AI HTTP v1 协议草案](docs/contracts/ai-http-v1.md) 定义自定义模型 endpoint、配置/凭据、任务、结果版本及错误；尚未实现，当前功能表仍以已验收代码为准。

当前 Server 已实现 App/Clip 文件索引和用户隔离；Clip 原件可查询和下载。[历史直传设计](docs/design/2026-10-22-clip-direct-server-upload-design.md) 与 [桥接草案](docs/contracts/clip-ingest-app-server-bridge.md) 保留产品演进背景，解码标准化及 AI 流程仍需分别开发验收。

## 本地开发与交付

本地开发直接运行 `bash scripts/run-desktop.sh`，使用 Flutter 调试与热重载。当前开发分支为 `boa/roger-integration`，代码和安装包统一维护在 [BofAI/reSpeaker_Clip](https://github.com/BofAI/reSpeaker_Clip)。交付包使用 Beta 版本。

## Beta 安装包下载

历史发布版本：**1.0.1-beta.5**，GitHub Release 标记为预发布。旧附件及链接不代表本分支已有新制品或下载可用性已复核。

- [Release 与所有附件](https://github.com/BofAI/reSpeaker_Clip/releases/tag/boa-voice-v1.0.1-beta.5)
- [macOS DMG（Apple Silicon / Intel 通用）](https://github.com/BofAI/reSpeaker_Clip/releases/download/boa-voice-v1.0.1-beta.5/Boa-Voice-1.0.1-beta.5-macos-universal.dmg)
- [当前 Boa Server 源码与安装说明](server/boa/README.md)

Beta 5 包含 BLE 初始化失败清理、Apple 加密通知重试及 AT 验证改动。真实 Clip 连接尚未完成现场验收，不能确认此前“可扫描但无法连接”的问题已经解决。

双击 DMG，将 App 拖入 Applications。Server 需单独启动，配置步骤见下文。DMG 采用临时签名，未经过 Apple 公证。

## 当前功能

| 模块 | 能力 |
| --- | --- |
| 本地音频 | 导入 WAV/M4A/MP3/Ogg/FLAC/AAC，复制入库、SHA-256 去重、搜索、详情、改名、导出、回收与恢复 |
| 时间与位置 | 本地按入库时间倒序，服务器按上传创建时间倒序；显示仅本地、仅服务器、两端都有；离线显示服务器状态未确认 |
| 播放 | 本地播放、暂停、定位，已下载文件离线播放 |
| 备份 | 自动上传开关、独立手动上传、按文件重试；同步任务显示目标、进度与错误，重启恢复队列；本地原件保留 |
| HTTP 存储 | 默认最大 2 GiB/文件、5 MiB 分片、完整性校验、下载 Range 续传 |
| 服务设置 | 配置地址与访问令牌，本机保存；桌面服务配置不访问钥匙串 |
| Clip | BLE 扫描、连接、断开、记住设备、重连、电量、版本/状态查询；开始/暂停/继续/停止/标记命令 |
| 麦克风 | 选择输入、WAV 录制与电平、暂停/继续、命名保存、取消后暂存恢复；本机实际采集与暂停/继续已通过，完整验证记录见 Beta 3 文档 |

范围：macOS 构建已验证；Clip 真机完整联调尚未完成。桌面入口尚未接入 Clip 文件下载、Wi-Fi 同步、OTA、转写、摘要和模型设置。Windows/Linux 未构建验收。文件位置反映最近一次查询或上传结果，外部修改后需刷新。

## 首次打开出现“Apple 无法验证”

当前 Beta 未公证。确认来自本仓库后，在“应用程序”尝试打开 App，再到“系统设置 → 隐私与安全性”找到 Boa Voice 提示，点击“仍要打开”，按系统提示由本人确认。

自用可按这个流程打开，不需要为此立即开通付费开发者账号。后续要提供 Developer ID 签名及公证包，需要开发者账号、证书与重新验收。完整步骤见 [macOS 签名与首次打开说明](docs/macos-signing-and-notarization.md)。

## 1. 准备环境

- macOS，完整安装 Xcode 并完成首次启动；CocoaPods、Git。
- Flutter stable（本机验证版本 3.47.4），运行 `flutter doctor -v` 检查环境。
- Python 3.11+；服务端测试使用 Python 3.13。FFmpeg 仅用于生成音频验证样本，普通服务启动不需要。
- Xcode 工程最低部署目标为 macOS 12.0；最低版本系统的实际兼容性尚未实机验收。

```sh
git clone https://github.com/BofAI/reSpeaker_Clip.git
cd reSpeaker_Clip
```

后续步骤需在维护者提供的 `boa/roger-integration` 工作区执行。分支尚未推送时，新克隆需先取得对应提交或补丁；默认分支不代表包含 Boa 集成功能。

## 2. 启动 Boa Server（终端一）

从仓库根目录执行：

```sh
python3 -m venv .venv-boa
.venv-boa/bin/python -m pip install -r server/requirements.txt
.venv-boa/bin/python -m server.boa.manage --data-dir "$HOME/.local/share/boa-server" add-user localuser --token-out "$HOME/.config/boa-user.token"
.venv-boa/bin/python -m server --data-dir "$HOME/.local/share/boa-server" --http-only --host 127.0.0.1 --port 9528 --web-port 9529
```

桌面端填写 `http://127.0.0.1:9528` 和登记的用户凭证。令牌保存在私有文件中，不提交到 Git 或发送到日志。已有用户不重复登记，重启沿用原数据目录和凭证。每个数据目录仅运行一个服务进程，退出按 Ctrl+C；App 不负责启动服务。

该命令仅供本机 HTTP 开发，没有 DTLS 接收。Clip 联调与远程访问按 [Server 安装说明](server/boa/README.md) 配置证书、设备和 HTTPS/DTLS 监听。数据按用户隔离；从旧共享服务迁移时由开发者确认文件归属。

## 3. 启动桌面端（终端二）

在仓库根目录运行：

```sh
bash scripts/run-desktop.sh
```

等价命令：

```sh
cd mobile/app
flutter pub get
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer flutter run -d macos -t lib/desktop_main.dart
```

Flutter 会处理 macOS CocoaPods 集成。如 CocoaPods 报环境错误，先修复 `flutter doctor -v` 中的 Xcode/CocoaPods 项；需要时在 `mobile/app/macos` 运行 `pod install`。

打开“服务设置”，填写地址、令牌，点击“连接并保存”。导入一段音频后可在本地播放；自动备份开启时，等待状态变成“本地 + 服务器”，然后在“服务器音频”中刷新查看。

首次麦克风录音和 Clip 搜索需要相应 macOS 权限。Clip 已被手机连接时先在手机端断开。设备控制与本机麦克风录音独立。

## 4. 构建本机安装版

```sh
cd mobile/app
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer flutter build macos --release -t lib/desktop_main.dart
mkdir -p "$HOME/Applications"
ditto 'build/macos/Build/Products/Release/Boa Voice.app' "$HOME/Applications/Boa Voice.app"
open "$HOME/Applications/Boa Voice.app"
```

替换前退出运行中的 App。产物使用本机签名，未公证；公开分发需要稳定开发者签名、公证与安装验收。以上不是 App Store 发布流程。使用 `desktop_main.dart` 构建桌面交付版本，原有 `main.dart` 为手机业务入口；`audio_storage_smoke_main.dart` 仅供验证。

## 制作 DMG 安装包

仅在本地功能验收完成、准备交付时执行；日常修改用上方 Flutter 调试入口。在仓库根目录运行：

```sh
bash scripts/package-macos-dmg.sh
```

脚本先构建 `desktop_main.dart`，检查包内全部原生文件的动态库依赖及构建号，校验 App 签名，再生成 `dist/Boa-Voice-<版本>-macos-<架构>.dmg` 和 `.sha256`。文件名保留 pubspec.yaml 中的 Beta 后缀；架构根据实际主程序判断，包含 arm64 和 x86_64 时标记 universal。已有同名安装包时停止，避免意外覆盖。

如果已经完成 Release 构建，可用 `bash scripts/package-macos-dmg.sh --skip-build` 仅打包。打开 DMG，将 Boa Voice.app 拖入 Applications，复制完成后推出映像，再从应用程序启动。更新时先退出旧版；音频及配置位于 App 沙箱，不在 DMG 中。

DMG 仅包含桌面 App，Server 仍按前文单独启动。当前产物为本机临时签名，未经过 Apple 公证；其他 Mac 的首次运行限制和最低系统兼容性仍需验证。

## 5. 数据和自动上传

- 本地库：Flutter Application Support 下的 `boa_desktop/library`；沙箱安装时位于 `~/Library/Containers/com.boa.voice.desktop/Data/Library/Application Support/` 内。
- 配置：`boa_desktop/credentials/server.json`，目录 0700、文件 0600，令牌为明文。本机自用可避免钥匙串反复确认；同一用户权限的程序仍可能读取。
- 队列：`boa_desktop/backup-queue.json`，不保存令牌。默认串行上传，失败等待 30/60 秒，三次尝试后等待手动重试。
- 自动备份包含已入库、新导入和新录音；关闭开关后不启动后续任务，已开始的上传完成。App 退出后暂停，下次启动恢复。
- 本地和服务器为独立副本，下载完成经过哈希校验后入库；目前不支持多端完整元数据同步或删除联动。
- 服务端：SQLite 元数据与 `files/` 文件要一起备份；`parts/` 保存未完成上传。请勿运行时手动修改数据目录。
- Git 忽略运行数据、测试音频、凭据、虚拟环境及构建产物；不要将 App 沙箱目录复制进仓库。

## 6. 开发与测试

```sh
# 仓库根目录：服务端接口测试（先按上文安装依赖）
.venv-boa/bin/python -m pytest server/boa/tests server/storage/tests -q

# Flutter 单元测试与局部静态检查
cd mobile/app
flutter test test/desktop test/audio_storage
flutter analyze lib/desktop_main.dart lib/src/features/desktop lib/src/features/audio_storage test/desktop test/audio_storage
```

本地开发期间已验证 14 项 Flutter 桌面/存储测试、12 项服务端测试；历史原生音频验证覆盖多格式和最大约 1 GiB 文件的下载、哈希、导入、播放/暂停/定位。该证据不替代 Clip 实机与麦克风采集验收，也不代表全仓库测试通过。

| 代码位置 | 用途 |
| --- | --- |
| `mobile/app/lib/desktop_main.dart` | macOS 入口及主题 |
| `mobile/app/lib/src/features/desktop/` | 音频库、备份队列、桌面页面、Clip 控制和服务配置 |
| `mobile/app/lib/src/features/audio_storage/storage_client.dart` | HTTP 上传、下载、续传、校验 |
| `mobile/sdk/flutter/` | 官方 BLE/AT 通信 SDK |
| `mobile/app/macos/` | 桌面窗口、权限与 Xcode 工程 |
| `server/storage/` | 音频存储服务、接口测试及验证脚本 |

新增业务功能可先从桌面页面拆分独立模块，再复用 HTTP 客户端。模型转写与摘要需要另行实现配置、异步任务与结果展示，不会因音频上传而自动触发。

接口、服务端验证脚本与限制见 [服务 README](server/storage/README.md)。

原生依赖回归测试：`python3 -m unittest discover -s scripts/tests -v`。独立检查安装包中的 App：`python3 scripts/verify-macos-bundle.py /Applications/Boa\ Voice.app`。打包检查会拒绝 Homebrew 等开发机绝对路径依赖。

## 桌面 Wi-Fi 列表与配网

新版本地开发桌面端在「Clip 设备」页提供原生配网区。未连接设备时可以扫描周边 Wi-Fi、选择兼容的 2.4 GHz / WPA2 网络和填写密码；连接后读取 Clip 已保存的名称，点击「保存并测试连接」核对设备持久化及 DHCP 结果。密码仅保留在当前窗口，保存、失败、扫描、修改名称及断连重连都不清空，眼睛按钮切换显示/隐藏。关闭窗口后不持久化密码。

Mac 第一次扫描需要用户允许 Boa Voice 的定位权限。不会读取钥匙串密码、改变 Mac 网络，也不需要网页或本机 HTTP 扫描服务。网页继续提供独立的手动配网入口。该桌面配网功能仍需在对应构建上完成实体 Clip 验收；网页绑定功能及其限制见 [绑定设计](docs/design/2026-10-28-clip-user-binding-design.md)。
