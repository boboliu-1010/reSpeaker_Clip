# Mac 桌面客户端到开发 Server 的 HTTP 测速状态

日期：2026-10-22。目标是验证本 Mac 上桌面端实际使用的 Dart `StorageClient` 与 `bobo@100.58.19.213` 音频 Server 的跨机器 HTTP 上传/下载。

## 当前结论：网络不通，尚无有效吞吐结果

- SSH 登录和文件传输可用，但 `direct-tcpip` 返回 `administratively prohibited`，不能建立访问远端 `127.0.0.1:18765` 的本地隧道。
- 本 Mac 使用**桌面端同一份 `StorageClient`** 对 `http://100.58.19.213:18765` 做连接检查，15.02 秒后 `SocketException: HTTP connection timed out`，没有进入上传/下载阶段。该检查使用无效的非敏感探测凭据，没有发送正式服务令牌。
- 额外临时探测只绑定服务端私有接口 `10.180.1.219:18766`，只接受私有来源的随机标记 GET，不接入音频库、不读取用户文件。从 Mac 对 `100.58.19.213:18766` 和 `10.180.1.219:18766` 的连接都超时；监听在 16 秒后自动关闭，退出码 0。
- `100.58.19.213` 不是 RFC 1918 私有地址或 100.64/10 共享地址，不能仅凭 100 开头认作私网。后续若提供公网地址，应使用可验证的 HTTPS；SSH 隧道内仍可用现有 loopback HTTP。

**没有测出 Mac/App → HTTP → Server 的真实上传/下载速度。之前 SSH 和服务器内回环的数字不能填作这项指标。**

## 已准备的客户端测速入口

新增 `deploy/benchmarks/desktop_audio_http.dart`，直接导入桌面端既有 `StorageClient`，不复制/修改其实现，不启动 GUI、不修改已安装 App 设置。

该入口会先验证鉴权，再上下行各测三次并报告中位数。每轮使用全新上传会话缓存和下载目录，防止命中本地缓存而测到虚假高速度；校验完整文件长度和 SHA-256。令牌只从指定文件读取，不打印、不写入报告。

指标是**桌面客户端端到端有效吞吐**：上传包含客户端哈希、HTTP 请求和服务完成等待；下载包含传输、写盘和客户端完整性校验。额外独立复核哈希在计时后执行。它反映用户等待时间，不等同于此前排除客户端哈希/合并的分片传输指标。

已用隔离的 Mac loopback 服务验证两项工具行为：

1. 正常凭据：实际上传/下载完成，返回成品和哈希一致，报告为 passed。
2. 错误凭据：HTTP 401，报告为 failed，样本数为 0；不会把鉴权失败或缓存命中冒充测速成功。

这两项只是**测速工具 smoke 验证**，不是远端部署验收，未将本地 smoke 速度列入正式结果。

## 网络开通后运行

优先由管理员按 [开发机说明](server-100.58.19.213.md) 允许 `bobo` 仅本地转发至 `127.0.0.1:18765`，建立隧道并验证。当前 bobo 无免密 sudo，无法代替管理员改系统 SSH 配置。

隧道可用后，在本 Mac 运行以下命令；若提供另一个可达 HTTPS 根地址，则替换首个参数：

```sh
cd /Users/bobo/code/respeaker-boa-integration/mobile/app
dart --packages=.dart_tool/package_config.json \
  ../../deploy/benchmarks/desktop_audio_http.dart \
  http://127.0.0.1:18765 \
  "$HOME/.config/boa-voice/development-100.58.19.213.token" \
  ../../services/audio_storage/artifacts/tone-101MiB.wav \
  "$HOME/.cache/boa-voice/desktop-http/remote" 3
```

示例依赖此前生成的合成 WAV 和本机受保护凭据文件；换机器需自行准备测试音频和凭据。实际运行会新增 3 个带 `desktop-http-` 前缀的测试录音；当前还未在远端运行这一正式测速。工具不会自动修改端口、SSH、模型、录音或 App 配置。

## 证据

- [Mac Dart 客户端连接结果](evidence/2026-10-22-desktop-http-client-probe.json)
- [无凭据的临时网络探测](evidence/2026-10-22-desktop-http-network-probe.json)
- [仅本地工具 smoke 检查](evidence/2026-10-22-desktop-http-tool-check.json)

原有 Server 仍运行，临时 18766 监听已关闭；未改防火墙、SSH 配置、正式应用令牌或安装的 App。

本轮使用的原始 `storage_client.dart` SHA-256：`5b2d866acca3a3450a6a922b8dbcd981eb15aa160caf4fe9b57080ad77e0ccb0`，与来源版本一致。
