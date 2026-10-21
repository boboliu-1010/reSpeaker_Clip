> 归档说明（2026-09-21）：以下为本次开发笔记，保留原工作区路径和历史验证记录。当前本地仓库为 `/Users/bobo/code/respeaker-personal`，后续主线是仓库根目录的 `mobile/app`；Clip Notes 原型仍位于 `mobile/sdk/flutter/example`，尚未迁入完整 App。文中的 `upstream/` 指本仓库根目录。运行日志、录音、密钥及构建缓存未上传。

# reSpeaker Clip 本地调试项目

## 2026-10-21：Boa Voice 定制设计评审

先看[基于官方 App 的修改与增强清单](../docs/product/official-app-customization.md)，再看[模块与协议设计](../docs/superpowers/specs/2026-10-21-boa-voice-module-protocol-design.md)。重点是自定义 endpoint、权限控制、存储控制和自选模型。当前分支只同步文档；以下旧开发记录保留为历史，不能视为最新软件状态。

目标：开发可自行控制的 Clip Notes：无 Clip 时用手机录音，按需调用自选模型；硬件到货后接通设备录音、下载和统一管理。

**当前总览与开发入口：[项目状态、开发说明与定制路线](docs/project-status-and-development.md)。**

## 当前状态（2026-09-20）

- 当前定制 App 位于 `upstream/mobile/sdk/flutter/example`，已有 Clip Notes 界面、系统麦克风录音代码、本地播放器及两组模型 API 配置。9 项测试通过、静态检查通过、iOS 模拟器构建安装成功；模拟器音频输入超时，真实录音和真实模型调用尚未验收。详见[模型配置说明](docs/local-model-api.md)。旧 SDK 面板位于「我的 → 设备调试工具」。

- 已保存官方仓库的独立 Git 副本，路径 `upstream/`，保留原始许可证。
- 基线提交：`d508d21e0c5c872bff3886cb27e7807826ceb90b`。2026-09-20 创建本地 `debug/local-setup` 分支，修正示例启动脚本的根目录计算。
- 已准备环境说明和硬件验收清单。
- 已通过 Homebrew 安装 Flutter 3.47.4 / Dart 3.13.3，并完成 SDK 与 example 的依赖解析。
- 初期验证记录：SDK 的 59 项测试和原示例的 1 项页面测试通过；修正快速重连的异步等待后，静态检查通过。
- 已选择 iPhone 路线。Xcode 27.0、CocoaPods 1.17.0 和 iOS 27.0 模拟器已准备完成，官方示例已成功编译、安装并在虚拟 iPhone 上显示界面。
- 完整官方 App `upstream/mobile/app` 也已通过 Xcode 构建并在模拟器显示登录页（2026-09-20）；修复了缺失 Google 配置引用及 FFmpeg/Opus ARM 模拟器兼容性。未登录、未验证云端与设备功能；其现有测试 2 通过、1 失败，详见本地项目讲解。
- 真机签名、安装及 Clip 硬件测试仍待完成；模拟器产物不能直接安装到真实 iPhone。详见 [模拟器调试说明](docs/ios-simulator.md)。
- 详见 [本次调试记录](docs/debug-2026-09-20.md)。
- 录音与硬件验证无需服务器；实际 AI 处理需要配置可用模型 API。尚未部署自己的业务后端。

## 从哪里开始

自主版本调研已保存：[源码、授权、服务替换与开发路线](docs/self-controlled-version-research.md)。建议先做不依赖厂商账号的本地 Flutter App，再接自有服务；当前已在示例工程落地原型，尚未迁移到独立产品工程，设备通信仍依赖官方 SDK。

本地开发入门：[项目目录、Xcode/Flutter 分工与快速开发步骤](docs/local-project-tour.md)。

1. 阅读 [环境准备](docs/environment.md)，安装所选平台工具链。
2. 阅读 [真机调试清单](docs/hardware-checklist.md)，准备 Clip、手机和数据线。
3. 运行最小示例；需要业务功能时再评估 `upstream/mobile/app/`。

目录：

```text
respeaker-clip-lab/
├── README.md
├── docs/
│   ├── environment.md
│   └── hardware-checklist.md
└── upstream/                    官方仓库，独立 Git 副本
    └── mobile/
        ├── sdk/flutter/example/ Clip Notes 定制原型（当前入口）
        ├── sdk/android/         原生 Android SDK
        ├── sdk/ios/             原生 iOS SDK
        └── app/                 已有业务 App，含账号、录音库、转写和摘要代码
```

## 最小示例启动

工具安装完成后，先执行：

```bash
cd /Users/bobo/code/respeaker-clip-lab/upstream/mobile
flutter doctor -v
bash scripts/check_environment.sh android  # iPhone 改成 ios
cd sdk/flutter/example
flutter pub get
flutter devices
flutter run -d <从列表取得的真机ID>
```

iOS 还需在 `flutter pub get` 后到 `ios/` 运行 `pod install`，再打开 `Runner.xcworkspace` 配置 Team、Bundle Identifier、Hotspot Configuration；详细步骤见环境文档。

**启动脚本路径已于 2026-09-20 本地修正。** 原版转发到 example/setup.sh 后，把 `sdk/flutter` 当成根目录，寻找不存在的 `sdk/flutter/scripts/check_environment.sh`。现改为定位 `mobile/`；依赖安装原本就正确指向 example，旧文档对这一点的描述已纠正。已验证脚本能进入实际的工具链检查，完整执行仍依赖 Flutter 和平台工具链准备完毕。

## 已知边界

- SDK 标为 0.1.0 preview；文档或 API 不等于已通过你的设备测试。
- 固件 Apache 2.0 与手机 SDK 的商业许可分开；硬件订单是否包含相应使用、修改和分发授权，需向 Seeed 确认。参见 `upstream/mobile/sdk/flutter/LICENSE`。
- 设备 `.opus` 是长度前缀的原始帧，不是普通播放器可直接播放的 Ogg Opus；必须转换。
- 官方调试面板的设备下载仍未接入定制录音库；新增手机录音使用持久目录和本地播放器，完整实录流程待验收。
- 业务 App 默认指向官方服务；自建产品要评估后端接口和授权，不要将构建成功视为云端可用。
- 本项目不包含账号密钥、签名证书或固件升级包。

## 下一次继续的提示

> 项目在 /Users/bobo/code/respeaker-clip-lab。请先阅读 README 和 docs，检查 Flutter 与所选平台环境，然后用 upstream/mobile/sdk/flutter/example 在真机验证 Clip。先完成短录音下载和播放，不升级固件，不自动删除设备录音。记录手机系统、固件版本、仓库提交和测试结果。

上游：https://github.com/Seeed-Studio/reSpeaker_Clip
