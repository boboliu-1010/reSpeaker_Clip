# 固件管理接口契约

**版本：1.0.0-draft.2｜日期：2026-10-22｜状态：按已确认方向修订，未实现，工程验收条件未完成。**

本版已纳入 [调整清单](../product/firmware-management-review.md) A-01～A-08：独立 start/cancel/resolve、设备登记、授权范围更新、profile/策略管理、状态和租约边界。对应 [产品与模块设计](../superpowers/specs/2026-10-22-firmware-management-design.md)。**这里的固件 API 尚未部署；现有 `/api/audio` 不变。**

## 1. Endpoint 与传输协议

| 项目 | 约定 |
| --- | --- |
| App 配置 | Server 根地址，例如 `https://100.58.19.213:9528`；这是开发地址示例，不是固件 API 已可用的声明 |
| 固件 API 前缀 | 固定 `/api/boa/v1/firmware`，由客户端追加，用户不填写完整接口路径 |
| 音频 API | 保留 `/api/audio`，固件不进入录音列表，不复用音频上传会话 |
| 元数据 | HTTPS + JSON；JSON 请求/响应为 UTF-8，首版元数据请求体上限 1 MiB |
| 固件正文 | `application/octet-stream`，流式 PUT/GET；GET/HEAD 支持单段 Range、If-Range、长度和 SHA ETag |
| 鉴权 | `Authorization: Bearer <firmware-token>`，独立固件凭据；音频 token 默认无固件权限 |
| 能力检查 | `GET /api/boa/v1/firmware/capabilities`，返回 server_id、协议版本、角色、范围、策略修订与限制 |

根地址只允许 HTTPS、非空主机及可选端口；禁止 userinfo、查询、fragment 和非根路径，规范化末尾 `/`。远程地址必须验证 TLS 链与主机名；开发证书只能显式配置受信证书，不关闭验证。首连时凭据仅发送到用户指定并绑定的 origin；能力响应的 server_id 与规范化 origin 一并保存，server_id 是持久服务标识，不替代 TLS 身份验证。

同一 Server 可同时部署音频和固件服务，两者分别验证协议与凭据。404 表示固件能力不可用，不能当作全部支持；失败不回退官方云，不跟随重定向发送凭据。Server 不接收任意下载 URL 代替制品 ID，也不充当无约束代理。

`FirmwareServiceProfile = {service_profile_id, endpoint, protocol_kind: boa_firmware_v1, credential_ref, expected_server_id?, revision}`。首次能力检查后绑定 server_id；之后不匹配则停止新请求并标记 server_identity_changed。改变 endpoint/origin/身份创建新的目标修订，旧授权、任务、缓存不自动迁移到新目标，旧 token 不自动发给新地址。若旧目标有活跃升级，保留其快照/只读镜像 lease 直到完成或人工恢复。

## 2. 标识、角色与资源范围

- package_id、upload_id、release_id、upgrade_id、principal_id、device_ref、profile_id、policy_revision 均为 Server 分配的不透明 UUID，各自独立；operation_id 是 App 为一次动作生成并持久化的 UUID。时间为 UTC RFC3339，大小为字节，SHA-256 为 64 位小写 hex。
- 固件角色为 viewer、operator、admin。admin 管理该固件服务；operator 可为其授权 device_refs/profile_ids 申请升级；viewer 只能读取/下载授权 profile 的已发布版本。非 admin 的设备和 profile 范围取主体 grants 与设备 allowed_profile_ids 的交集。
- 缺/失效凭据 401；动作无权 403；不可见资源 404。隐藏 UI 不代替 Server 每次检查。App 不获得签名私钥，不在日志、普通偏好或导出中保存 token。
- 首个 admin 由受控 Server CLI 初始化；之后在 App 管理设备、主体、授权和策略。CLI 保留凭据遗失等恢复用途，不提供匿名 bootstrap API。Server 仅存高熵 token 的校验摘要；创建/轮换返回的明文只展示一次。
- 保留至少一个有效 admin；禁止普通主体扩大自己的角色/范围。admin 的创建、授权、撤销和策略修改均审计，不将旧音频 token 自动升级为管理员。
- device_ref 是逻辑设备身份；本机 BLE remoteId 不作为跨平台稳定设备 ID。登记时记录身份来源和核实级别，硬件能力未核实前仅现场手动核对，不宣称设备身份已通过加密认证。

