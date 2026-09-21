# 手机录音与本机模型配置

项目：`upstream/mobile/sdk/flutter/example`，应用名 Clip Notes。

## 使用

1. 录音库 → 手机录音。首次允许麦克风权限，支持暂停、继续、结束保存；离开应用自动暂停。放弃会清理未保存音频。
2. 我的 → 模型 API，分别配置「语音识别」与「摘要与待办」。每组填写 API 基础地址、模型名称、API Key。
3. 基础地址填写 `https://服务域名/v1` 等完整前缀，不要包含 `/chat/completions` 或 `/audio/transcriptions`。目前仅支持 HTTPS。自建模型需要有效 HTTPS 入口；不支持直接填写 HTTP 的 localhost/Ollama 地址。
4. 打开真实录音 → 识别语音 → 确认发送目标。完成后点击「生成摘要与待办」。待办可勾选并保存，不会自动执行外部操作。
5. 原有三条演示记录仅用于界面参考，没有真实音频，也不会发送到模型。

语音模型必须支持 multipart `POST /audio/transcriptions`，返回 `{"text":"…"}`。文本模型必须支持 `POST /chat/completions`，返回 `choices[0].message.content`。不是所有聊天模型都能识别语音，也不是所有厂商接口都兼容这两种格式。

## 数据与限制

- AAC/M4A、16 kHz、单声道、64 kbps；文件位于应用 Application Support/recordings。
- 录音索引、转写、摘要、待办勾选状态保存在本机 JSON，串行原子替换写入。
- API 配置存入 flutter_secure_storage（iOS Keychain、Android 安全存储），不写进录音索引。应用不打印密钥或服务响应正文。Android 禁用应用备份，避免密钥恢复错配。
- 仅在用户确认后直接访问所配置服务，不依赖 Seeed 登录或转发后台。HTTPS 不跟随重定向；三分钟超时、不自动重试。取消客户端请求不保证服务端停止处理或计费。
- 单次转写文件上限 24 MB；不支持实时转写、长录音分段、后台持续录音或后台处理队列。
- 重新识别成功会清空旧摘要和待办，避免旧内容对应新转写。
- 录音和结果是应用私有文件，并非额外加密文件；设备系统备份策略仍应在产品化时明确。
- 示例 App 的商业许可仍需向 Seeed 确认；本次改造没有改变上游许可。

## 开发入口

- `lib/phone_recording.dart`：系统麦克风、录音生命周期和音频路径。
- `lib/model_api.dart`：安全配置、语音与文本 API 客户端、错误处理。
- `lib/model_settings_page.dart`：两组模型设置。
- `lib/recording_detail.dart`：播放器、发送确认、转写和待办。
- `lib/companion_home.dart`：录音库和本机持久化，旧记录兼容。

## 验证

`flutter analyze`；`flutter test`；`DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer flutter build ios --simulator --debug`。
接口测试使用合成文件和 mock HTTP，不会调用收费服务。真实模型效果仍需用户填写服务与密钥后测试。Android 真机与 Clip 硬件未验证。

### 2026-09-20 本机验证记录

- 9 项 Flutter 测试通过；静态分析无问题；iOS 模拟器 Debug 构建成功并安装。
- 模拟器确认模型配置页可打开，Keychain 空配置可保存，旧示例记录可迁移显示。
- 当前 iOS 27 模拟器启动麦克风时，CoreAudio 输入设备出现 `HALC_ProxyObject::SetPropertyData` 错误，未完成真实声音采集验证。已加入启动 15 秒超时、明确错误提示与退出路径；真实音频录制及播放仍需在可用输入设备或 iPhone 真机验证。
- 未配置真实 API Key，未进行收费 API 调用，也没有上传真实录音。
