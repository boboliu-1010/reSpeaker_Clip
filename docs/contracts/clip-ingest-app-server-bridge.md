# Clip 实验直传与 Boa App / Server 接入契约

**职责与隔离以 [统一总览](../product/boa-voice-overview.md) 为准。** 本文 owner_id 对应统一用户身份 owner_user_id；设备凭据须经有效绑定确定归属，后台解码/发布继承该归属。未绑定片段不能自动归入任意用户；共享实验 token 尚不是多用户方案。

**版本：0.2 评审草案｜日期：2026-10-22｜状态：接入方案未实现。**

本稿以 BofAI `experiment/https-runtime-0.1.2` 的 **`cfff60539d94c6d3e43f788592b97a76547278fe`** 为实验实现基线。已有设备直传不从零重写；本稿定义它如何作为同一个 Boa Server 的接收模块进入音频库和 AI 流程；“桥接”指内部格式/数据接口适配，不是另建一套 Server。现有代码、仓库实测记录和计划新增功能分开标记。

配套：[已实现/待补对照](../superpowers/specs/2026-10-22-clip-direct-server-upload-design.md)、[音频 HTTP v1](storage-http-v1.md)、[AI HTTP v1 草案](ai-http-v1.md)。本轮只更新文档，不部署接收服务、不更改设备配置、不刷机。

## 1. 当前三套接口不能只靠换地址互通

| 边界 | 现有/规划接口 | 实际语义 |
| --- | --- | --- |
| 已有实验设备上传 | GET/PUT `/v2/devices/{device}/recordings/{session}/{segment}` | 8 MiB 以内的单个原始 Opus 片段，16 KiB 续传块，返回原始字节落盘回执 |
| 已有 Boa App ↔ 存储 | `/api/audio/uploads`、`/api/audio/recordings` 及 content | 标准音频文件、32 位 hex recording_id、SHA/长度与 Range 下载 |
| 尚未实现的 Boa AI | `/api/boa/v1/transcriptions`、summaries、jobs、results | 以标准音频 recording_id + SHA 建立转写/摘要任务，模型在服务端执行 |

**推荐：服务端增加兼容接收适配器和转换入库模块，保留设备 V2 路径/回执；App 继续读取标准音频接口。** `/api/boa/device/v1` 是旧方案提出的未来新协议，不是实验固件已使用的接口，首期不强迫设备切换。

整合方式确定为“同一个 Boa Server 内的设备路由 + 持久处理 Worker + 音频库内部发布接口”，统一对外根地址、身份归属与音频目录。当前同一开发机的 9527/9528 进程只是过渡部署，不保留为两套产品 Server。复用实验 ResumeStore 的校验/续传规则，不能直接把测试用 ThreadingHTTPServer 当成生产模块嵌入事件循环。后台 Worker 可独立运行进程，但仍属于同一 Server，不形成第二套用户服务或身份体系。

当前 FastAPI 中间件对所有请求校验同一个用户存储 token，**新增 router 本身并不足以接通**。需要按已注册的路由边界分别校验 V2 设备身份和 `/api/audio`/用户 API 身份，再将受信 principal 传入用例；不能直接全局放行 `/v2`，也不能使设备 token 获得用户音频库权限。旧用户 token 的行为保持兼容。

## 2. 已实现 V2 协议基线（保持兼容）

| 项目 | `cfff605` 的行为 |
| --- | --- |
| 路径身份 | device 为 1..32 个字母/数字/下划线/短横线；session 为 14 位数字；segment 为正整数、最多 9 位；不是 capture UUID |
| 身份认证 | 配置的单设备 Bearer token + 接收端预期 device；当前不是多用户设备注册系统 |
| GET/PUT 共用头 | X-Recording-Size（整个片段字节数）、X-Content-SHA256（整个片段 SHA-256）；Authorization |
| PUT 专用 | Content-Length、Upload-Offset、X-Chunk-SHA256；请求体为本块原始字节；禁止 Transfer-Encoding |
| 大小/偏移 | 单片段最大 8 MiB，每块最多 16 KiB；设备用 2 KiB 缓冲流式发送；块 offset 按接收端持久检查点推进 |
| 回执字段 | status=partial/stored、size、sha256、offset；设备核对四个字段；不是 recording_id 或 canonical_ref |
| 文件发布 | 校验整片段哈希后 `.partial` 原子发布为 `.bin`，同步文件/目录并清理 checkpoint；同身份不同内容冲突 |
| 连接复用 | 自动上传携带 X-Clip-Batch: 1；完整文件之间可 keep-alive；头部与小 JSON 回执合并写出 |

