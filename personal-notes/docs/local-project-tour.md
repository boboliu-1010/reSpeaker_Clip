# 本地项目讲解：快速开发自己的 reSpeaker App

> 当前状态请先看 [项目总览与定制路线](project-status-and-development.md)。本文后半保留官方完整 App 的构建历史，不能与当前定制原型的测试结果混用。

项目根目录：`/Users/bobo/code/respeaker-clip-lab`。

## 先分清三个东西

| 路径（相对根目录） | 用途 | 何时看 |
|---|---|---|
| `upstream/mobile/sdk/flutter/example` | 当前 Clip Notes 定制原型，内含官方调试面板 | 日常开发入口；手机录音和模型 API 已接入，真实闭环待验收 |
| `upstream/mobile/app` | 官方完整 Flutter App | 研究页面、录音库、转写和云端交互；默认仍是官方账号体系 |
| 独立产品工程 | 当前尚未从示例迁出 | 应独立开发并拥有自己的标识、数据目录、服务和通信边界 |

`upstream` 是独立 Git 仓库，当前分支 `debug/local-setup`。根项目中的调研和操作文档属于另一层 Git。不要把两个目录的提交、依赖安装和构建命令混在一起。

## Xcode 与 Flutter 如何配合

Flutter/Dart 负责页面、状态、业务、存储和跨平台代码。Xcode 负责 iOS 原生项目、模拟器/真机运行、签名、权限能力及原生错误排查。

打开完整 App 应选择 `upstream/mobile/app/ios/Runner.xcworkspace`；最小示例则选择 `upstream/mobile/sdk/flutter/example/ios/Runner.xcworkspace`。两者都叫 Runner，要核对窗口对应的完整路径。安装 CocoaPods 后用 workspace，才能同时加载 Pods 依赖。

日常页面修改在 `lib/` 中进行。使用 `flutter run` 时按 `r` 热重载、`R` 热重启；改原生插件、Podfile、系统权限或编译参数后要停止并重新构建。热重载并不代表重新跑了 main() 或初始化逻辑。

## 完整 App 的阅读顺序

以下路径相对 `upstream/mobile/app/`：

1. `pubspec.yaml`：依赖、SDK 路径、资源、Flutter 配置。
2. `lib/main.dart` → `lib/src/bootstrap.dart`：入口和初始化。
3. `lib/src/app/router/app_router.dart`：页面导航、登录拦截。
4. `lib/src/features/device/`：设备状态和操作；当前 controller 很大，不建议照着它组织新项目。
5. `lib/src/features/recordings/`：录音列表、详情、播放、同步、转写流程。
6. `lib/src/core/db/`、`lib/src/core/storage/`：数据库和按账号分区的文件。
7. `lib/src/core/audio/`：原始 Opus 解码、合并、波形、封装。
8. `lib/src/core/server/`：认证、上传、ASR、LLM、固件 API。
9. `ios/Runner/Info.plist`、`Runner.entitlements` 和 `android/app/src/main/AndroidManifest.xml`：平台权限。

手机 SDK 在 `upstream/mobile/sdk/flutter/lib/`；根协议在 `upstream/docs/protocol.md` 和 `udp_protocol.md`；电脑验证工具在 `upstream/sdk/`。

## 可复用的启动操作

本机全局 xcode-select 仍可能指向 CommandLineTools，以下命令显式指定 Xcode，避免改全局配置。

```bash
cd /Users/bobo/code/respeaker-clip-lab/upstream/mobile/app
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
bash third_party/opus_flutter_ios/build-simulator.sh  # 首次运行，需 CMake
flutter pub get
cd ios
pod install
open Runner.xcworkspace
cd ..
flutter devices
flutter run -d D2F86963-B58F-415E-B460-BA7C14940148
```

最后的 ID 是当前 iPhone 18 Pro 模拟器；若删除或重建模拟器，应使用 `flutter devices` 输出中的新 ID。运行最小示例时，把起始目录改为 `.../mobile/sdk/flutter/example`，跳过 Opus 构建脚本。

在 Xcode 中选择 Runner scheme，目标选具体 iPhone 模拟器后运行。真机则另需自己的 Team、Bundle Identifier 和所需能力，模拟器产物不能安装到物理 iPhone。

## 最快开发自主版本的顺序

