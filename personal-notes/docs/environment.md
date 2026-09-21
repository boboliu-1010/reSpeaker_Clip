# Mac 环境准备

## 最新状态（2026-09-20）

最终更新：完整 Xcode 27.0 及 iOS 27.0 模拟器已安装，许可与初始化已完成。示例已在 iPhone 18 Pro 模拟器上运行并通过画面确认；见 ios-simulator.md。通过命令级 DEVELOPER_DIR 指定 Xcode，不修改全局 xcode-select。以下为早期阶段记录。

后续已选择 iPhone：CocoaPods 1.17.0 已安装并通过 `pod --version` 验证；已打开 Xcode 的 App Store 页面，完整 Xcode 尚未安装，开发者 Team 未配置。下面的 doctor 结果为 CocoaPods 安装前的记录。

已安装 Flutter 3.47.4 / Dart 3.13.3，SDK 位于 `/opt/homebrew/share/flutter`，命令已链接到 `/opt/homebrew/bin`。`flutter doctor -v` 确认网络正常；仍缺 Android SDK、完整 Xcode、CocoaPods，没有手机或模拟器，只列出 macOS 和 Chrome。SDK 与示例测试已通过，但测试不是手机安装包构建。详见 debug-2026-09-20.md。

## 首次检查的状态（历史记录）

2026-09-18：Git、Homebrew、VS Code 已安装；默认 Java 为 23.0.2。命令路径未找到 Flutter、Dart、adb、CocoaPods。常用目录未发现 Android Studio、Android SDK 和完整 Xcode；`xcode-select -p` 指向 CommandLineTools，`xcodebuild -version` 无法运行。空闲磁盘约 232 GiB。

这些是当前路径与常用目录的检查结果，不代表已搜索整块磁盘。本次项目准备没有安装工具或修改全局环境。

## Android 路线

1. 安装 Flutter stable，确保满足仓库要求 Flutter >= 3.27、Dart >= 3.6，并把 Flutter 的 bin 加入 PATH。最终采用版本需经依赖解析和构建验证，不只看最低版本。
2. 安装 Android Studio，通过 SDK Manager 配置 Android SDK 36、Platform Tools，以及 Flutter 构建实际要求的 Build Tools / NDK。
3. 配置 JDK 17；保留现有 Java 23，避免影响其他项目。
4. 设置 ANDROID_HOME 为真实 SDK 目录，将 platform-tools 加入 PATH。
5. 阅读并接受必要的 Android SDK 许可，运行 `flutter doctor --android-licenses`、`flutter doctor -v`。
6. 手机开启开发者选项、USB 调试，通过数据线连接，允许此电脑调试。
7. `flutter devices` 应出现真机，执行 README 中的示例启动步骤。

## iPhone 路线

1. 安装 Flutter、完整 Xcode 和 CocoaPods。仅 Command Line Tools 不足以构建 iPhone App。
2. 打开 Xcode 完成首次启动、许可和所需平台组件安装；确认开发目录指向完整 Xcode。
3. 连接并信任 iPhone，根据系统要求启用开发者模式。
4. 从示例目录安装依赖：

```bash
cd /Users/bobo/code/respeaker-clip-lab/upstream/mobile/sdk/flutter/example
flutter pub get
cd ios
pod install
open Runner.xcworkspace
```

5. 在 Runner 中选择自己的 Team 和唯一 Bundle Identifier，确保 App ID 与签名包含 Hotspot Configuration。
6. 免费账号的基础真机调试不等于所有能力可用；以实际签名结果为准。完整热点流程需要可签署对应能力的账号配置。
7. 授予蓝牙、本地网络权限，运行 `flutter doctor -v` 和 `flutter devices`，再运行示例。

## 工具链完成的验收条件

- 所选平台的 `flutter doctor -v` 没有阻断项。
- 真机能被 `flutter devices` 识别。
- 示例依赖解析成功，能构建、安装并启动。
- Clip 到货后再验收 BLE、热点和音频传输；模拟器不能替代这些测试。

## 服务器

硬件验证阶段不用服务器。接入业务时可先在 Mac 上启动 Spring Boot；手机通过 Mac 的局域网 IP 访问，不能使用手机自己的 localhost。手机加入 Clip 热点后，应先完成下载，退出热点并确认互联网或局域网服务可达，再上传。

参考：
- https://github.com/Seeed-Studio/reSpeaker_Clip/blob/main/mobile/docs/getting-started.md
- https://github.com/Seeed-Studio/reSpeaker_Clip/blob/main/mobile/sdk/flutter/README.md