## 3. 模块接口与职责

| 提供方 | 领域接口 | 必须满足的行为 |
| --- | --- | --- |
| FirmwareCatalogPort | `capabilities()` / `listReleases(filter)` / `getRelease(id)` / `checkCompatibility(device, release)` | 只返回可见资源；unknown 不等于兼容 |
| FirmwarePublisherPort | `beginImport(metadata, op)` / `putContent(upload, bytes)` / `completeImport(upload, op)` / `publish(package, policy, op)` / `withdraw(release, op)` | 隔离校验后发布；字节和发布快照不可覆盖 |
| FirmwareAdministrationPort | `registerDevice()` / `updateDevice()` / `updateGrants()` / `createProfile()` / `revisePolicy()` | admin 专用、修订检查、审计；不提供任意 shell/AT 命令 |
| FirmwareCachePort | `fetch(release, progress)` / `verify(ref)` / `evict(ref)` | 按 server_id、principal、package_id、SHA 隔离；校验后原子发布缓存，活跃升级持有读取 lease |
| FirmwareAuthorizationPort | `authorize(device, release, op)` / `start(id, preflight, op)` / `cancel(id, reason, op)` / `resolve(id, evidence, op)` | 授权、开始许可、取消、结果核实各自明确；HTTP 成功不等于设备已执行 |
| DeviceUpdatePort | `preflight(device, release)` / `start(lease, permit, op)` / `observe(id)` / `reconcile(id)` | 获取本机设备独占锁，BLE SMP 执行；先观察再恢复，不自动重放写命令 |
| FirmwareAuditPort | `appendEvent(id, sequence, evidence)` / `listHistory(filter)` | 事件可幂等补报，不签发开始许可、不强制解锁；保留 App 声明与设备观测来源 |

Server 保存目录、策略、授权、租约和审计，不替 App 连接蓝牙。App UI 只依赖这些接口，不自行拼接 BLE、HTTP 或文件写入。设备执行镜像接收/启动验证，bootloader 签名策略仍是设备侧边界。

## 4. HTTP 路由目录

以下路径全部追加到 `/api/boa/v1/firmware`。`viewer+` 表示 viewer/operator/admin，具体资源仍受范围控制。列表使用不透明 cursor，limit 默认 50、最大 100；排序含唯一 ID，避免翻页重复或遗漏。

### 4.1 能力、包和版本

| 方法与后缀 | 角色 | 输入/输出与约束 |
| --- | --- | --- |
| GET `/capabilities` | viewer+ | server_id、protocol_version、principal_id、role、grants、limits、policy_revisions；不泄露秘密 |
| GET `/releases?profile_id=&channel=beta&cursor=&limit=` | viewer+ | 授权范围内已发布版本，发布时间倒序；首版只有 beta |
| GET `/releases/{id}` | viewer+ | 不可变发布快照及 published/withdrawn 状态；不可见资源 404 |
| GET/HEAD `/releases/{id}/content` | viewer+ | 按制品 ID 取正文，不输出磁盘路径；Content-Length、Accept-Ranges、ETag=`"<sha256>"`、单段 Range/If-Range；已撤下返回 410 |
| GET `/packages?state=&cursor=&limit=` | admin | 隔离/就绪包、校验结果；普通用户不能取得隔离包正文 |
| POST `/packages/uploads` | admin | filename、size_bytes、sha256、format、profile_id、来源声明；201 返回 upload_id、expires_at，预留配额 |
| GET `/packages/uploads/{id}` | admin | 上传/校验状态和错误，就绪时含 package_id |
| PUT `/packages/uploads/{id}/content` | admin | 完整包流式写临时文件，长度/哈希一致后原子提交；200；中断后从零重传，首版不承诺上传分片续传 |
| POST `/packages/uploads/{id}/complete` | admin | 异步校验，202 返回 validating；终态重复请求 200 返回同一 package；失败为 quarantined |
| POST `/releases` | admin | package_id、channel=beta、profile_id、policy_revision、说明；ready 且信任/兼容/数据影响通过才 201 |
| POST `/releases/{id}/withdraw` | admin | reason；200；阻止新下载/授权/开始，不替换包、不自动回滚设备 |

### 4.2 升级控制与审计

