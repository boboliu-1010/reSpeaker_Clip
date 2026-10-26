# 功耗策略与电量估算

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
`CLIP_BATTERY_WIFI_STA_ACTIVE_LOAD_MA` default to **0 (unknown)**. Zero is not a
physical zero-current claim. PMIC current still feeds the gauge during uploads,
but the radio load remains incomplete until a Station-specific estimate is
provided. A nonzero setting is still an estimate, not automatic calibration.
The active value applies to an up interface during association/check/upload
jobs; it is an average, not a per-packet measurement. AP values are not silently
reused for Station. A physically calibrated whole-battery energy result remains
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