第一步先把页面与硬件分开。定义设备接口，例如扫描、连接、状态、开始/停止录音、列举与下载文件。模拟器使用明确标记为演示的假设备实现，真机使用实际 BLE/UDP 实现。两者共用同一录音库和 UI，避免硬件未到就停工，也避免演示数据冒充实测。

第二步只做设备、录音库、任务、设置四个入口。先实现导入测试音频、播放、重命名和导出，不先接账号与大模型。任务状态至少分为等待、下载、校验、解码、完成和失败。

第三步用短录音把真机闭环跑通：连接 → 录音 → BLE 下载 → 校验 → 转为可播放音频 → 导出。Wi-Fi 下载、断点恢复和锁屏恢复随后加入。保留原始音频，不自动删除硬件文件。

第四步启用可选云端：自己的服务地址、私有存储、转写和摘要。断网或服务故障时，本地录音仍可访问。不要直接把官方的登录开关改成 false 就认定完成离线改造，本地数据目录也依赖账号身份。

获得手机 SDK 授权后可通过适配层接入它加速；长期自建通信实现可根据公开协议和许可明确的参考开发。新项目不要直接复制商业 SDK 源码。完整官方 App 的功能范围、许可和第三方音频库分发要求还需分别确认。

## 完成标准

- 模拟器：页面、状态、测试音频播放和错误流程；不证明设备通信可用。
- 真机 + Clip：配对、录音、BLE/Wi-Fi 下载、完整性、恢复、导出。
- 自主性：禁用官方服务仍能拿到录音；云端只连配置的服务；完整备份可迁移。

详细取舍和证据见 [自主版本调研](self-controlled-version-research.md)。

## 本次运行中已确认的问题（2026-09-20）

- 模拟器运行时挂载路径发生变化后，CoreSimulator 保留旧路径。重启该服务后模拟器恢复，原数据未擦除。
- 官方完整 App 的 Xcode 工程仍引用未提供的 `GoogleService-Info.plist`；已移除失效的资源引用。未配置 Google 登录，未添加账号或密钥。
- 原锁定的 FFmpeg 插件 4.1.0 排除了 ARM 模拟器；更新到 4.6.2，保留 CocoaPods 集成。依据：[插件维护者更新记录](https://pub.dev/packages/ffmpeg_kit_flutter_new/changelog)。音频实际转换还需单独验证。
- Opus iOS 插件 3.0.1 缺少 ARM 模拟器 slice。新增 `third_party/opus_flutter_ios` 本地覆盖和 `build-simulator.sh`，使用仓库 libopus 源码编译真正的模拟器 framework，保留原有真机 framework。已安装 CMake；生成库不入 Git，干净环境先运行脚本。当前生成包支持 Apple Silicon 模拟器，不包含 Intel 模拟器 slice。
- Flutter 根据当前工具链把最低 iOS 部署目标迁移到 15.0，更新了锁文件和分析排除配置；生成的跨平台插件注册文件也随依赖变更更新。
- `flutter test`：2 项通过、1 项失败。`test/widget_test.dart` 缺少 ProviderScope，并且期待启动后直接显示“设备”；该测试尚未适配实际初始化和登录流程，未为了展示修改产品登录行为。
- `flutter build ios --simulator` 曾报 `app_settings` 模块找不到，随后使用 Xcode 的具体模拟器目标重新构建，模块正常生成。此后通过 `flutter run` 成功启动。
- 最终验证：Xcode `BUILD SUCCEEDED`；`cc.seeed.voice` 安装成功；Flutter 输出 `first frame rendered`；模拟器实际显示 SenseCraft Voice 登录页（Apple/Google/GitHub/邮箱）。没有登录或接受用户协议，硬件和云端功能未测试。
- Opus 首次链接后出现动态库名称大小写不一致；构建脚本已统一 bundle executable 与 install name 为 `opus`，重新签名并重建后启动成功。`vtool` 确认库面向 IOSSIMULATOR，核心解码符号存在；实际音频解码仍待验证。

Xcode 具体模拟器构建命令（从完整 App 的 `ios` 目录运行）：

```bash
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild \
  -workspace Runner.xcworkspace -scheme Runner -configuration Debug \
  -sdk iphonesimulator \
  -destination 'platform=iOS Simulator,id=D2F86963-B58F-415E-B460-BA7C14940148' \
  BUILD_DIR=/Users/bobo/code/respeaker-clip-lab/upstream/mobile/app/build/ios build
```
