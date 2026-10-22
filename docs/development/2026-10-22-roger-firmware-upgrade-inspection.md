# Roger 固件升级相关代码核对

日期：2026-10-22。性质：Git 提交与源码静态核对，不是固件构建、刷机或真机验收。

## 核对范围与结论

已从 `https://github.com/roger-gan/reSpeaker_Clip.git` 获取当前分支引用。重点核对：

- Roger 当前 `experiment/https-runtime-0.1.2`：`3245fafd3b217f38967c1795c627ea5452fe5f33`。
- 我们集成分支固定的 Roger 作者提交基线：`cfff60539d94c6d3e43f788592b97a76547278fe`。它与 Roger 当前上述分支 tip 不同，不能混作同一个版本。
- Roger 的 main/dev 等分支也作了对照；它们不是同一份 HTTPS 实验构建，不能概括“Roger 仓库所有固件都禁用 OTA”。

**涉及升级，而且当前 HTTPS 实验构建主动禁用应用层 OTA，保留 bootloader USB 恢复。没有找到该实验代码已经实现自建固件库、发布、升级授权或 App 固件管理的证据。**

## Roger 的直接改动

| 提交 | 改动 | 对 App/升级的影响 |
| --- | --- | --- |
| `930f777dd3d1b8b33cab2cdf8413f36d27f7b4fc` | HTTPS 实验开关、应用 DFU 拒绝分支和受限 AT 控制面 | 启用 CONFIG_CLIP_HTTPS_POC 后，DFU started/chunk 回调返回 MGMT_ERR_EBUSY，不是临时仅在上传期间忙；不能直接复用 App BLE OTA |
| `7afc3cc3bde830582b16147b4506181c99e50f70` | Wi-Fi 补丁迁到外置 SPI NOR；保留两个更新镜像，不增加 Wi-Fi patch DFU 槽 | OTA ZIP 不包含这份独立补丁；普通 App/网络核升级包不能代替外置补丁配置和布局迁移 |
| `7027496` | 临时 flash_maintenance 固件、USB 主机备份/迁移/恢复工具 | 有 USB 维护能力，但要使用维护应用和外部工具，不是已经接入 Boa App 的升级页面 |
| `4a7192c` | 外置补丁硬件验证记录 | 属于上游作者的验证文档，不代表我们本机或手上设备完成升级验收 |

### 应用 OTA 被拒绝的直接证据

[clip_event.c](../../applications/clip/src/clip_event.c) 的 mcumgr_dfu_cb 在 CONFIG_CLIP_HTTPS_POC 下，对 MGMT_EVT_OP_IMG_MGMT_DFU_STARTED / DFU_CHUNK 返回 MGMT_ERR_EBUSY；git blame 指向 Roger 的 `930f777`。Roger 当前实验 tip 和我们 cfff605 基线都保留这段逻辑。

[Kconfig](../../applications/clip/Kconfig) 帮助明确写了“disables application OTA during this experiment”；[https.conf](../../applications/clip/https.conf) 实际启用 CONFIG_CLIP_HTTPS_POC。不能仅凭 prj.conf 中基础 OTA 配置为 y 推断最终构建支持升级。

[https_poc.c](../../applications/clip/src/https_poc.c) 的 AT 白名单没有 DFU，[at_server.c](../../applications/clip/src/at_server.c) 在分派前执行白名单检查。普通 AT+DFU 处理器仍在源文件中，不代表 HTTPS 实验模式允许调用它。

## 继承的能力与限制

- BLE mcumgr/SMP、OTA 进度、双镜像、1200-baud USB CDC 进入 MCUboot 和 overwrite-only 策略，有上游原有实现；不能都算作 Roger 新增。1200-baud 入口的原提交是 Lynn 的 `5a3604d`，overwrite-only 默认由 `c1f6224` 引入。
- [板级配置](../../boards/seeed/clip/Kconfig.sysbuild) 当前默认 overwrite-only，不是自动回滚模式。[运行时记录](../https-runtime-0.1.2.md) 也明确说明无自动回滚；不能把“保留旧版本文件”写成“设备可自动回滚”。
- [外置补丁说明](../wifi-patch-external-flash.md) 记录补丁独立配置，LittleFS 从 0x6d0000 缩到 0x6b0000，两个原有 OTA 槽地址/大小保留。跨此布局需要备份和迁移，不能只刷应用。
- [USB 维护工具说明](../../tools/flash_maintenance/README.md) 的备份包含蓝牙密钥和配置，应保留在私有目录；不能上传普通固件库或提交仓库。
- [HTTPS 接收端](../../tools/https_poc/server.py) 处理录音 /v1、/v2 GET/PUT，不是固件版本分发接口；联网录音上传不能推出联网 OTA 已实现。

## 对 Boa 设计的必要修正

1. BLE OTA 是目标交付能力，**当前 HTTPS profile 不满足其固件前置条件**；App/Server 不能给该 profile 显示可 BLE 升级或签发相应开始许可。
2. 管理固件包、版本和权限可继续设计/开发，不等于能马上给当前实验固件刷写。恢复应用 OTA 需要独立固件改造和资源/互斥/中断恢复验收；不能简单删除拒绝逻辑就宣称完成。
3. USB recovery 是现有维护路径，首版文档指引可参考既有工具；若要直接在 App 操作，仍需 USB 适配器、权限、工具边界、备份/恢复与真机验收，不伪装成已有 BLE 功能。
4. 兼容矩阵必须包含外置补丁/存储布局和配置迁移影响；同为 0.1.2 或同一板型也不能默认互刷。

本次只更新核对记录和设计约束，未改固件/App/Server 运行代码、未切换集成基线、未刷机或发布。
