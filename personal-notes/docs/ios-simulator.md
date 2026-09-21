# iPhone 模拟器调试

## 构建环境

- Flutter 3.47.4 / Dart 3.13.3、CocoaPods 1.17.0。
- Xcode 27.0（27A266a），安装在 `/Applications/Xcode.app`，许可和首次初始化已完成。
- 系统 xcode-select 仍指向 CommandLineTools。此项目通过命令级 `DEVELOPER_DIR` 使用 Xcode，不改变其他项目的全局设置。
- 当前构建最低系统版本为 iOS 15.0（由新版 Flutter 迁移），不是此前文档的 iOS 13。

## 复现构建

```bash
cd /Users/bobo/code/respeaker-clip-lab/upstream/mobile/sdk/flutter/example
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
flutter pub get
cd ios
pod install
cd ..
flutter build ios --simulator --debug --no-pub
flutter devices
```

已有 CocoaPods 工程。当前 pubspec 明确设置 `flutter.config.enable-swift-package-manager: false`，与仓库业务 App 的策略一致。首次失败报 `Module 'file_picker' not found`：插件被部分划入 SwiftPM，但旧工程没有完整集成。设置项目级配置后还必须重新运行 `pod install`，才能将 file_picker、flutter_blue_plus_darwin、path_provider_foundation 纳入 Pods。仅修改 pubspec 后重复 build 并不能修复既有 Pods。

构建产物：`upstream/mobile/sdk/flutter/example/build/ios/iphonesimulator/Runner.app`。

## 已验证

- `flutter build ios --simulator --debug --no-pub` 成功。
- example 静态检查通过。
- example 页面测试 1 项通过。
- `git diff --check` 通过。

构建仍提示部分插件不支持 SwiftPM 的未来迁移警告；本次使用 CocoaPods 已成功构建，不把警告描述为全部消失。

## 安装与运行

运行时安装完成并启动模拟器后执行：

```bash
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
xcrun simctl install booted /Users/bobo/code/respeaker-clip-lab/upstream/mobile/sdk/flutter/example/build/ios/iphonesimulator/Runner.app
xcrun simctl launch booted com.seeed.sensecraftvoice.sensecraftVoiceExample
```

Xcode 27 的本机设备管理应用位于 `/Applications/Xcode.app/Contents/Applications/DeviceHub.app`。

模拟器用于界面验证。本示例没有模拟 Clip 数据，蓝牙、录音控制、热点下载和 OTA 仍需真实手机与设备；模拟器包不能直接安装到真机。真机还要单独签名和构建。

## 运行状态

已完成 iOS 27.0 ARM64 运行时安装，启动 iPhone 18 Pro 模拟器（D2F86963-B58F-415E-B460-BA7C14940148），使用 simctl 安装并启动示例。已通过 Device Hub 的实际画面和可访问性文本确认显示 SenseCraft Voice SDK Demo、Scan 和各设备操作按钮。首次启动曾短暂黑屏，随后正常显示；没有据此修改业务代码。

尚未连接 Clip。录音、下载等按钮在未连接状态灰显，真实硬件流程未验证。
