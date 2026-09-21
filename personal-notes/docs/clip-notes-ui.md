# Clip Notes 界面预览

> 历史记录：此文描述最初 UI 预览。手机麦克风与模型 API 已在后续接入代码；当前范围和实测缺口以 [项目总览](project-status-and-development.md) 为准。

2026-09-20：按已确认的「录音库、设备、我的」设计，改造截图对应的 Flutter 示例入口。实现位于 `upstream/mobile/sdk/flutter/example/lib/companion_home.dart`；`lib/main.dart` 配置主题与入口，并保留原有 `DemoPage` 作为设备调试工具。完整官方 App `mobile/app` 未被此界面替换。

## 可体验

- 暖白、森林绿、浅绿配色；自绘设备示意和波形，不依赖在线字体或图片。
- 录音库分类、文本搜索、收藏、详情重命名、复制示例文本。
- 转写、摘要、待办三个详情标签；待办勾选仅在当前详情页保留。
- 演示录音计时、暂停、继续、放弃和保存演示记录；没有采集麦克风声音。
- 演示记录、收藏、名称和服务地址写入应用本地 `clip_notes_preview_v1.json`。
- 设备页说明真机要求，并提供原 SDK 调试工具入口；调试错误增加中文提示。
- 服务地址校验与保存；当前未连接后端，不会自动上传。

## 尚未实现

真实音频播放/导入/导出、实际转写摘要、文件夹、删除、业务界面中的真实设备状态与同步。原 SDK 工具仍可用于后续真机验证，但不代表新界面的设备流程已经打通。所有示例均标注演示，无可播放录音；设备画稿只用于界面展示。

## 验证

- 新行为先运行失败测试，再实现界面。
- `flutter test --no-pub`：2 项交互测试通过，覆盖搜索与详情、演示录音保存和设备页导航。
- `flutter analyze --no-pub`：No issues found。
- Xcode 模拟器构建成功；`flutter run` 安装启动；实际检查首页和详情页，无可见溢出。
- 尚未用硬件验证，也不把 UI 测试当成音频或云端验证。

## 启动

```bash
cd /Users/bobo/code/respeaker-clip-lab/upstream/mobile/sdk/flutter/example
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
flutter run -d D2F86963-B58F-415E-B460-BA7C14940148
```

模拟器桌面名称是 **Clip Notes**，沿用示例应用 ID，与完整官方 `cc.seeed.voice` 并存。这是已有示例上的本地 UI 迭代，不是已完成授权拆分的独立商业产品。