接入后，上述状态码、GET 对账、重复块/冲突处理和回执字段保持。不得把“原始片段已保存”的 stored 改成“等待转码”的新枚举，也不能要求旧设备解析新的任务对象。参数非法、哈希错误、截断、接收端重启和回执丢失的回归必须重跑。

## 3. 数据身份与落盘事件：先解决可追溯性

现接收端 `.bin` 文件名是 device/session/segment 路径哈希，**不能从文件名反推出设备和会话**；现 V2 请求也没有声道、采样率、模式、总片段数、停止标记或 session manifest。因此不能只写一个“扫描目录并导入所有 .bin”的脚本就宣称接通。

建议新增服务端持久 `SourceRecord`：

```text
source_id: UUID
owner_id: 服务端身份
receiver_id / binding_epoch: 服务端注册的接收实例及绑定代数
device_id / device_session / segment: 当前 V2 路径中的源身份
raw_size / raw_sha256 / raw_object_ref: 不可变字节身份与私有对象引用
decoder_profile_id / revision: 可缺失，缺失则等待元数据
audio_metadata: channels, sample_rate_hz, mode, frame_format；可缺失
state / sequence / canonical_ref / safe_error
created_at / received_at（原始片段完整提交前为 null） / updated_at
```

- owner、receiver、binding_epoch 由受信 Server 配置/鉴权确定，不能由设备填字段抢占其他用户。当前单用户部署可绑定固定 personal owner；不因此宣称已有多租户隔离。
- 路径源键在绑定实例内唯一；同源相同 raw_size/raw_sha 返回原记录，同源不同内容为冲突，禁止覆盖。session 时间命名可能重复，首期冲突需人工处理；未来 capture UUID 需新协议。
- 接收首个合法请求时先持久化源身份与声明的 raw 字节信息，再接收/确认数据。原始文件完整提交后，持久化 raw_stored 状态和处理事件，再回原有 stored。转换不在 HTTP 回执等待路径执行。
- 原件提交、事件状态和 SQL 不是同一原子操作：用持久状态机与扫描 SourceRecord 对账。原件已发布、事件未提交时可补记；事件在原件未验证时不得转码；不能靠扫描不带元数据的文件名重建归属。
- GET 已完成片段也需补齐幂等源索引/事件后返回原回执，覆盖“原件已保存但响应/事件写入失败”。恢复事件不要求设备重传完整字节。
- 接收侧和标准音频库目录分开，旧存储启动清理不能误删原始 `.partial/.bin`。日志/事件不包含 token、密码、音频字节或转写正文。

## 4. 解码元数据与录音粒度

### 首期：片段可见，完整会话合并另立协议

保留 V2 的**一个片段 → 一个标准 recording_id**。App 标题可展示“Clip / 会话 / 第 N 段”，不要将某片上传成功显示成“整场录音完整”。现有 V2 没有总片数/会话结束清单，不能用短时间没有新文件推断完整，也不能盲目拼接编号连续文件。

声道/采样率/录音模式的来源有两种受控方式，均为待补：

1. **受控联调阶段：**服务端给已确认的设备/固件配置绑定明确、版本化 decoder profile；操作者通过已有 USB/设备元数据核对。只接经确认符合该 profile 的测试录音，不能默认所有历史片段都为同一声道/模式。
2. **产品阶段：**新增会话元数据上报，将 session.json 必需字段、封口状态、片段列表/长度/哈希绑定到同一 capture；定义 Schema、认证、版本、重传与大小上限。当前固件/接收端没有这个接口，需后续固件 + SDK + Server 协议扩展。