| 方法与后缀 | 角色 | 输入/输出与约束 |
| --- | --- | --- |
| POST `/upgrade-authorizations` | operator+ | operation_id、device_ref、release_id、expected_running_images；原子检查范围/兼容策略并占用设备，201 返回 UpgradeSnapshot |
| GET `/upgrades/{id}` | 本人/有范围的 admin | 授权、开始许可、阶段、租约、修订和证据；读取不触发刷写或续期 |
| POST `/upgrades/{id}/start` | 该授权操作者 | If-Match；operation_id、最终 preflight 观测；200 返回含持久化 StartPermit 的 UpgradeSnapshot。原子复核最新权限、发布状态、策略和设备租约 |
| POST `/upgrades/{id}/cancel` | 本人/有范围的 admin | If-Match；reason；仅尚未签发开始许可时 200 取消并释放租约，已开始或结果不确定时 409；不发送设备强停命令 |
| POST `/upgrades/{id}/resolve` | admin | If-Match；reason、resolution_outcome、设备观测证据；核实后 200 归档并释放租约。不提供无证据 force-unlock |
| PUT `/upgrades/{id}/events/{sequence}` | 该操作者/有范围的 admin | sequence 从 1 起；phase、观测时间和证据；相同内容重传 200，首次接收 201，冲突/缺口 409；不替代 start/cancel/resolve |
| GET `/upgrades?device_ref=&cursor=&limit=` | 有范围的 operator/admin | 创建时间倒序的历史；不是设备实时状态 |

`events/0` 不再有“开始升级”的含义，也不注册兼容别名；draft.1 未实现，没有旧客户端迁移需要。事件只能推进已许可操作的合法阶段；最终结果符合第 6.3 节的完成条件后，Server 才归档/释放租约。所有升级控制响应返回 UpgradeSnapshot；事件响应返回 last_event_sequence 和最新快照，快照变化时 revision 同步递增。

### 4.3 设备、主体及策略管理

| 方法与后缀 | 角色 | 输入/输出与约束 |
| --- | --- | --- |
| GET `/devices?cursor=&limit=` / GET `/devices/{id}` | operator+/限定范围 | 逻辑身份、允许 profile、状态和 revision；不是实时 BLE 扫描结果 |
| POST `/devices` | admin | label、identity、allowed_profile_ids；201 分配 device_ref；已知稳定硬件标识重复时 409 |
| PATCH `/devices/{id}` | admin | If-Match；label、enabled、allowed_profile_ids；200 新 revision；禁用阻止新授权/开始，活跃升级保留快照；不变更已有物理身份 |
| GET `/principals` | admin | 脱敏主体、角色、授权范围、状态、revision；没有 token 明文/摘要 |
| POST `/principals` | admin | label、role、grants；201，新 token 只展示一次 |
| PATCH `/principals/{id}/grants` | admin | If-Match；role、device_refs/profile_ids；200 新 revision；检查最后管理员，记录操作者与前后范围 |
| POST `/principals/{id}/revoke` | admin | If-Match；reason；200；立即阻止新请求/许可，不强停设备关键阶段 |
| POST `/principals/{id}/rotate` | admin | If-Match；200；原子轮换使旧 token 失效，新 token 仅首次响应展示 |
| GET `/profiles?cursor=&limit=` / GET `/profiles/{id}` | viewer+/限定范围 | 板型、镜像映射、验证状态、当前策略修订和公开信任标识 |
| POST `/profiles` | admin | hardware_targets、image_layout、身份/兼容验证证据、label；201；缺验证证据标记 unverified，不允许借上传包自报兼容 |
| PATCH `/profiles/{id}` | admin | If-Match；仅 label、notes、enabled；硬件/镜像布局改变须新 profile，不覆盖已发布引用 |
| GET `/profiles/{id}/policy` | viewer+/限定范围 | 最新公开策略快照及 policy_revision，不包含私钥 |
| PUT `/profiles/{id}/policy` | admin | If-Match；信任公钥标识/指纹、bootloader 条件、电量、数据影响和确认策略；201 创建不可变 policy_revision |
| GET `/profiles/{id}/policies/{policy_revision}` | viewer+/限定范围 | 读取被发布/授权引用的历史快照；修订必须属于同一 profile |

不同设备和 profile 的授权交集由 Server 计算，不能只信任客户端过滤。人工登记的 identity 必须标明 assurance=manual；设备观测也不自动升级成加密认证。私钥生成、签名服务和固件构建服务不在这些 API 内。

## 5. DTO 与修订

