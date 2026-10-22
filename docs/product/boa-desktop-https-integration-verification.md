# Boa 桌面与 HTTPS 实验分支集成验证

日期：2026-10-22。分支：`boa/desktop-https-integration`。范围：迁入既有桌面和音频服务、保留实验固件，未实现新桥接。

## 代码保留

- 实验基线：`cfff60539d94c6d3e43f788592b97a76547278fe`，是本分支祖先。
- 桌面来源：`c69830b`；从 `1c75058` 到 `c69830b` 的 13 个桌面线提交使用 `cherry-pick -x` 迁入，无冲突。
- 对比实验基线，`applications/`、`boards/`、`tools/` 完全一致；原固件脚本保持一致，仅新增既有桌面构建脚本。
- 对比桌面来源，`mobile/`、`services/` 的受控文件保持一致。Flutter 工具自动追加的分析配置排除项在验证后恢复，未做依赖升级。
- 原 `boa/desktop-beta3` 分支保持 `c69830b`；原安装 App、录音、设置和既有服务未修改。

## 回归结果

| 验证 | 本次结果 |
| --- | --- |
| `python3 -m unittest discover -s tools/https_poc -p 'test_*.py'` | 集成前后均 90 项运行，89 通过、1 跳过；缺少 `CLIP_TEST_SDK` 外部夹具 |
| `python -m pytest -q`（`services/audio_storage`） | 12 通过；FastAPI TestClient / httpx 弃用警告 |
| `flutter test test/desktop test/audio_storage` | 29 通过 |
| `flutter test`（完整 App） | 31 通过、1 失败：`test/widget_test.dart` 原有手机 App smoke fixture 缺少 Riverpod `ProviderScope`，随后标题断言失败；本次未改动该测试或手机 App |
| `flutter build macos --debug -t lib/desktop_main.dart` | 成功，未安装或启动；插件迁移和上游 API 有弃用警告 |
| `scripts/verify-macos-bundle.py` + `codesign --verify --deep --strict` | 47 个 Mach-O，0 外部依赖错误；本地签名校验通过，不等于 Apple 公证 |
| `python3 -m unittest discover -s scripts/tests -p 'test_*.py'` | 2 通过，检查原生依赖验证器 |

HTTPS 负向用例包含错误 CA、错误证书及中途断开；日志中的 TLS 拒绝及断开客户端后的响应写入异常属于这些测试场景，不能据此宣称设备网络长期稳定。

## 实际 HTTP 与音频内容

运行 `services/audio_storage/verify_live.py`，使用本工作区忽略的 `artifacts/verification-data`，动态空闲 loopback 端口；没有访问日常使用的 8765 服务。

六份输入：WAV、M4A、MP3、Ogg、101 MiB WAV、1 GiB WAV。所有用例均通过：分片上传、重复首片、完成查询、HEAD 长度、Range 断点下载、SHA-256 完整比对、FFmpeg 全文件解码、认证 HTTP seek 解码。大文件上传中杀死测试服务进程，再启动并恢复；服务重启后列表保留。观测到服务峰值 RSS 55.41 MiB，仅代表本机本轮采样。

Dart 客户端六份音频的上传、下载、恢复后哈希、重复上传去重全部通过；桌面自动备份队列 → 实际 HTTP → 服务端哈希 → 队列重载防重复验证通过。测试复用现有 `tool/verify_audio_http.dart` 和 `tool/verify_desktop_backup.dart`；测试副本只将固定 8765 地址替换成隔离服务动态端口，并指向上述夹具目录，未改 App 运行时代码。测试产物、令牌和原始日志不入库。

## 本轮未验收

- 没有安装/启动本分支 App，没有新做麦克风权限或扬声器听感验证；音频解码成功不能替代真人听音。
- 没有固件交叉编译、刷机、物理 Clip BLE/STA/TLS 联调或长时间稳定性验证。
- 没有运行 AI 模型、实现直传标准入库桥接、制作 DMG、签名公证、打 tag、上传 Release 或部署。
- 历史 Beta 3 安装、麦克风验收保留为来源文档，不计入本次结果。

## 独立审查与收尾

独立只读审查覆盖迁移提交、代码树保留、配置/忽略规则、启动说明、原生构建和 HTTP 报告，未发现 Critical / Important / Minor 集成问题。审查另行复核了 47 个 Mach-O 的依赖与本地签名。结论仅为可保留本地集成分支。

本次明确保留的验收边界及后续风险：

1. 物理 Clip BLE/STA/TLS、固件交叉编译及长时间运行未验收；代码未改不代表硬件兼容性已通过。
2. 新构建未安装/启动，麦克风授权、听感与既有数据迁移未验收；实际使用仍可能遇到权限或迁移问题。
3. 原始录音归属、转换、入库和 AI 运行时尚未实现；直传文件目前不会自动成为 App 可处理内容。
4. 公证、分发、部署不在本轮；本地签名校验通过不能避免未来安装时的 Gatekeeper 限制。
5. 手机端旧 smoke fixture 保持原样；完整 App 测试仍有 1 项失败，后续应单独修复。

原分支未重写。所有改动提交到本地 `boa/desktop-https-integration`，未推送远程、未合并到其他分支、未创建发行物。工作区保留供后续开发。
