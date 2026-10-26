# 项目文档

本目录只保留当前录音与DTLS主动上传项目需要的说明。旧HTTPS方案、阶段验证报告、
旧分支清单和过时资源表已移除，不设history目录。原始产品目标与当前实现范围分别说明。

## 当前实现

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