```text
Capabilities {
  server_id, protocol_version: "1.0.0-draft.2", principal_id, role,
  grants{device_refs[], profile_ids[]}, limits, policy_revisions[]
}
Package {
  package_id, state: uploading|validating|quarantined|ready,
  filename, format: ota_zip|signed_bin, size_bytes, sha256,
  declared_source, source_commit?, build_id?, profile_id,
  images[{image_index, version, size_bytes, sha256, signing_key_id}],
  validation{status, checks[], errors[], validator_revision}, created_at
}
Release {
  release_id, package_id, profile_id, channel: beta, display_version,
  state: published|withdrawn, notes, policy_revision,
  compatibility{hardware_targets[], bootloader_requirements, app_min_version},
  data_impact{recordings, settings, wifi, upload_credentials, migration},
  created_by, published_at, withdrawn_at?
}
DeviceRecord {
  device_ref, label, enabled, revision,
  identity{kind, hardware_id?, assurance: manual|observed, evidence},
  allowed_profile_ids[]
}
Principal {
  principal_id, label, role, grants{device_refs[], profile_ids[]},
  state: active|revoked, revision
}
FirmwareProfile {
  profile_id, label, enabled, hardware_targets[], image_layout[],
  validation_status: unverified|verified, validation_evidence,
  current_policy_revision, revision
}
PolicySnapshot {
  policy_revision, profile_id, trust_public_keys[], bootloader_requirements,
  minimum_battery_percent, external_power_conditions, confirmation_rules,
  data_preservation_rules, created_by, created_at
}
UpgradeSnapshot {
  upgrade_id, operation_id, principal_id, device_ref, release_id, package_id,
  server_id, profile_id, sha256, policy_revision, revision,
  authorization_state: issued|consumed|cancelled|expired|revoked,
  operation_state: reserved|active|needs_attention|completed|cancelled|expired,
  lease_state: reserved|held|released,
  expected_running_images[], start_before, permit?, reported_phase?,
  last_event_sequence, outcome: succeeded|failed|null, result_evidence?
}
StartPermit {
  permit_id, upgrade_id, operation_id, principal_id, device_ref,
  release_id, package_id, sha256, policy_revision, issued_at,
  constraints{manual_only:true, erase_app_settings:false}
}
UpgradeEvent {
  sequence, phase, bytes_sent?, total_bytes?, observed_at,
  evidence_source: app_report|device_observation,
  running_images?, error_code?, message?
}
```

- 可修改资源和 UpgradeSnapshot 带 revision，并返回 ETag=`"<resource-kind>:<id>:<revision>"`。需要 If-Match 的写操作缺头返回 428，不匹配 412；检查与修改在同一事务内执行，不能先读再无条件写。
- profile policy 的 GET/PUT 使用所属 profile 的 revision/ETag；PUT 在创建不可变策略快照时原子更新 profile 指针并增加该 revision。读取历史 policy 不改变当前指针。
- device/profile/grants 列表中的 ID 均须存在且符合范围，不允许用任意 ID 绕过策略。已发布 Package/Release/Policy 的核心字段是不可变快照；策略变化产生新 revision，不修改正在执行的授权。
- data_impact 每项为 preserved、erased、migration_required、unknown；不接受缺字段默认 preserved。常规升级不得发布未知影响或要求擦除设置的包；迁移策略需另行验证后开放。
- 包哈希仅证明内容一致，签名可信和适用硬件须分别验证。来源标签、版本文字、手工 assurance 不等于密码学证明。

## 6. 授权、开始、取消与结果核实

### 6.1 正常开始

1. App 读取设备实际状态和运行镜像，选择固定 release_id；不使用可漂移的 latest 下载链接。
2. 创建授权时 Server 检查主体范围、设备/profile、发布/策略、预期运行镜像和设备租约。取得 reserved 租约，默认 30 分钟内开始；同 device_ref 的并发创建返回 409 device_busy。
3. App 下载并验证完整包，重新读取设备状态；取得本机 Device 独占锁，暂停共享控制轮询。录音、暂停录音、传输、直传上传、状态未知或另一 OTA 活跃时不启动。
4. App 在本机持久化 operation_id 和 pending_start，以 If-Match 调用独立 start，提交最新观测。首版观测不超过 30 秒；这是应用策略，不是固件时钟精度声明。Server 在事务内复核凭据/范围、设备启用、release、策略修订、期限及租约。策略发生变化返回 409 policy_changed，不能静默改用新策略。
5. Server 持久化 StartPermit，将授权置 consumed、操作置 active、租约置 held，返回 permit；这表示允许开始，不证明设备已写入。App 保存 permit 和 device_write_started，再调用一次 DeviceUpdatePort。不能以 events 请求获取开始许可。

