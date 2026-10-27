# 外置 Flash 布局与 Wi-Fi 补丁

当前上传固件使用外置 SPI NOR 存放 nRF7002 固件补丁，减少应用内部 Flash 占用。
应用启动时分块读取并加载到 Wi-Fi 芯片；这不是外置 Flash XIP，也不把整份补丁常驻在应用RAM。

## 当前布局

板级分区定义为 [`pm_static_clip_nrf5340_cpuapp.yml`](../boards/seeed/clip/pm_static_clip_nrf5340_cpuapp.yml)。
外置 NOR 总计8 MiB，地址为该设备内偏移：

| 范围（末端不含） | 用途 |
|---|---|
| `0x000000..0x0f0000` | 应用核 OTA secondary slot |
| `0x0f0000..0x130000` | 网络核 OTA secondary slot |
| `0x130000..0x7e0000` | LittleFS，大小 `0x6b0000`，107个64 KiB块 |
| `0x7e0000..0x800000` | 独立 Wi-Fi 补丁，128 KiB |

SD上的录音不在此Flash。LittleFS保存设备settings，包括配网、接收端和上传开关。
构建选择 `SB_CONFIG_WIFI_PATCHES_EXT_FLASH_STORE=y`，保留 SDK 补丁完整性校验，
读取块大小2048 B。SPI NOR与Wi-Fi接口不同，不能把生成HEX的逻辑地址当作可直接烧写的SPI偏移。

## 普通升级和首次迁移

已经使用该布局的设备，应用升级需继续保留匹配的补丁、文件系统几何和签名约束。
正常应用SMP升级包不自动写这份补丁；不能仅凭DFU成功认定新设备已完成布局迁移。

原厂旧布局的LittleFS曾延伸到外置Flash末端。首次迁移必须独立完成：

1. 读取并验证完整备份，确认当前设备、分区和补丁版本。
2. 离线重建缩小后的LittleFS，校验目录、文件、属性及配置；不能只改分区长度。
3. 使用受控维护程序写入新的文件系统和匹配的原始SDK补丁，再完整回读校验。
4. 验证冷启动、Wi-Fi启动／关闭、录音与设置恢复；保留能恢复原布局的备份。

维护程序在 [`applications/flash_maintenance/`](../applications/flash_maintenance/)，它不是正常
录音固件。此页不是直接执行擦写的命令清单，首次迁移需按设备实际备份和恢复方案执行。
回刷旧应用不会自动恢复旧文件系统布局。

Mac 端完整流程可由[一体化升级工具](../tools/flash_maintenance/README.md#mac-一体化升级工具)
串联。离线交付包内置运行环境及 SMP 客户端，用户无需安装开发工具；当前为开发验证
阶段，未知原厂版本拒绝，完整实机迁移和正式 Mac 签名／公证尚未完成。

## 构建校验

使用 [`scripts/verify_external_wifi_patch.py`](../scripts/verify_external_wifi_patch.py) 比较基线
与候选构建、原始 `nrf70.bin`。脚本检查配置传播、分区边界、HEX／补丁内容和镜像一致性；
依赖NCS环境的pyelftools、PyYAML、intelhex。参数以脚本 `--help` 为准。

当前布局已在项目设备使用。构建校验仍不代替新设备的实际SPI读写、首次迁移、补丁异常
或中断恢复测试。发布包与回退包需分别记录所要求的布局和补丁身份。