仅凭 Opus 扩展名、字节数或 `session` 字符串不得猜元数据。元数据不足进入 awaiting_metadata，原始上传回执仍为 stored，App 显示“已上传，待补录音信息”，不标为可播放。

封装/解码由 Server Worker 负责：验证 u16LE packet 长度、尾包、实际可解码性、声道、采样率和时长，资源有界。保留原始文件，生成标准 WAV（首期保持已确认的原采样率/声道，不静默混音或重采样）；供 ASR 的适配转换由 AI Worker 按选定模型处理。失败保留来源与安全错误，不伪造可播放文件。

整场合并未来必须有显式 manifest/关闭标记，校验缺段与顺序后生成独立 canonical rendition，并保留每段溯源；不得覆盖旧片段 recording_id 或偷偷替换内容哈希。

## 5. 标准音频发布：让当前 App 真正看得见

**不能**直接将 `.bin` 搬到 `services/audio_storage/files`，也不能在同一 Server 的接收模块里随意 INSERT uploads。标准库只通过它自己拥有的发布接口写元数据和字节。

建议新增内部接口（不是现有 HTTP API）：

```text
LibraryPublisher.publishVerified(import_key, verified_standard_audio, provenance)
  -> {recording_id, sha256, mime, size_bytes}
import_key = source_id + decoder_profile_revision + conversion_revision
```

Publish 模块与当前 Store 在同一服务/单数据目录的受控写入边界执行。为 import_key 建唯一约束和发布日志：分配/保存稳定 recording_id → 生成并 fsync 私有暂存 → 原子发布字节 → 同一数据库事务提交 complete 录音记录与 import_key 映射。崩溃后对账同一 id，未提交记录不可被标准清单读出；遗留文件按日志恢复，不能重新建第二份可见录音。

同 import_key 再发布时须比较标准文件 hash/size 与转换版本；一致返回已有引用，不一致报冲突，不能以“幂等”为由覆盖已发布文件。

该接口需新增实现/迁移/测试，当前 Store 只有上传 create/finalize 等流程。若改走旧 HTTP 上传接口，其创建 POST 没有服务端幂等键，不能据此承诺桥接 exactly-once；必须另补发布/对账协议后再选该方案。

标准音频入库后，已有接口可复用：

| App 操作 | 接入方式 |
| --- | --- |
| 看到远程录音 | 原 GET `/api/audio/recordings` 返回新增的 complete 标准音频记录 |
| 下载/播放 | 原 GET/HEAD content、Range/ETag、SHA 校验 → LocalLibrary 导入 → 本地播放器 |
| 区分来源 | 新增查询 provenance，关联 device/session/segment/raw_sha/canonical_sha，不在原文件名里藏机器可解析协议 |
| 防重复备份 | 已下载标准音频可按同目标 SHA + size 识别副本；不得用 raw SHA 对比 WAV SHA |
| 状态展示 | 原清单只显示 complete；未完成的接收/转码状态用新增 device-ingests 视图，不能塞进现有上传 state 枚举 |

原始 SHA 和标准 WAV SHA 不同。canonical_ref 绑定最终 recording_id/sha256，后续转写必须使用 canonical 的值。未来重新转换产生新 rendition/引用，不能改变已发布 recording_id 的字节。

上述现成清单/下载行为指 **Boa 桌面入口及共享 StorageClient**。原完整手机客户端业务仍调用另一套 `/api/v1` 账号/OSS/ASR 接口，尚未接到 `/api/audio`；手机端需通过 Storage/Jobs 适配器与服务配置接入，不能仅替换 base URL 或复制桌面按钮就视为完成。建议先用桌面验证接收→入库→播放，再复用核心适配到 iOS/Android，分别验收。

## 6. App 与 Server 新增的最小查询契约（草案）

建议新增用户身份接口：

