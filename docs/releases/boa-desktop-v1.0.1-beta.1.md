# Boa Voice 1.0.1-beta.1

macOS 桌面端与自托管音频存储服务的 Beta 预发布。后续验收完成前继续使用 Beta 版本号；本次不合并到 main，不作为固件正式版本。

## 下载与安装

- `Boa-Voice-1.0.1-beta.1-macos-universal.dmg`：桌面 App，支持 Apple Silicon 和 Intel。
- `Boa-Audio-Storage-1.0.1-beta.1-source.tar.gz`：Server 源码和锁定依赖，需 Python 3.11+。
- `SHA256SUMS`：发布资产校验值。
- `dmg-verification.json`：映像挂载、安装入口、架构及复制后签名验证结果。

打开 DMG，将 Boa Voice.app 拖入 Applications，等待复制后推出映像。首次使用麦克风、蓝牙需允许相应系统权限。本次为临时签名，未经过 Apple 公证，其他 Mac 首次运行和最低系统版本兼容性仍需验证。

首次出现“Apple 无法验证”时，确认来源后，前往“系统设置 → 隐私与安全性”，在 Boa Voice 被阻止提示旁选择“仍要打开”，由安装者本人按系统提示确认。详见 [首次打开说明](https://github.com/BofAI/reSpeaker_Clip/blob/boa/macos-desktop-audio-storage/docs/macos-signing-and-notarization.md)。

Server 独立启动，不包含在 App 中。上述源码附件是历史 Beta 1 的单用户服务，目录和启动方式与当前开发分支不同。当前统一 Server 使用仓库根目录的 `python -m server`、`python -m server.boa.manage` 和 `server/requirements.txt`，安装步骤见 [当前 Server 说明](../../server/boa/README.md)。旧数据需由开发者明确指定归属后迁移。

## 功能与验收范围

本地导入、搜索、时间倒序、存放位置标识、离线播放、HTTP 分片上传/下载、下载续传、自动备份队列、Clip BLE 连接及录音控制入口。

14 项 Flutter 桌面/存储测试和 12 项 Server 接口测试通过；局部静态分析及 macOS Release 构建通过。DMG 验证以附件报告为准。

麦克风真实采集、Clip 硬件完整联调尚未完成；桌面入口尚未接入 Clip 文件下载、Wi-Fi 同步、OTA、模型配置、转写与摘要。Server 当前为个人自用的单用户文件服务。

完整说明：[桌面与 Server README](https://github.com/BofAI/reSpeaker_Clip/blob/boa/macos-desktop-audio-storage/README-desktop.md)。
