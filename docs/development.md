# reSpeaker Clip - Development Log

> 以下为上游 v0.1.2 基线资料；当前上传固件的差异见文末[当前上传分支补充](#当前上传分支补充)。基线功能、构建方式和性能数据不等于本分支已启用功能或实测结果。

## Current State (2026-05-18)

### Implemented Features

| Feature | Notes |
|---------|-------|
| PDM Microphone Capture | 16kHz, stereo/mono/merge modes |
| Opus Encoding | Mode-specific bitrate/complexity via Kconfig |
| SpeexDSP Processing | Noise suppression, dereverberation (SpeexDSP AGC unavailable in FIXED_POINT; custom integer AGC + high-pass in Enhanced/MERGE mode) |
| Audio Modes | Normal (stereo, 32kbps/ch = 64kbps total, complexity 1), Enhanced (mono, 32kbps, complexity 1) |
| SD Card Storage | FAT32, timestamp buckets under `/SD:/REC/YYYYMMDD/HH/MM/SS/` with 100-file group directories |
| SD Card Log Persistence | LOG_BACKEND_FS, /SD:/LOG/, 128KB files x20; AT+LOG=off\|info\|debug (debug default INF) |
| Session Metadata | session.json and marks.bin per timestamp-bucket session |
| Bookmark System | Binary marks.bin with notes |
| BLE GATT Service | Command, Response, File Data, Event characteristics |
| BLE Event Notifications | State changes, marks, BLE/WiFi/USB events via notify |
| AT Command Protocol | 30 commands |
| File Transfer (BLE) | Pause/resume/cancel, session-level resume |
| File Transfer (UDP) | Fire-and-forget with per-file CRC32, file-level retransmit |
| Transport Abstraction | BLE + UDP + USB CDC channels via transport.h (active selection UDP > BLE) |
| WiFi AP Mode | SSID: ClipAP_XXXX, default password 12345678 (random 8-char password regenerated on first pairing), IP: 192.168.4.1, Port: 8089 |
| WiFi Auto-Off | 3 min timeout (CONFIG_CLIP_WIFI_TIMEOUT_MS=180000) |
| USB CDC Security | Disabled by default, AT+USB control, auto-off on disconnect |
| NVS Configuration | 5 settings persist: mode, noise, autodel, dereverb, brightness |
| Battery Monitoring | NPM1300 PMIC + nRF Fuel Gauge (directionally rate-limited, persisted SoC display) |
| Button Handler | Custom input driver: long-press record, short-press bookmark, single-click status |
| OLED Display | CH1115 driver (88x48, I2C), 24x24 icons, 8x16 font, status bar, recording time, battery/charging, low battery fullscreen |
| Haptic Motor | PMIC GPIO2 control (optional, Kconfig) |
| CPU Boost | 128MHz/64MHz reference-counted system |
| Event System | k_msgq + k_sem driven main loop |
| Factory Reset | Config reset + SD card format + reboot |
| Power Off | PMIC ship mode via AT+POWEROFF |
| Time Sync | Unix timestamp via AT+TIME, persisted to NVS |
| Firmware Update (DFU) | MCUmgr SMP OTA DFU via BLE, dual-image, OTA progress display |
| WiFi Client Detection | WiFi AP client connected icon in status bar |
| Session Sorting | AT+LIST sessions sorted newest-first via shared cache |
| Transfer Cancel | Thread-safe cancel via volatile flag (no race with transfer thread) |
| Device Naming | AT+NAME for custom BLE device name |

### AT Commands (30)

| Command | Type | Purpose |
|---------|------|---------|
| AT+GSTAT | EXEC | Get device status |
| AT+BATT | QUERY/EXEC | Get battery status (%, charging, voltage, temp) |
| AT+STORAGE | QUERY/EXEC | SD card storage info |
| AT+DEVICE | EXEC/GET | Device name |
| AT+VERSION | EXEC | Version info |
| AT+TIME | GET/SET | System time (Unix timestamp) |
| AT+START | EXEC/SET | Start recording |
| AT+STOP | EXEC | Stop recording |
| AT+MARK | EXEC/SET | Add bookmark |
| AT+PAUSE | EXEC | Pause recording |
| AT+RESUME | EXEC | Resume recording |
| AT+CANCEL | EXEC | Cancel transfer |
| AT+LIST | GET/SET | List sessions/files |
| AT+DELETE | SET | Delete session |
| AT+MARKS | GET/SET | Get bookmarks |
| AT+DOWNLOAD | SET | Download file/session |
| AT+AUTODEL | GET/SET | Auto-delete policy |
| AT+FORMAT | EXEC | Format SD card |
| AT+POWEROFF | EXEC | Power off (ship mode) |
| AT+WIFI | EXEC/GET/SET | WiFi AP control |
| AT+WIFICFG | SET/GET | WiFi AP channel + regulatory domain |
| AT+MODE | GET/SET | Recording mode |
| AT+BRIGHTNESS | GET/SET | OLED brightness |
| AT+PAIR | GET/SET | BLE pairing |
| AT+FACTORY | SET | Factory reset |
| AT+REBOOT | EXEC | Reboot |
| AT+USB | GET/SET | USB CDC control (default: off, auto-off on disconnect) |
| AT+DFU | EXEC | Reboot into MCUboot recovery mode |
| AT+LOG | SET | SD log backend level: off \| info \| debug (debug default info) |
| AT+NAME | GET/SET | Custom BLE device name |

### Thread Architecture

| Thread | Priority | Stack | Purpose |
|--------|----------|-------|---------|
| Main | 0 | Default | Event loop, status updates |
| Audio | 0 | 32768 | PDM capture, DSP, Opus encode |
| Transfer | 5 | 4096 | File transfer over BLE/UDP |
| UDP Server | 5 | 2048 | WiFi UDP packet handling |
| AT Server | 7 | 8192 | AT command parsing and dispatch |

### Memory Usage

- FLASH: ~915 KB (app core, secure + non-secure image)
- RAM: ~445 KB (total system SRAM, secure + non-secure + shared)

### Recording Modes

| Mode | Audio | Bitrate | Complexity | DSP | Segment Duration |
|------|-------|---------|------------|-----|-----------------|
| Normal | Stereo (L+R) | 32kbps/ch (64kbps total) | 1 | Disabled | 60s (sync) / 300s (no sync) |
| Enhanced | Mono (L+R merged) | 32kbps | 1 | Enabled | 60s (sync) / 300s (no sync) |

### Build & Flash

```sh
# Environment
source ~/ncs/v3.3.0/zephyr/zephyr-env.sh
export ZEPHYR_EXTRA_MODULES=$(pwd)

# Build
west build --build-dir build-clip --board clip/nrf5340/cpuapp applications/clip

# Flash and reset
west flash --build-dir build-clip && nrfutil device reset

# Serial output
minicom -D /dev/ttyACM0 -b 921600
```

### Not Yet Implemented

| Feature | Priority | Notes |
|---------|----------|-------|
| Low Power Mode | Medium | Sleep when idle |
| Auto-Purge Execution | Medium | Background task to delete old transferred sessions |

---

## Change History

### 2026-06-16 - v0.0.5 Release

- **Idle power: ~1.5mA → ~170µA (production)** via four changes, each measured on the 3V3 rail:
  - nRF5340 internal regulators switched to DCDC (`vregmain`/`vregradio` = `NRF5X_REG_MODE_DCDC`); ~500–600µA
  - SD card idle power-gating: after 45s of no record/transfer/AT/USB activity, unmount → disk deinit → SPI4 runtime-PM suspend → park CS low → LDO2 off; lazy remount on next access via `storage_ensure_mounted()`
  - SPI bias-pull-up removed from `spi3`/`spi4` (push-pull needs no pull-up) and `bias-pull-down` added to `spi4_sleep`; ~750µA
  - UART console keeps UARTE active at idle (~570µA, baud-independent); the `production` snippet disables console + UART log backend
- **Debug / production firmware split** via the `production` snippet: debug keeps UART console + SD log at INF; production strips both for low power. Both exported to `output/0.0.5/`
- **FS log backend (`/SD:/LOG`) now AT-controlled**: new `AT+LOG=off|info|debug` toggles it at runtime; boot default coupled to `LOG_BACKEND_UART` (debug on / production off) so the app-only Kconfig symbol is never broadcast into the mcuboot sysbuild image
- **Storage-full handling**: percentage-based (`CLIP_STORAGE_FULL_PERCENT`, default 95%) via `fs_statvfs`; recording refused with a "Storage Full" on-screen error and BLE event when SD is full
- **AT+NAME**: capacity 32B → 256B; surrounding quotes stripped from the argument
- **BLE reliability**: fixed slow-advertising interval (was a copy-paste of the fast interval); un-bonded devices also drop to slow advertising; connection params tightened (interval 15–30, supervision timeout 800); CCC handlers use a notify mask (`&`) instead of equality
- **Transfer cancel**: thread-safe, marks the transfer ERROR synchronously so re-download works after a BLE drop
- **Battery**: reserve capacity + early low-battery shutdown; SoC smoothing bypassed below reserve so a true low reading is acted on immediately
- **Python client (`tests/clip`)**: retries AT commands on BLE-notify drops; robust JSON parse around brace-matched notifications
- New storage API: `storage_idle_poweroff()` / `storage_resume()` / `storage_ensure_mounted()` / `storage_is_full()` / `storage_set_busy_cb()`

### 2026-05-18 - v0.0.1 Release

- Version reset to 0.0.1 for initial release
- SD card log persistence: LOG_BACKEND_FS writes WRN+ERR logs to /SD:/LOG/, 64KB files x10 max, circular overwrite
- USB CDC security: disabled by default, controlled via AT+USB command, auto-disables on USB disconnect
- BLE event notifications: state changes (recording/idle/paused), bookmark marks, BLE/WiFi/USB status events sent as JSON via GATT notify
- WiFi auto-off: 3 minute timeout (CONFIG_CLIP_WIFI_TIMEOUT_MS=180000), timer resets on client disconnect
- BLE security: LE Secure Connections pairing, encrypted link required
- Partition resize: mcuboot 96KB -> 84KB, app core slot0 940KB (268KB secure + 192KB non-secure + 256KB OTA slot + 192KB OTA non-secure)
- AT+NAME command: custom BLE device name, stored in NVS
- AT+USB command: enable/disable USB CDC, query status
- Memory: app core ~915KB FLASH, ~445KB RAM

### 2026-04-17 - UI Overhaul and Bug Fixes (v2.0.5)

- UI overhaul: 24x24 icons, 8x16 font, battery fix, charging display
- Low battery (<10%) full-screen display
- Disable idle BT/WiFi icons, add OTA icon, instant transfer display refresh
- Fuel gauge: nRF Fuel Gauge integration, SoC smoothing, charging status
- OTA progress display
- WiFi client connected icon
- Fix FILE_ACK NACK: skip CRC update on UDP send failure
- Fix AT+CANCEL race: cancel handled in transfer thread via volatile flag
- Fix AT+LIST sorting: sessions sorted newest-first with shared cache
- Fix DOWNLOAD response: add bytes field (use %u not %llu)
- Fix Ctrl+C in Python tools: gracefully merge downloaded files on interrupt
- Fix unexpected disconnect: merge files on disconnect/timeout
- Transfer file retry limit increased from 5 to 10

### 2026-03-28 - Documentation and Code Cleanup

### 2026-03-28 - Documentation and Code Cleanup

- Removed AT+BITRATE, AT+COMPLEXITY, AT+AGC, AT+CHUNKSIZE, AT+PROGRESS commands
- Bitrate and complexity are now mode-specific via Kconfig (not runtime configurable)
- AGC removed entirely (SpeexDSP FIXED_POINT build limitation)
- Transfer chunk size is compile-time only (CONFIG_CLIP_TRANSFER_CHUNK_SIZE)
- Unified all config defaults to Kconfig (removed hardcoded macros from config.h)
- Added DSP timing to encode log (avg/min/max for both Opus and DSP)
- Updated all documentation to match current codebase

### 2026-03-27 - WiFi/BLE Coexistence and Transport Refactoring

- Added WiFi/BLE coexistence configuration (nrf_wifi_coex_config_pta/non_pta)
- Added WiFi/BLE coex hardware reset on WiFi stop
- Fixed compiler warnings: net_if_ipv4_addr_add return type, deprecated net_if_ipv4_set_netmask
- Refactored transport layer: transport.h abstraction with BLE + UDP backends
- Rewrote UDP protocol: fire-and-forget with per-file CRC32 (replaced sliding window)
- Fixed button status bar in WIFI_SYNC state
- Added CPU boost system (128MHz/64MHz reference-counted)
- Event-driven main loop (k_msgq + k_sem)

### 2026-03-23 - Audio Recording Optimization

- On-demand encoder/DSP initialization
- Microphone power control (on/off with stabilization delay)
- Removed VBR settings (21ms → ~12ms encode time)
- Increased audio thread stack to 32KB and priority to 0
- Fixed AT command JSON format and buffer check
- Increased AT server thread stack from 2KB to 4KB (stack overflow fix)
- Set HFCLK divider to 1 for maximum CPU frequency (128MHz)

### 2026-02-26 - Mode Mapping Fix and DSP Restriction

- Fixed mode mapping: Normal=stereo (no DSP), Enhanced=mono (with DSP)
- DSP only enabled in enhanced mode
- Bitrate scaling: mono=1x, stereo=2x

### 2026-02-25 - Simultaneous Recording and BLE Transfer

- Added transfer_resume_from() for file-level resume
- Simultaneous recording and BLE transfer
- Disconnect callback cleanup
- Extended AT+DOWNLOAD with session/start_file syntax
- Python sync tool with auto-detection and resume support

### 2026-02-24 - Session Storage Structure

- Session directories: /SD:/REC/YYYYMMDDHHMMSS/
- session.json, files.lst, marks.bin per session
- AT+TIME command for time synchronization
- Fallback session IDs when time not synced

### 2026-02-20 - Initial Implementation

- BLE GATT service with 3 characteristics
- AT command parser (EXEC/SET/GET)
- State machine (IDLE/RECORDING/TRANSMITTING/PAUSED/ERROR)
- NVS configuration storage
- Opus encoding integration
- SpeexDSP noise suppression and dereverberation
- SD card FAT32 storage
- Audio recording thread
- Custom button input driver


---

## 当前上传分支补充

维护仓库为 [BofAI/reSpeaker_Clip](https://github.com/BofAI/reSpeaker_Clip)。当前上传源码
在 `feature/dtls-upload-core-0.1.2`；源码结构和构建入口见 [architecture.md](architecture.md)
及 [tools/upload/](../tools/upload/README.md)。

## 分支与提交

采用 `feature/* → develop → release/vX.Y.Z → main` 的维护方向。功能在 feature 验证后
再合入 develop；发布准备阶段按需建立 release 分支，验收后进入 main。
`release/*` 不是每次开发都必须创建。main、develop 以 `845713be` 为 v0.1.2 基线；
这里不将它们的远端状态当作实时查询结果。本文最新构建资源对应 `06a3284` 的固件源码，
不能把功能分支内容当成 main 已包含的功能；操作前核对实际分支和远端提交。
远端另有 `boa/*` 专项分支；本说明不把它们纳入当前上传功能维护链路，也不更改它们。

改动在本地维护，检查并保留已有修改；不向上游 Seeed 仓库误推。提交前核对实际差异和
验证范围，推送明确指定 `bofai` 和目标分支。构建镜像、私钥、设备令牌、Wi-Fi 凭据及
录音不入源码库。临时展示 HTML 和测试数据留本地。

## 开发与构建流程

使用 Mac 本地开发 → Ubuntu 编译 → Mac 设备测试。编译服务器只承担源码同步和构建，
不维护另一条未核对的源码线。首次或改变规则时先 dry-run，再 rsync；默认不 `--delete`。
源码改名／删除时检查远端残留，必要时使用独立源码与构建目录。

从仓库根目录执行，路径按实际环境填写：

```sh
python3 tools/upload/build.py \
  --ncs /path/to/ncs --sdk /path/to/zephyr-sdk \
  --build /path/to/ncs/build-clip-upload-default \
  --ca /path/to/public-ca.pem --preset dtls-single
```

追加 `--production` 选择 production。两种模式的数据通路性能参数一致；默认版提供
UART／资源／网络／性能诊断，production 关闭这些调试入口并默认整段上传后删除。
`CLIP_UPLOAD` 为上传总开关，CA 构建变量为 `CLIP_UPLOAD_CA_FILE`；没有 HTTPS 构建回退。
底层 TLS 库仍服务 DTLS 的加密和证书校验。

构建记录保存 Git 提交、未提交差异和新增源码快照、实际工具链／依赖版本、最终配置、
日志、分区、签名镜像、ELF/map及资源报告。产物本地按版本目录维护以便回退与对比；
尚未实机验证的临时构建与测试记录放 `.analysis/`，不冒充已验收发布版本。

## 验证入口

```sh
CLIP_TEST_SDK=/path/to/pinned-sdk-fixture \
  python3 -m unittest discover -s tools/upload/tests -v
python3 -m unittest discover -s tools/upload/tests -p 'test_dtls_receiver.py' -v
```

主机 C 用例需要 Clang，SDK回移用例需要固定源码fixture。真实DTLS网络用例还需支持
DTLS API 的pyOpenSSL。跳过的网络用例应在具备依赖的隔离环境补测；不干扰运行接收服务。

清理提交 `112ad51` 的验证范围：110项主机用例执行完成（3项真实DTLS本机跳过），
接收服务器隔离环境23项DTLS／存储测试通过；默认版及production编译、签名、ZIP及
分区检查通过。这些用例存在重叠，不能简单相加当作独立测试数量，也不等于实机验收。

## 当前资源基准

以下为最新已记录、固件源码匹配 `06a3284` 的完整录音应用构建，非裁剪上传实验版。
镜像在提交前构建，当时的未提交源码快照与差异已保留；提交后的固件源码一致，
不把它描述为直接从干净提交构建的镜像。对应本地产物目录为
`71-v0.1.2-station-current-estimate-default` 和 `72-v0.1.2-station-current-estimate-production`。

| 构建 | 应用 Flash | 静态 RAM | 应用 RAM 区域剩余 |
|---|---:|---:|---:|
| 默认版 | 852,220 B | 448,542 B | 2,018 B |
| production | 809,204 B | 444,974 B | 5,586 B |

应用 Flash 区域933,376 B，RAM区域450,560 B。静态RAM包括堆和线程栈预留，不能再把
运行时堆分配叠加计算；“区域剩余”也不是堆中可用空间。要判断上传峰值，需采样实际
堆、线程栈和独立网络池。清理旧的未编入HTTPS源码没有释放大块运行时RAM。

## 实机与发布

编译与刷机分开；升级方式见 [usb_dfu.md](usb_dfu.md)。保留当前回退镜像和匹配的
外置Wi-Fi补丁布局，确认签名和分区后再测试。

最新记录的验收范围如下；各项对应其实际镜像，不因后续编译成功而自动扩展：

| 版本／场景 | 已验证 | 尚不能据此确认 |
|---|---|---|
| 最新默认版（`06a3284` 固件源码） | 已刷机；纯电池供电、BLE 采样下，一条 DTLS 连接从零上传 13 个文件，共 13,964,311 B；长度及 SHA-256 全部一致；Station 补偿生效，Wi-Fi 关闭后归零 | BLE OTA 完整升级、长期稳定性、准确上传能耗 |
| 最新 production | 编译、签名、ZIP、分区及配置检查通过 | 此镜像尚未刷机，不能继承默认版的实机验收 |
| 前一清理默认版的切网对照 | 不重启设备完成原网络与手机热点切换并上传；返回原网络的 13 文件 DATA 加权速率约 317.74 KiB/s | 旧租约失效的全部恢复路径、ARP 偶发延迟根因 |

最新默认版电池供电样本的 DATA 加权速率为 281.26 KiB/s，累计 DATA 阶段
48.486秒；服务器首个 OPEN 至最后 COMPLETE 为58.693秒，触发至清理完成的
观测耗时为81.230秒。后者包含观测轮询延迟，不能与服务器计时混用。
电量输入模型累计约1.594 mAh，属于未校准估算，不是真实电池耗电测量。
完整记录保留在本地版本目录，不提交录音、镜像、私有配置或服务器实际地址。

按改动选择持续上传、同一连接批量上传、录音抢占续传、断网、服务重启、硬复位及
真实掉电测试。每次记录文件数／大小／SHA-256、配置、网络、时间边界、失败及重传。
DATA速率和整任务速率分别统计，不把本机局域网结果与公网结果直接混为一个指标。
耗电结论需满足 [power.md](power.md) 的测量与校准条件。