start 请求体为 `{operation_id, preflight:{observed_at, recording_state, transfer_active, upload_active, ota_active, battery_percent, running_images[], package_sha256, local_device_lock_acquired}}`；供电和槽位等 profile 必需字段也须提交。它们是 App 观测声明，Server 验证字段、时效和策略一致性，不据此宣称直接观测了设备。缺少适用 profile 所需证据时拒绝开始。

start 响应丢失时，使用同一幂等键或 GET 查询同一 operation_id/permit。只有本地日志能确认从未调用设备写入且仍满足预检时，才恢复该次开始；本地记录遗失、曾发出写命令或结果不确定时先 reconcile 设备并置 needs_attention，不能因 Server 显示 active 就自动重刷。

### 6.2 取消和超时

- cancel 与 start 串行竞争；尚未 consumed 时取消成功并释放 reserved 租约，已签发 permit 时 409 cancel_not_safe。UI 不把关闭页面当作 cancel 已成功。
- 已 cancelled 的同一请求返回原快照；expired/revoked 等未开始终态返回当前快照，不改写原始原因。已开始或已完成操作不能用 cancel 覆盖历史。
- 已开始后不提供 Server 远程强停/reset；App/OS 异常退出先保留恢复记录。SMP 续传只在相应 profile 经验证后显式恢复，不能通用自动重放。
- 未开始授权过期可转 expired 并释放 reserved 租约；已开始不按 TTL 自动解锁。运行中超时、断链、版本不一致或结果未知均转 needs_attention，继续保留 held 租约与镜像引用。
- 建议预检 HTTP 超时 30 秒、BLE 无进展观测窗口 60 秒、重启重连窗口 120 秒；profile 可通过新策略修订调整。超时是进入核实流程的信号，不证明设备没有执行，不自动触发 reset、重刷或强制取消。

### 6.3 结果核实与释放

- 有开始许可、合法完整阶段及所需运行镜像/确认观测的 succeeded 事件，Server 才归档 completed、outcome=succeeded、释放租约；证据仍标明由 App 上报，不冒充设备签名证明。
- 已开始后的 failed/缺失证据事件归入 needs_attention，不能凭一个 SDK 错误就解锁。管理员通过 resolve 提交 reason、resolution_outcome=succeeded|failed 和当前运行镜像、设备状态、核实时间等证据；Server 检查 profile 规则、revision、租约及状态后归档 completed 并释放。
- resolve 不能重新发开始许可，也不向设备发命令；缺少设备安全状态/运行镜像证据时返回 422 resolution_evidence_required，保持锁定。没有安全确认时先按 USB 恢复指引处理，再提交核实结果。
- 需要管理历史/已恢复设备但原主体已被撤销时，由有权限 admin 核实并追加审计；原主体不能绕过撤销补报。App 可保留脱敏离线记录供恢复使用，不因此扩张权限。

## 7. 事件阶段与竞争规则

App 的观察阶段：`downloading → verifying_package → preflight → uploading → validating_image → rebooting → verifying_running_image → succeeded`，以及 failed、needs_attention。downloading/preflight 可在 reserved 时报告，设备写入阶段要求已有 StartPermit。cancelled/expired 由控制结果生成，不能用普通事件单方面释放设备。

事件 sequence 从 1 连续递增；服务端保存 last_event_sequence，断网后依次补报，相同序号相同规范化正文幂等，正文冲突或缺口返回 409 并附 last_event_sequence。迟到事件可作为审计保留，但不得倒退已归档状态、改变 permit 或重新占锁。bytes_sent 仅代表镜像传输，不是整体成功比例。

