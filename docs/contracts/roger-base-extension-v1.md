# Roger 基础与 Boa 扩展约定

**v0.1｜2026-10-26｜设计稿。** 配套 [设备与文件功能](../product/boa-voice-overview.md)。

## 1. 基础与扩展层

| 层 | 当前来源 / 建议目录 | 职责 |
| --- | --- | --- |
| Roger 固件基础 | `applications/clip/` | 录音、BLE 控制、STA 联网、HTTPS 上传和设备侧续传状态 |
| Roger Server 基础 | `tools/https_poc/server.py`、`resume_store.py` 及原依赖 | V2 解析、设备身份检查、分块校验、检查点、原始文件提交与回执 |
| Boa Server 扩展 | 建议新增 `services/boa_server/` | 单一 HTTPS 服务入口、用户/设备绑定、Roger 请求适配、文件索引、列表 API |
| Boa App | 现有 Flutter App | 设备连接/控制、文件列表与已有本地录音上传 |

当前固定来源为 `cfff60539d94c6d3e43f788592b97a76547278fe`；基础目录按该提交原样引用。新增实现、测试和部署配置放在 Boa 扩展目录。升级 Roger 基础时显式调整版本并跑兼容回归。

## 2. 同一个服务如何复用基础

App 和 Clip 使用同一个 SERVER_URL。Boa 启动入口负责 TLS、路由和生命周期，以 Roger 的 Receiver/Handler 为基础，通过新增子类/适配器扩展。BoaReceiver 初始化基础 Receiver 后，将自身 RequestHandlerClass 设为 BoaHandler，再开始接收请求；扩展代码不修改基础模块的全局 Handler：

- `/v2/devices/...`：进入 Roger Handler 的接收流程，复用 ResumeStore 的校验、续传、落盘及回执。
- `/api/audio/...`：通过进程内 ASGI 桥接复用现有音频服务，保持已有请求/响应；事件循环只在 Boa 启动时创建并随服务关闭，正文按有界缓冲流式转发。外层先校验当前用户与上传/文件 owner，再用服务内凭据调用旧服务；内部凭据只在服务内使用。
- `/api/boa/v1/audio-files`：由 Boa 扩展读取统一文件索引，按用户过滤返回。

对外一个服务地址，扩展入口统一启动和关闭所有组件。App 路径由适配器按明确路由表接管；基础 V1/V2 设备路径按基础匹配规则复用设备上下文。其他路径返回原协议的未匹配结果。文件接收、业务索引与列表是同一服务内的模块。

Roger Handler 当前从 `self.server` 读取固定 device/token/directory/resume。扩展层先验证设备凭据与绑定，再为**每次请求**构造独立上下文视图，提供匹配的 device、token、私有目录、commit_lock 和 ResumeStore；其余服务器属性委托给原 Receiver。基础 Handler 在此视图上运行。视图中的 token 只使用本次已通过外层认证的请求凭据，绑定与目录来自受信注册表；共享 Receiver 的这些字段保持固定，避免并发请求串用其他用户身份。

每个绑定命名空间共享同一份 commit_lock 和 ResumeStore，V1/V2 共同使用该锁；每个请求视图引用它们，避免为并发请求重复创建存储锁。

上下文有效期覆盖本次完整 HTTP 请求。长连接的下一次请求重新认证和选择上下文；索引操作始终使用接收开始时保存的归属快照。目录由受信绑定 ID/代数生成；每次换绑使用新的目录和 ResumeStore 命名空间，保留 Roger 原 object_id 算法及 `.partial/.checkpoint/.bin` 布局。

## 3. 归属、文件可见与恢复

在扩展目录保存 SQLite 索引，索引与 Roger 的原始目录各有明确写入边界。最小记录：

```text
file_id, owner_user_id, source: app_upload|clip_direct,
source_key, binding_epoch?, device_id?, session?, segment?,
expected_size, expected_sha256, private_object_ref,
created, filename, state: receiving|ready
```

- App 来源键为原上传 ID；Clip 来源键为 `(device_id,binding_epoch,session,segment)`；各自唯一。
- 首个合法请求先持久化来源、预计大小/SHA 和 owner，再交基础接收文件。重复请求校验同来源身份；不同内容冲突。
- 接收适配器观察基础的 stored 回执，在新增钩子登记 ready；回执字段、状态码和正文沿用 Roger 基础。索引更新失败时保留 receiving 记录和安全诊断，stored 仍表示原始字节已经完成基础校验。
- Boa 启动时及运行中定期对账已登记的 receiving 记录：使用记录保存的私有对象引用核对完整 `.bin`、长度和 SHA，再发布 ready。恢复扫描由同一服务内的轻量任务执行；不依赖 App 在线。
- App 创建上传时先调用旧服务取得上传 ID，再固定 owner/来源索引，最后向 App 返回 ID；后续分片与查询先校验这份归属。创建后、索引前崩溃的空会话按旧过期规则回收，不能凭该 ID 接收私有字节。
- App 上传完成事件采用相同规则：complete 文件满足长度/SHA 后登记 ready；启动对账补偿“文件已提交、索引未完成”。
- 列表只返回 ready 的本人记录。原 `/api/audio/recordings` 列表同样先按归属过滤再分页；单条 metadata、content、HEAD/Range 与上传查询/取消逐项检查 owner，不能把旧共享 token 接口直接暴露给所有业务用户。校验未完成时维持 receiving；存储错误保留来源供排障，不伪造成功记录。

先持久化来源失败时拒绝进入接收，避免留下无法追溯归属的新原件。历史散落文件由开发者结合受信设备记录核实后登记；文件名哈希本身不是归属证明。

## 4. 用户与设备边界

用户凭据映射 user_id；设备凭据映射 device_id、owner_user_id 和 binding_epoch。开发者通过受控 CLI 登记、撤销与换绑。用户列表从身份取 owner，设备路径必须匹配凭据中的 device。

接收创建时固定 owner 和 binding_epoch；重启、重传、设备后续换绑均沿原记录核实。换绑前由开发者核清设备未上传录音、结束旧上传并撤销旧凭据，新绑定使用新的凭据和存储命名空间。

BLE 连接用于附近控制；网络配置和上传配置沿 Roger 当前 USB 命令。App/设备持有各自凭据，Server 保留身份映射；日志与文件列表使用脱敏元数据。

## 5. 接口兼容与验收

| 验收项 | 要求 |
| --- | --- |
| 基础来源 | Roger 基础目录相对固定提交无修改；新增逻辑位于 Boa 层 |
| V2 协议 | 原 GET/PUT、header、8 MiB/16 KiB 限制、partial/stored 回执、keep-alive 规则继续通过基础测试 |
| 同一入口 | App 上传、Clip 直传、本人文件查询使用同一个 SERVER_URL |
| 并发隔离 | 两设备/用户并发、长连接连续请求、错误 token 和路径设备不符均正确隔离 |
| 重传与重启 | 同来源无重复，断块/回执丢失/接收与索引间崩溃后可恢复查询 |
| 设备功能 | BLE 连接、VERSION/GSTAT、START/STOP，以及 USB NETCFG/UPLOADCFG/UPLOADSAVE/UPLOADAUTO 的实际配置与状态分别记录真机证据 |

上述为实施依据和验收条件；当前新增目录、适配器、归属索引及列表仍为设计。
