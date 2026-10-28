# Boa 产品设计

当前实现和使用入口：[产品总览](../product/boa-voice-overview.md)、[Server](../../server/boa/README.md)、[网页](../../server/web/README.md)、[Roger 基础与可选扩展](../contracts/roger-base-extension-v1.md)。设计稿中的日期和状态仅描述相应版本；软件测试、固件编译和实体设备验收分别记录。

## 当前产品边界

- [Clip 用户绑定与自动覆盖](2026-10-28-clip-user-binding-design.md)：完整 UID、持久配置、凭证隔离、解绑与换绑。
- [桌面原生 Wi-Fi 配网](2026-10-28-desktop-wifi-design.md)：桌面扫描，网页保留手动配网；替代旧网页回环扫描方案。
- [网页默认 Server](2026-10-27-web-default-server-design.md)、[开发 ID 登录](2026-10-27-web-id-session-design.md)：同源发现、登录身份及会话切换。
- [网页录音列表与播放](2026-10-27-web-recordings-chrome-design.md)：按用户查询、下载校验及浏览器播放。

## 后续规划与历史设计背景

- [模块与协议设计](2026-10-21-boa-voice-module-protocol-design.md)：完整模块规划，AI 等部分仍是目标协议。
- [固件管理设计](2026-10-22-firmware-management-design.md)：完整产品管理流程，需区分已实现路由和草案能力；当前 OTA 采用 Roger 原生实现。
- [早期直传设计](2026-10-22-clip-direct-server-upload-design.md)：保留旧 HTTPS/V2 演进背景；当前实现为 DTLS v3，用户归属和统一文件索引已实现。