| 路径 | 用途/语义 |
| --- | --- |
| GET `/api/boa/v1/device-ingests` | 按设备/状态筛选接收与处理记录；created_at DESC + source_id DESC，limit 默认 50、最大 100；不透明 cursor 绑定身份/筛选/顺序，有效 24h，非法/过期 422 |
| GET `/api/boa/v1/device-ingests/{source_id}` | SourceView 完整快照，含 sequence；查询断网不重建上传或转码 |
| POST `/api/boa/v1/device-ingests/{source_id}/retry` | 只重试失败的服务端转换/发布；有效输入和 profile 才接受；Idempotency-Key 必填；不要求设备再上传 |
| GET `/api/boa/v1/audio-provenance/{recording_id}` | 读取标准音频的来源、raw/转换版本与设备/片段关联；不返回私有文件路径或凭据 |

这些路由**尚未实现**。SourceView 至少含 source_id、device_id、session、segment、state、sequence、created_at、received_at（可 null）、updated_at、canonical_ref（可 null）、safe_error（可 null）、decoder_profile_ref（可 null）；created_at 是首次合法请求建记录的 Server UTC 时间。查询不到/越权统一 404。列表响应为 `{items,next_cursor}`；分页水位固定，状态反映读取时当前值，按 source_id 去重并定期从首页刷新，不宣称历史状态快照。

状态为 `receiving → raw_stored → awaiting_metadata|converting → publishing → ready`，转换/发布可转 failed；ready 必须对应已可下载的标准库 complete 记录。retry 的 body 为 `{}`，对 ready 返回 200 原快照，不重新转换；对运行中返回 200 当前快照；对 awaiting_metadata 返回 409 METADATA_REQUIRED；对 failed 受理后返回 202 快照，重复 key 返回原受理结果，不新建并发 worker。重试沿用固定 decoder profile/revision；换解码配置须显式形成新 conversion_revision，不暗改旧 rendition。

权限按 authenticated owner 校验；初期单用户沿用存储 token 的 personal 身份，未来细分 ingest.read/ingest.process/audio.read。设备 token 仅访问 V2 自己的资源，不能访问此用户 API、音频清单或 AI 模型档案。错误格式/请求 ID/幂等规则沿用 AI HTTP v1 公共约定；具体 Schema 与正反例需在实施计划前冻结。

App 第一阶段只增加：接收状态页、provenance、手动刷新/转换重试入口。设置页明确“当前固件需要 USB 配网”；不要先做可点击但不起作用的手机配网开关。连接时可通过已认证的 GET device-ingests?limit=1 探测：200 表示入口可用，404/501 表示未提供，401/403 是认证/权限问题，网络错误为未知；不能都归为“不支持”。缺能力时已有音频下载/播放仍工作；App 不能因为固件自报版本就假定 Server 已支持桥接。

## 7. 转写与摘要如何接上

```text
设备 V2 stored（原始片段已保存）
  → SourceRecord/outbox → 元数据校验/解码 → 标准库 complete
  → App 取 canonical_ref → 用户确认数据发送及模型 profile/revision
  → AI HTTP v1 POST transcriptions → Job/result
  → POST summaries（固定转写版本/模板）→ App 展示/缓存
```

AI HTTP v1 全部仍是待实现协议；本次不把实验直传当成 AI 已开发。首期用户显式触发，原始上传 stored 不启动计费任务。设备中不放模型密钥，模型 endpoint/凭据仍在 Server。

未来自动处理需增加服务端流水线：用户许可/模型及模板快照、预算、`source_id + canonical_sha + pipeline_revision` 幂等键、恢复/取消与失败阶段。不能靠 App 常驻观察完成事件触发后台“自动”任务，否则 App 退出后流程断裂。

## 8. 配置迁移与固件差距

