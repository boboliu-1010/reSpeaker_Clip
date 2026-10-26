# Troubleshooting

> 以下为上游 v0.1.2 基线资料；当前上传固件的差异见文末[当前上传分支补充](#当前上传分支补充)。基线功能、构建方式和性能数据不等于本分支已启用功能或实测结果。

Symptoms → cause → fix, grouped by area. Each entry is deliberately short.

## Build

| Symptom | Cause | Fix |
|---------|-------|-----|
| App/module Kconfig not found, board files missing | `ZEPHYR_EXTRA_MODULES` not set, or set as a CMake variable | `export ZEPHYR_EXTRA_MODULES=$(pwd)` — must be an **environment variable**; Kconfig module discovery happens before CMake configuration |
| Mysterious Kconfig errors (e.g. WPA3 `..._WPA3_IMPLEMENTATION_NONE` missing) | Building against NCS v3.2.1 | `main` requires **NCS v3.3.0** (`source ~/ncs/v3.3.0/zephyr/zephyr-env.sh`); v3.2.1 is unsupported |
| `snippet not found` / snippet ignored | Under sysbuild the app dir is not on the snippet search path (or `SNIPPET_ROOT` was passed relative) | Use `-- -DSNIPPET_ROOT=$(pwd)/applications/clip -DSNIPPET=production` — `SNIPPET_ROOT` must be an absolute path |
| MCUboot changes don't appear in the image | Incremental build | MCUboot changes require a **pristine** build (`--pristine`) |
| Compiler warnings block commit | Repo rule | Fix all warnings before committing; zero-warning policy |

## Console / serial

| Symptom | Cause | Fix |
|---------|-------|-----|
| Can't find the device console; `/dev/ttyACM0` shows J-Link traces | J-Link probe takes `ttyACM0` when attached | Clip's UART0 bridge moves to `/dev/ttyACM1` — use whichever port is the "USB Single Serial" / non-J-Link one. Identify the Clip port by USB PID `2886:0x0069` (`lsusb`) |
| `west flash --reset` doesn't reset the board | Board quirk | Run `nrfutil device reset` after `west flash` |
| No output at all | Wrong baud or console compiled out | Debug builds: 921600 baud. Production snippet builds have **no console** by design |

## Runtime

| Symptom | Cause | Fix |
|---------|-------|-----|
| Log prints `"lu"` literally for 64-bit values | Zephyr minimal printf has no `%llu` | Use `%u` with `(unsigned int)` cast for 64-bit values |
| Python tool won't exit on Ctrl+C | `except Exception` doesn't catch `KeyboardInterrupt` (it's a `BaseException`) | Use bare `except:` or handle `KeyboardInterrupt` explicitly |
| UDP transfer shows CRC/data mismatches, lost chunks | `sendto()` returns success even when the WiFi TX queue silently drops packets | Don't trust single-send success; CRC is only updated after confirmed send, file-level retry recovers losses |
| Transfer can't be cancelled or races with AT commands | AT commands and transfer run on different threads | Coordinate via `volatile` flags (e.g. `transfer_cancel_requested`) checked in the transfer loop |

## Storage

| Symptom | Cause | Fix |
|---------|-------|-----|
| Session list in wrong order after new recordings | FAT directory order is not chronological | Listing uses a cached sorted buffer invalidated on mutations — ensure every mutation invalidates it |
| Need post-mortem logs after a crash/field issue | Logs persist to SD (`CONFIG_LOG_BACKEND_FS=y`, rotating 64KiB files) | Read `/SD:/LOG/` off the card. Note `CONFIG_LOG_DEFAULT_LEVEL=0` compiles logs out — enable `LOG_RUNTIME_FILTERING` / per-module level when debugging |
| SD card dead after 45s idle | Not a fault — idle power-gating (unmount → LDO2 off) | Any access lazily remounts via `storage_ensure_mounted()` |

## Recovery / boot

| Symptom | Cause | Fix |
|---------|-------|-----|
| Boot hangs ~40s, loops (often after repeated BLE pair/unpair) | Corrupt `/lfs/settings/run` blocks `settings_load` | Normally auto-recovered by the watchdog on the system workqueue (wipes the file + reboots if load exceeds `CLIP_SETTINGS_LOAD_TIMEOUT_MS`=3s). Manual recovery: MCUboot custom mcumgr "erase settings" command (erase LFS 128KB). Reflashing the app does **not** clear it — settings live in external flash |
| App-only update via raw J-Link of `zephyr.signed.hex` to slot 0 doesn't boot | Image must be installed through MCUboot | Use USB serial DFU or BLE OTA (see `docs/usb_dfu.md`) |


---

## 当前上传分支补充

| 现象 | 先确认什么 | 说明 |
|---|---|---|
| 配网保存成功，但没有上传 | `UPLOADAUTO?`、配置完整性、设备忙闲及待传文件 | `saved:true`只表示已保存，不表示已联网或服务器可达 |
| `NETCHECK`成功，但上传失败 | 校时、DNS、DTLS、服务器UDP端口与认证 | NETCHECK只测Wi-Fi关联和DHCP；见[协议](protocol.md#ble-network-validation-and-automatic-upload-control) |
| 偶发联网／握手很慢 | ready、关联、DHCP、ARP和DTLS分别计时 | UDP没有TCP建连，但DHCP／ARP和DTLS重传仍存在；见[网络诊断](network.md) |
| UDP 9527收不到 | 监听、主机防火墙和上层网络的UDP放行 | TCP 9527可用不能证明UDP已放行 |
| 上传中按录音，暂时未录 | `record_pending`、`record_error`和实际`recording` | pending表示已排队，需完成资源清理后启动 |
| 文件又上传了一次 | 目标指纹、长度、状态CRC及服务器偏移 | 换目标或本地状态无效可重新发现；以服务器检查点续传 |
| production上传后设备列表为空 | `delete_after_upload`、`session_deleted` | 整段全部确认后默认删除；默认诊断版保留 |
| 电量显示不下降 | VBUS／充电状态、原始SoC、显示平滑和Wi-Fi未校准电流 | 不等于没有耗电；见[功耗](power.md) |
| 拔USB后没有串口 | CDC自动关闭、物理数据线和USB开关 | 可通过BLE开启USB，必要时接回后再次开启；不是直接证明设备重启 |
| 切换默认版／production后蓝牙配对报错 | 两端绑定是否匹配 | SDK绑定配置标志不同，可能需移除主机旧绑定并重新配对；不要直接擦除设备设置或录音 |
| SD空闲后关闭 | SD空闲电源管理 | 下次访问按原有流程重新挂载；持续扫描／日志会影响休眠 |
| 64位计数JSON输出`ld/lu` | 目标格式化库的64位支持 | 当前BATTDIAG显式转换十进制；不要用截断为32位掩盖溢出 |
| 镜像无法启动／验签失败 | 设备Bootloader信任的密钥、镜像类型及布局 | 进入[USB恢复](usb_dfu.md)，使用匹配回退包；不把问题直接归因于网络 |

默认版按已启用的编译开关提供资源、网络和性能诊断；production不保证存在调试命令。
抓包、设备状态和服务器日志需对齐时间边界，保留失败样本；不要为复现直接清空用户录音。