| 竞争或变化 | 开始许可签发前 | 开始许可签发后 |
| --- | --- | --- |
| 版本撤下/profile 禁用 | 阻止新授权/start；新正文 GET（含续传）410；撤下时已打开的流不强制中止 | 保留快照/缓存 lease，让本机安全完成；不远程回滚 |
| 主体撤销/权限缩小 | 每次检查并拒绝新许可，按当前身份返回 401/403 | Server 拒绝无权请求；不强停设备，本机保留记录，后续 admin 核实 |
| 策略修订 | start 检测快照冲突，取消旧授权后显式重新申请 | 不给活跃操作套用新策略；原快照保留审计 |
| 网络断开 | 不能新签发 start，UI 不进入设备写入 | 本机安全完成关键阶段，恢复后按权限补报或 admin 核实 |
| 切换 Server/账号 | 不把旧任务、凭据或授权用于新目标 | 活跃操作固定旧目标快照，保留本地镜像，不自动改投 |
| 清理缓存/制品 | 无引用时按保留策略清理 | 活跃 lease、published/保留审计引用阻止删除 |

主体撤销、授权范围缩小后不再允许该目标、版本撤下或设备/profile 禁用时，尚未签发 permit 的受影响授权置 revoked，并在与 start 串行的事务内释放 reserved 租约；已 consumed 的授权不按此路径解锁。策略修订不静默替换授权快照，仍通过 policy_changed 要求显式取消/重新申请。revoked 原因及触发操作者保留审计。

Server 的 device_ref 租约只约束本服务；本机 Device 锁仍不可省略，也不能保证外部刷机工具没有占用同一实物。

## 8. 幂等、资源限制与错误

- 所有控制型 POST（导入、complete、发布、撤下、授权、start/cancel/resolve、主体/设备/profile 创建、凭据撤销/轮换）使用 Idempotency-Key。按主体、方法、路由、键绑定规范化正文摘要，至少保留 24 小时；相同请求返回同一结果，不同正文 409 idempotency_conflict。主体和当前可见权限在回放前仍须检查；策略/状态变化不能让旧响应重新授予一次设备执行权。
- If-Match 写操作先识别已完成的相同幂等操作，再返回原结果，不能因原动作已增加 revision 把合法重试误报为 412；首次执行仍必须原子检查当前 revision。PATCH/PUT 以相同正文和 If-Match 保证条件写，不能无条件覆盖并发修改。
- 创建/轮换 token 的首次响应含明文，但不写审计、普通数据库或幂等响应缓存。重放只返回脱敏主体及 secret_available=false；明文响应遗失时由其他有效 admin 或受控恢复 CLI 显式再次轮换，不提供再次读取旧秘密的 API。
- 上传会话 24 小时到期。完整包 PUT 可按原 upload_id 和预期 SHA 从零重传；已完成的相同正文返回原状态，不允许替换已验证内容。首版建议包 32 MiB、解压 64 MiB、归档 32 项、镜像 1–2 个、固件库 2 GiB，实际值由 capabilities/策略给出。配额先预留后写入，清理不能删除活跃升级引用。
- 拒绝归档路径穿越、绝对路径、链接、重复冲突镜像和解压炸弹。固件来自服务内不可变制品，不接受任意远程 URL。私钥、原始 token 和设备 Wi-Fi 密码不进入普通 DTO 或日志。
- 错误体统一 `{error:{code,message,retryable,request_id,details?}}`。400 参数、401 未认证、403 无权、404 不存在/不可见、409 冲突、410 过期/撤下、412 revision 冲突、413 限额、422 无效包/证据、428 缺 If-Match、507 空间不足。details 不泄露秘密或磁盘路径；retryable 不授权自动重刷。

## 9. 样例、兼容性和验收

[可机器解析的请求/响应样例](examples/firmware-http-v1.json) 展示 endpoint 拼接、能力、独立 start/cancel/resolve 与权限条件写；所有 ID、镜像和响应都是说明性样例，不代表已有设备或已部署路由。

与 draft.1 相比：开始许可从 events/0 移到独立 start；增加 cancel/resolve、设备/主体 grants/profile/策略管理和修订保护；拆开授权、操作、租约及 App 观察阶段。因 draft.1 未实现，无旧客户端迁移和兼容别名。此修订不修改 `/api/audio`，不新增固件 AT 命令。

工程冻结前仍需核实实际板型/运行包、稳定身份、签名公钥/bootloader、SMP 镜像读取/确认、配置与录音保留。验收包含角色越权/撤销、两个客户端争用、start/cancel/撤下竞争、幂等响应遗失、条件更新、毒化/截断 ZIP、配额/清理、断电/断网/进程恢复、同版本不同构建和升级后配置/录音仍可用。模拟或示例不能替代真机验收。当前仅修订文档，不部署接口、不发 token、不刷机。