- 当前 Boa 启动脚本默认本机 HTTP，设备实验要求 HTTPS。部署须增加符合设备 CA/主机名校验的 TLS 入口，再转发隔离的 V2/用户路由；保留鉴权、Content-Length、16 KiB 请求体及正确回执，验证代理超时/keep-alive，不以本机 HTTP 能用推断设备能连。
- 历史 receiver 目录没有 SourceRecord，不能从散落 .bin 反推身份。迁移需结合受信设备配置与设备上传清单/已有证据建立 device/session/segment/raw_sha 映射，再验证文件；缺映射的数据先保留待核对，不自动归给当前用户或删除。
- 初期保留 USB NETCFG/UPLOADCFG/UPLOADSAVE/UPLOADAUTO 控制。实验构建关闭 AP/USB MSC，不能承诺现有 App 的 Wi-Fi 下载页在同一镜像上可用；BLE 控制也需按实际构建逐项验收。
- 新 Server 必须兼容旧设备信任的 CA、主机名和 V2 路径；若改 host/port/CA，设备指纹会变，旧 uploaded 标记不保证当前目标已有副本，需要重新对账。
- 当前指纹不含账号身份/绑定代数，换 token 不改变目标。首期不支持同 origin 靠换 token 安全转让设备；单设备接收实例/静态 owner 映射和将来的云端绑定是两回事。
- 当前凭据保存为 LittleFS 中带 CRC 的配置，不是加密；配置和清除仅 USB。出厂重置是否同时清除 https/config、设备登记/吊销/轮换、App 加密配网仍须专项补齐，不以旧 FACTORY 注释代替验证。
- 当前 SNTP 未认证，信任 CA 编译进固件。正式证书轮换、可信时间与时钟异常、设备丢失/凭据泄露处理需要产品方案；开发 CA 的历史有效期不能视为当前线上仍可用。

## 9. 分阶段接入与验收

| 阶段 | 计划工作 | 可验收结果 |
| --- | --- | --- |
| I0 固定基线 | 记录实验 firmware/receiver/CA/配置版本，归档真实部署 profile；不盲刷分区 | 源码、镜像、配置与证据对应，保留旧固件/存储布局回退说明 |
| I1 兼容接收与索引 | 同服务 V2 router、限权身份、SourceRecord、持久事件与重启对账 | 旧设备 16 KiB 续传、重复块、丢失回执继续通过；归属/原始 SHA 可追溯 |
| I2 标准化与发布 | decoder profile、原始帧校验、持久转换队列、幂等 LibraryPublisher | 同源只发布一份指定 rendition；下载与转换 SHA 一致，可解码播放；缺元数据明确等待 |
| I3 App 对接 | 原清单/Range 下载/离线播放、来源状态页/重试 | 手机/Mac 不在线时设备也可上传；之后 App 只连 Server 即可取到已入库内容 |
| I4 AI 接入 | 按 AI HTTP v1 实现配置、转写、摘要及用户授权 | 标准 recording_id → 转写 → 摘要，模型 endpoint 可配置；App 重启可恢复查询 |
| I5 设备产品化 | App 配网、绑定/轮换/清除、证书时间、AP/MSC 策略和发布集成 | 实验能力进入明确的发布矩阵；不能因 main/release 分支名推断包含直传 |

所有阶段均未在本轮执行。关键回归：receiver 返回 stored 后立即重启；原件已提交但事件未提交；转换中断；发布字节后数据库提交前崩溃；缺元数据/损坏 Opus；重复 source、目标切换/越权；标准下载 Range/hash/播放；长录音多段不可误合并；AI 重复提交/未知外发不能重复计费。实际断电、长期稳定、功耗与 TLS 偶发超时仍需真机专项验证。

## 10. 实现依据

- [实验接收端](https://github.com/BofAI/reSpeaker_Clip/blob/cfff60539d94c6d3e43f788592b97a76547278fe/tools/https_poc/server.py)、[持久续传](https://github.com/BofAI/reSpeaker_Clip/blob/cfff60539d94c6d3e43f788592b97a76547278fe/tools/https_poc/resume_store.py)、[设备请求/配置](https://github.com/BofAI/reSpeaker_Clip/blob/cfff60539d94c6d3e43f788592b97a76547278fe/applications/clip/src/https_poc.c)。
- 本地 Boa [存储 API](../../services/audio_storage/app.py)、[Store](../../services/audio_storage/store.py)、[客户端](../../mobile/app/lib/src/features/audio_storage/storage_client.dart)、[桌面音频页](../../mobile/app/lib/src/features/desktop/desktop_page.dart)。这些源码不因本设计而变化，也不能把实验 receiver 与当前 Store 视为同一实现。
