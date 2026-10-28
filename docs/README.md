# Documentation Map

Entry point for all reSpeaker Clip documentation. English docs are canonical;
the only maintained translation is `tests/clip/README_zh.md`.

## Boa Voice integration

Current firmware development is based on Roger's DTLS branch. Boa business API, per-user storage and Web live in the unified Server tree:

- [Boa integration and local startup](../README-integration.md)
- [Product overview](product/boa-voice-overview.md), [desktop guide](../README-desktop.md)
- [Roger baseline and optional Boa extensions](contracts/roger-base-extension-v1.md)
- [Server installation](../server/boa/README.md), [Web guide](../server/web/README.md)
- [Current product designs](design/README.md), including binding, desktop Wi-Fi and Web sessions
- [Storage HTTP contract](contracts/storage-http-v1.md), [schema](contracts/storage-http-v1.schema.json), [examples](contracts/examples/storage-http-v1.json)
- [AI HTTP proposal](contracts/ai-http-v1.md), [schema](contracts/ai-http-v1.schema.json), [examples](contracts/examples/ai-http-v1.json): future model endpoints and persistent AI jobs
- [Historical ingest/processing proposal](contracts/clip-ingest-app-server-bridge.md), [device compatibility contract](contracts/clip-device-v1.md): read their dated scope before using as implementation requirements

The firmware protocol sources below remain authoritative for current wire behavior. Product designs do not establish deployment or physical-device acceptance.

## Where do I start?

| I want to... | Go to |
|--------------|-------|
| Upgrade a device in the field | [usb_dfu.md](usb_dfu.md) |
| Build a phone/desktop client | [protocol.md](protocol.md) (BLE AT) + [udp_protocol.md](udp_protocol.md) + [../mobile/README.md](../mobile/README.md) |
| Start firmware development | [../README.md](../README.md) (Getting Started) + [../applications/clip/README.md](../applications/clip/README.md) + [architecture.md](architecture.md) |
| Build my own app on the Clip board | [custom_app_guide.md](custom_app_guide.md) |
| Understand the hardware/board | [architecture.md](architecture.md) §10 Hardware Interfaces + [../tests/clip/README.md](../tests/clip/README.md) (pin/regulator tables) |
| Publish a release | [release_process.md](release_process.md) |
| Debug power draw | [power.md](power.md) |
| Fix a stuck device / common errors | [troubleshooting.md](troubleshooting.md) |
| Run hardware test firmware | [../tests/clip/README.md](../tests/clip/README.md) ([中文版](../tests/clip/README_zh.md)), [../tests/dtm/README.md](../tests/dtm/README.md), [../tests/wifi_radio/README.md](../tests/wifi_radio/README.md), [../tests/battery_cycle/README.md](../tests/battery_cycle/README.md), [../tests/re/README.md](../tests/re/README.md) |
| Run the Python test suite | [../applications/clip/tests/docs/testing.md](../applications/clip/tests/docs/testing.md) |

## Index

**Getting started**

- [../README.md](../README.md) — repo overview, toolchain install, build/flash
- [../applications/clip/README.md](../applications/clip/README.md) — main application guide

**Guides**

- [architecture.md](architecture.md) — system architecture and design
- [custom_app_guide.md](custom_app_guide.md) — custom apps, signing, OTA, DFU recovery
- [usb_dfu.md](usb_dfu.md) — firmware upgrade (USB / BLE / programmer)
- [release_process.md](release_process.md) — tagging and publishing a release
- [power.md](power.md) — power measurements and idle budget
- [troubleshooting.md](troubleshooting.md) — common errors and recovery

**Protocol specs**

- [protocol.md](protocol.md) — BLE AT command protocol (WiFi AP credentials, AT command list in Appendix A)
- [udp_protocol.md](udp_protocol.md) — WiFi UDP file transfer protocol

**Reference**

- [requirements.md](requirements.md) — product requirements
- [audio_quality_standard.md](audio_quality_standard.md) — audio quality test standard
- [development.md](development.md) — development log

**Release notes**

- [release_notes/](release_notes/) — one `vX.Y.Z.md` per release

**Mobile**

- [../mobile/README.md](../mobile/README.md) — companion app and SDK monorepo
- [../mobile/app/docs/](../mobile/app/docs/) — app design/API docs

**AI-assisted development**

- `skills/clip-dev` — firmware development skill (Zephyr/board specifics)
- `skills/clip-sdk` — SDK/client integration skill

## Single source of truth

| Fact class | Owner |
|------------|-------|
| WiFi AP credentials & BLE name | [protocol.md](protocol.md) §2 |
| Power figures (idle current, budgets) | [power.md](power.md) |
| AT command list / count | [protocol.md](protocol.md) Appendix A |
| Build commands | [../README.md](../README.md) |
| MCUboot patch details | [../patches/mcuboot/README.md](../patches/mcuboot/README.md) |

Other files summarize; when they disagree, the owner above wins.


---

## 当前上传分支文档

基线文档完整保留；下列入口描述本分支的增量功能。基线指南中的 AP、USB 磁盘、BLE OTA、资源与性能数据需要结合当前构建配置阅读。各基线指南末尾保留当前分支补充，不恢复已淘汰的 HTTPS 实验文档。

### 当前实现


| 文档 | 内容 |
|---|---|
| [architecture.md](architecture.md) | 硬件职责、录音／上传模块、数据流和存储关系 |
| [dtls-upload-core.md](dtls-upload-core.md) | 自动调度、连续DATA、断点续传、状态双槽、哈希缓存、整段删除和待办 |
| [protocol.md](protocol.md) | App使用的BLE／USB AT接口、通知、录音及文件传输格式 |
| [network.md](network.md) | DHCP／ARP补丁、Wi-Fi关联诊断和网络问题定位 |
| [power.md](power.md) | 上传省电策略、PMIC采样、电量模型、诊断接口和校准限制 |

## 开发与交付

| 文档 | 内容 |
|---|---|
| [development.md](development.md) | 当前分支策略、构建／测试入口、产物管理和资源基准 |
| [usb_dfu.md](usb_dfu.md) | 当前USB恢复升级、镜像选择、签名与故障回退 |
| [wifi-patch-external-flash.md](wifi-patch-external-flash.md) | 当前外置Flash布局、独立Wi-Fi补丁和首次迁移边界 |
| [release_process.md](release_process.md) | 发布准备、当前CI差异与验证材料 |
| [troubleshooting.md](troubleshooting.md) | 当前上传、录音、供电、配对与恢复排查入口 |
| [custom_app_guide.md](custom_app_guide.md) | 同一板级源码上的自定义应用开发参考；其可选功能不等于当前上传固件已启用 |

## 产品与测试依据

- [requirements.md](requirements.md)：原始产品需求，不能当作当前已实现功能清单。
- [audio_quality_standard.md](audio_quality_standard.md)：音质测试方法与验收目标，不替代实际测试结果。

## 代码入口

- 固件：[`applications/clip/`](../applications/clip/)。
- 编译、设备控制和主机回归：[`tools/upload/`](../tools/upload/README.md)。
- DTLS接收服务：[`server/`](../server/README.md)。
- 外置Flash构建校验：[`verify_external_wifi_patch.py`](../scripts/verify_external_wifi_patch.py)。
- 板级硬件测试：[`tests/clip/`](../tests/clip/README.md)。

接口以当前源码和[协议规范](protocol.md)核对；资源数字注明对应提交及构建模式，静态
RAM与运行时峰值分开。网络、吞吐和电量结论必须有对应实测，不因文档合并扩大验证范围。
