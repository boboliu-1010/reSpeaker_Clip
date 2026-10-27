# Power Management

> 以下为上游 v0.1.2 基线资料；当前上传固件的差异见文末[当前上传分支补充](#当前上传分支补充)。基线功能、构建方式和性能数据不等于本分支已启用功能或实测结果。

> **This file owns the power figures.** Other docs quote these numbers;
> if a number changes, change it here first.

All measurements are on the **3V3 rail** (firmware v0.0.5 baseline).

## Summary

| Configuration | Idle current |
|---------------|--------------|
| Production snippet (console off), all gating active | **~170µA** |
| Debug build (UART console on) | ~170µA + ~570µA console leak |
| BLE slow advertising (~1s interval) | add ~0.1mA averaged |
| Main/radio regulators on LDO instead of DCDC | add ~500–600µA |

## Budget breakdown

- **DCDC conversion** — nRF5340 main and radio regulators configured as DCDC
  (`vregmain`/`vregradio` = `NRF5X_REG_MODE_DCDC`), saving ~500–600µA vs LDO.
- **UART console leak (debug builds only)** — the UARTE peripheral stays
  enabled between log outputs, leaking **~570µA** at idle (baud-independent;
  115200 and 921600 leak the same). The `production` snippet disables the
  console + UART log backend, which is what brings production to ~170µA.
- **SD card idle power-gating** — after `CLIP_SD_IDLE_DELAY_MS` (default 45s,
  `applications/clip/Kconfig`) of no SD access: unmount → disk deinit → SPI4
  runtime-PM suspend → CS pin parked low → LDO2 off. Remount is lazy on the
  next access via `storage_ensure_mounted()`.
- **nRF70 (WiFi) QSPI low power** — `CONFIG_NRF70_QSPI_LOW_POWER=y` puts QSPI
  in low power whenever WiFi is not in use.
- **BLE advertising** — slow advertising (~1s interval) adds ~0.1mA averaged to
  idle current.
- **SPI bias resistors** — `bias-pull-up` removed from `spi3`/`spi4`
  (push-pull needs none), with `bias-pull-down` on `spi4_sleep`.
- **Runtime PM** — `CONFIG_PM_DEVICE_RUNTIME=y`: UART, I2C, SPI drivers
  suspend automatically when idle and resume on access.

## The production snippet

Mechanism: `applications/clip/snippets/production/` (conf + `snippet.yml`).
It disables the UART console and UART log backend (`CONFIG_CONSOLE=n`,
`CONFIG_UART_CONSOLE=n`, `CONFIG_LOG_BACKEND_UART=n`); the FS log backend
default follows (off). Use it for battery/production builds where the console
leak matters.

```sh
# app-dir snippets are auto-discovered under NCS v3.3.0:
west build --build-dir build-clip-prod --board clip/nrf5340/cpuapp applications/clip \
  -- -DSNIPPET_ROOT=$(pwd)/applications/clip -DSNIPPET=production
# (CI additionally passes -DSNIPPET_ROOT="$(pwd)/applications/clip"; equivalent.)
```

The default (no-snippet) build is the **debug** image: UART console on, FS log
to `/SD:/LOG` at INF level.

## Regulator map

PMIC (NPM1300, I2C1 @ 0x6b) regulators:

| Rail | Consumer | Notes |
|------|----------|-------|
| BUCK1 | Haptic motor | |
| BUCK2 | Main 3.3V | |
| LDO1 | Mic 1.8V | |
| LDO2 | SD card 3.3V | Turned off by SD idle power-gating |

GPIO-controlled regulators:

| GPIO | Rail | Consumer |
|------|------|----------|
| gpio1.14 | mic_vdd | PDM microphones |
| gpio1.8 | oled_vdd | CH1115 OLED |
| gpio0.29 | rfsw_vdd | RF switch |
| gpio0.27 | flash_vdd | External SPI flash (PY25Q64H) |

## How to measure

Measure on the 3V3 rail (series ammeter / power analyzer on BUCK2 output or
the 3V3 net). Ensure the device has been idle for >45s so SD power-gating has
engaged, WiFi is off, and (for the ~170µA figure) the production snippet build
is flashed. Compare against the summary table above.


---

## 当前上传分支补充

本页区分固件的供电／采样逻辑与实际整机耗电。当前尚无经过电池供电路径校准的
Station 上传能耗结论，不能用显示电量不变推断上传不耗电。

## 当前省电策略

- 自动上传一批文件时复用一条 DTLS 连接；任务完成、失败或取消后关闭连接和 Wi-Fi。
- 上传期间申请现有 128 MHz CPU 提频，结束后释放；恢复到当时其余任务所需的频率。
- SD 沿用空闲电源管理；频繁轮询目录或日志可能延后 SD 休眠。
- production 关闭 UART 控制台和 UART 日志，SD 日志默认关闭；USB CDC 业务接口仍可用。
- 充电时才上传、低电量暂停上传尚未实现。自动上传开关与这些策略是不同功能。

## Station 上传的电量采样


The upload job is active even while scanning SD or preparing a file, before the
Station interface is up. It must use measured PMIC current rather than the
400 uA idle budget. An up Station interface also counts as active when no job
runs. Existing AP idle/phone-transfer compensation remains separate.

## Inputs and limits

PMIC current is normalized to positive discharge and negative charging. The
configured unseen Wi-Fi current is added once. The existing 59/99 mA AP defaults
originated in upstream commit `48f7cd3116534c7292b88875bb43d2b74d601e45`, whose
message describes conservative upper-bound defaults requiring calibration;
these are not Station measurements. The board-level measurement blind spot is
documented by that upstream change; it has not been independently verified here
against the schematic or a battery-rail measurement.

Station-specific `CLIP_BATTERY_WIFI_STA_IDLE_LOAD_MA` and
`CLIP_BATTERY_WIFI_STA_ACTIVE_LOAD_MA` now default to **50 mA** and **78 mA**
respectively. These are initial **uncalibrated estimates**, not Station
measurements or a fixed AP-to-Station conversion ratio.

The [nRF7002 electrical specification](https://docs.nordicsemi.com/r/bundle/ps_nrf7002/page/chapters/elspec/doc/electrical_specification.html)
lists a typical 2.4 GHz receive/listen current of 49.6 mA and, for the QFN package
at MCS7 and maximum output power, a typical transmit current of 191 mA. The
reference supply is 3.6 V at 25 C. The initial model assumes:

- Station interface up, no upload/check job: awake receive/listen reference,
  `round(49.6) = 50 mA`.
- Station interface up during an upload/check job: assumed 20% transmit and
  80% receive/listen, `round(0.2 * 191 + 0.8 * 49.6) = 78 mA`.
- Interface down, including file preparation before radio startup: no Wi-Fi
  compensation. Existing idle/PMIC accounting still applies.

The 78 mA active estimate replaces 50 mA; they are never added together.
Existing PMIC current is added separately with its charge/discharge sign.
The active value applies throughout association, DHCP, TLS, DATA and
between-file waits while the interface is up; it is not live packet accounting.
The 20/80 split, output power and time spent asleep have not been measured.
The current firmware retains Station power-saving support, so this awake-radio
model may overestimate consumption when the radio sleeps. Board supply-voltage
differences and the actual unmeasured supply branch still need calibration.

Setting either parameter to zero explicitly leaves that state's compensation
unknown, not physically zero. AP defaults remain separate. `wifi_unmodeled:false`
only means an estimate is present (or the radio is off); `energy_calibrated`
remains false. A physically calibrated whole-battery energy result remains
outside what these software changes alone can establish.

Polls are queued on upload/check BEGIN and END, and run every five seconds while
a Station job/interface is active (otherwise the existing sixty seconds).
The preceding interval uses its starting current sample. This avoids applying
the first upload current to a previous minute of idle or applying the new idle
current to the end of an upload. Current between samples and transition-worker
latency remain approximations. Charge state changes are sampled via the existing
PMIC notifications. Flash checkpointing stays on displayed-percent change or
ten elapsed minutes; five-second polling does not turn it into a fifty-second
save interval. No new thread is added.

## Default-build diagnostic API

`AT+BATTDIAG` / `AT+BATTDIAG?` works over USB and encrypted BLE, including during
uploads. It is read-only, returns the last completed sample under the battery
mutex, and never forces an ADC reading or gauge update. It is registered only
with `CLIP_DEBUG_INTERFACES`; the baseline production configuration excludes it.
Existing `AT+BATT` and `AT+GSTAT` responses are unchanged.

The JSON `data` contains:

| Field | Meaning |
|---|---|
| `valid`, `gauge_ready` | Sample exists; fuel-gauge library initialized. If not initialized, raw SoC is the voltage fallback. |
| `age_ms`, `interval_ms` | Snapshot age and preceding integration interval, in milliseconds. |
| `vbus`, `vbus_valid`, `vbus_status_raw` | USB power PRESENT attribute, latest status-read validity and cached raw PMIC bitfield. Only use `vbus` when `vbus_valid` is true. The raw bitfield includes flags unrelated to presence, and must not be tested as a boolean; `charging:false` also does not prove battery-only power. |
| `active`, `station_job`, `station_radio` | Selected load mode, job activity and up Station interface. |
| `wifi_unmodeled` | Radio is on but no compensation is configured (or compensation is disabled). |
| `pmic_discharge_ua` | Measured PMIC-path current, positive discharge / negative charging. Not a whole-board meter. |
| `wifi_comp_ua` | Configured extra radio current; 0 with `wifi_unmodeled:true` means missing estimate. |
| `model_current_ua` | Current chosen for the interval beginning at this sample. |
| `interval_current_ua` | Current actually passed to the gauge for the preceding interval. |
| `raw_soc_milli_percent` | Gauge SoC before display hold/rate limiting, in 0.001 percentage points. |
| `display_percent` | Existing integer display value; may be held/smoothed. |
| `model_net_uas` | Since-boot signed integral of current fed to the gauge, in microamp-seconds. Positive means net discharge. Not calibrated mAh. |
| `unmodeled_wifi_ms` | Since-boot modeled intervals with missing Wi-Fi compensation. |
| `energy_calibrated` | Always false: the interface does not certify hardware calibration. |

Counters are volatile, not written to SD or settings. Sample age arithmetic uses
the low 32-bit uptime clock. The integral is a sampled gauge input, not a hardware
coulomb counter, and must not be labeled measured battery consumption. In
particular, unchanged integer percentage does not prove zero consumption.

For upload tests, capture diagnostic baselines with VBUS false, retain the full
sample sequence and take end/rest samples without reconnecting USB. Compare raw
SoC, model input and display separately. Do not classify an upload as a successful
energy measurement until the missing current and calibration limits are resolved.

The target formatter cannot render the 64-bit printf conversions used by the first diagnostic candidate. Counters are explicitly converted to decimal digits, still emitted as JSON numbers, without changing libc configuration. Host tests enforce this target limitation and signed/unsigned 64-bit bounds.

## 电源轨参考



PMIC (NPM1300, I2C1 @ 0x6b) regulators:

| Rail | Consumer | Notes |
|------|----------|-------|
| BUCK1 | Haptic motor | |
| BUCK2 | Main 3.3V | |
| LDO1 | Mic 1.8V | |
| LDO2 | SD card 3.3V | Turned off by SD idle power-gating |

GPIO-controlled regulators:

| GPIO | Rail | Consumer |
|------|------|----------|
| gpio1.14 | mic_vdd | PDM microphones |
| gpio1.8 | oled_vdd | CH1115 OLED |
| gpio0.29 | rfsw_vdd | RF switch |
| gpio0.27 | flash_vdd | External SPI flash (PY25Q64H) |


## 如何得到准确的上传耗电量

电池供电、无 USB 充电条件下，在电池路径测量整机电流及电压，对同一批文件积分，
并保留联网、握手、DATA 和收尾的时间边界。再与 PMIC 路径读数、模型积分和显示
电量分别对比，估计或校准 PMIC 未覆盖的 Station Wi-Fi 电流。

仅测 3V3 某一支路不等于测到了整机电池消耗；短时电压下降也不能直接换算为 mAh。
当前默认补偿为“未知”，没有可承诺的整机耗电误差范围。默认版诊断及完整计算限制
见上文；production 不开放 `BATTDIAG`。
