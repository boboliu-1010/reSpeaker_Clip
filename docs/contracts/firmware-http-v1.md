# 固件管理接口契约

**版本：1.0.0-draft.1｜状态：待评审、未实现。** 对应 [产品与模块设计](../superpowers/specs/2026-10-22-firmware-management-design.md)。现有 `/api/audio` 不变；下面路由目前不存在，不能据此配置 App 后就认为功能可用。

待调整项集中在 [功能与协议调整清单](../product/firmware-management-review.md) 的 A-01～A-08；包括显式 start/cancel/resolve、设备和授权范围管理、profile/策略接口。这些是下一版修订建议，当前表格仍保留 draft.1，未将建议误标为冻结协议。

## 1. 标识、权限与状态

- `package_id`：Server UUID，绑定一个不可变制品及校验元数据；`upload_id` 为独立的临时上传 UUID。
- `release_id`：不可变发布记录 UUID，绑定 package、profile、beta 渠道和发布策略修订；撤下改变可发现性，不替换字节。
- `upgrade_id`：一次设备升级尝试 UUID；与本地 `operation_id`、制品 ID 和设备 `device_ref` 分开。
- 时间统一 UTC RFC3339，大小为字节，哈希为 64 位小写 SHA-256。版本文字只作显示，兼容性与是否升级不能只比较字符串。
- 独立固件 Bearer 凭据，TLS 必须验证。每条路由检查角色与资源范围；缺凭据 401、无权限 403，越权资源查询不泄露元数据。旧音频 token 默认无固件权限。
- `PackageState = uploading | validating | quarantined | ready`；`ReleaseState = published | withdrawn`；ready 不等于 published。
- 包 ready 后不可修改字节/核心元数据；重新导入不同内容需新 package。publisher 名称和人工来源声明不是已验证的签名证明。
- 设备登记首版由管理员受控 CLI 建立逻辑 device_ref、允许 profile 和可访问主体，App 从 capabilities 读取授权目标并保存本机连接映射；不从 BLE remoteId 自动生成可信硬件身份。管理员可在 App 权限页创建、撤销、轮换后续主体凭据；只有首个管理员依赖 CLI bootstrap。

## 2. 模块接口

| 提供方 | 接口（领域签名） | 成功条件 |
| --- | --- | --- |
| FirmwareCatalogPort | `listReleases(filter)` / `getRelease(id)` / `checkCompatibility(device, release)` | 返回角色可见内容，未知兼容性保留 unknown/reasons |
| FirmwarePublisherPort | `beginImport(metadata, op)` / `putContent(upload, bytes)` / `completeImport(upload, op)` / `publish(package, policy, op)` / `withdraw(release, op)` | 校验与权限通过后才发布；不可覆盖制品 |
| FirmwareCachePort | `fetch(release, progress)` / `verify(ref)` / `evict(ref)` | 精确长度和 SHA 一致后原子发布本地可用缓存，活跃升级持有读取 lease |
| FirmwareAuthorizationPort | `authorizeUpgrade(device, release, op)` | 返回绑定操作者、设备、制品和策略快照的授权记录；不能由 App 自行签发 |
| DeviceUpdatePort | `preflight(device, release)` / `start(lease, grant, op)` / `observe(id)` / `reconcile(id)` | 全设备互斥，区分上传、启动、确认；不能确定结果时返回 needs_attention |
| FirmwareAuditPort | `appendEvent(upgrade, sequence, evidence)` / `listHistory(filter)` | 事件去重，客户端声明与设备观测证据分开 |

`DeviceUpdatePort` 不向 UI 暴露原始 BLE 写入、文件路径或任意命令。网络/文件/SDK 类型只停留在适配器内。

## 3. HTTP 路由目录

所有路径以 `/api/boa/v1/firmware` 开头。首版无需新增 Web 管理站，App 管理页面使用同一 API。账号 Web 登录、固件构建服务和签名服务不隐含在这些接口中。

| 方法与后缀 | 角色 | 输入/输出与约束 |
| --- | --- | --- |
| GET `/capabilities` | viewer+ | 包/解压/配额限制、支持格式、当前角色、允许 profile/设备范围和策略修订 |
| GET `/releases?profile=&channel=beta&cursor=&limit=` | viewer+ | 仅授权已发布记录；分页，limit 默认 50、最大 100 |
| GET `/releases/{id}` | viewer+ | 不可变元数据与当前撤下状态；不泄露存储绝对路径 |
| GET/HEAD `/releases/{id}/content` | viewer+ | 服务内 ID 解析的制品下载；Content-Length、SHA ETag、单段 Range/If-Range；撤下禁止新下载 |
| GET `/packages?state=&cursor=&limit=` | admin | 包括隔离包、校验结果；普通用户不可获取隔离二进制 |
| POST `/packages/uploads` | admin | filename、size_bytes、sha256、format、profile、构建来源声明；201 返回 upload_id、expires_at |
| GET `/packages/uploads/{id}` | admin | 状态及明确错误，完成时返回 package_id；不把收到字节等同于校验完成 |
| PUT `/packages/uploads/{id}/content` | admin | 流式完整包，长度/哈希验证，写临时文件后原子提交；首版中断后从零重传，无分片续传承诺 |
| POST `/packages/uploads/{id}/complete` | admin | 202 返回 validating，轮询至 ready/quarantined；重试不会创建第二份包 |
| POST `/releases` | admin | package_id、channel=beta、profile、更新说明和策略修订；ready + 信任/兼容校验通过才 201 |
| POST `/releases/{id}/withdraw` | admin | reason；保留历史与活跃升级引用，撤下不能更换制品 |
| POST `/upgrade-authorizations` | operator+ | operation_id、device_ref、release_id、expected_running_images；服务验证资源范围和策略，201 返回 upgrade_id 与授权快照 |
| GET `/upgrades/{id}` | 本人/有范围的 admin | 授权快照、服务收到的进度、观测证据与最终结果 |
| PUT `/upgrades/{id}/events/{sequence}` | 该授权 operator/admin | 单调 sequence 的事件；相同内容重传幂等，冲突 409；Client 声明标记 reported |
| GET `/upgrades?device_ref=&cursor=&limit=` | 有范围的 operator/admin | 升级历史；按发生时间倒序，保留审计，不能作为设备实时状态 |
| GET/POST `/principals` | admin | 查看脱敏主体/创建独立角色凭据；新凭据只返回一次，禁止日志记录 |
| POST `/principals/{id}/revoke` | admin | 撤销后阻止新请求/授权；不能强制中断已开始的设备关键启动阶段 |
| POST `/principals/{id}/rotate` | admin | 新凭据只展示一次，旧凭据失效；幂等重放不回显秘密，遗失响应后需显式再次轮换 |

首个 admin 通过服务器受控 CLI 初始化，不提供匿名 bootstrap 或“把任意 Bearer 当管理员”的后门。主体创建输入 role、允许的 device_refs/profile_ids，禁止普通主体修改自己的授权范围；保留最后一个有效管理员，防止自锁。App 发布/撤下/权限操作显示确认，Server 始终重新授权。

## 4. 制品、发布与升级快照

```text
Package {
  package_id, state, filename, format: ota_zip|signed_bin,
  size_bytes, sha256, declared_source, source_commit?, build_id?,
  hardware_targets[], profile_id,
  images[{image_index, version, size_bytes, sha256, signing_key_id}],
  validation{status, checks[], errors[], validator_revision}, created_at
}
Release {
  release_id, package_id, profile_id, channel: beta,
  display_version, notes, state, policy_revision,
  compatibility{hardware_targets[], bootloader_requirements, app_min_version},
  data_impact{recordings, settings, wifi, upload_credentials, migration},
  created_by, published_at, withdrawn_at?
}
UpgradeAuthorization {
  upgrade_id, operation_id, principal_id, device_ref,
  release_id, package_id, sha256, policy_revision,
  expected_running_images[], issued_at, start_before,
  constraints{manual_only:true, erase_app_settings:false}
}
UpgradeEvent {
  sequence, phase, bytes_sent?, total_bytes?, observed_at,
  evidence_source: app_report|device_observation,
  running_images?, error_code?, message?
}
```

`data_impact` 每项为 `preserved | erased | migration_required | unknown`，不接受空缺默认为 preserved。首版未知影响或要求擦除设置的包不得作为常规升级发布；另行制定可恢复迁移策略后再放开。package_id 不是 SHA，下载对已发布的不可变快照重新验证，不跟随“latest URL”漂移。

## 5. 幂等、授权有效期及失败

- 创建导入、发布、撤下、升级授权、创建/撤销/轮换 principal 使用 `Idempotency-Key`；按主体、路由和键绑定规范化请求摘要，至少保留 24 小时。相同请求返回原结果，键相同但参数不同 409。
- 创建 principal 的重试不重复返回明文秘密；响应遗失时通过已有主体记录识别结果，再显式轮换新凭据。服务审计不保存或回放明文响应。
- 上传会话 24 小时到期；同一 upload 的 PUT 只允许相同预期哈希的完整内容，禁止已验证/已发布对象覆盖。限额先预留再写入；验证失败留隔离元数据，不可供普通下载。
- 升级授权建议 30 分钟内开始。App 启动前需要在线复核授权和设备状态；首版不开放离线升级。已经开始后持久记录本机进度，网络中断不强行停止镜像验证/重启，恢复后补报事件。
- Server 对同一 device_ref 串行授权并持有独占租约；存在未过期授权/活跃升级时拒绝其他创建请求，返回 409。未开始的授权可过期释放；开始后的未知结果须 reconcile/管理员核实，不能仅凭 TTL 自动允许第二次刷写。本机 Device 操作锁仍不可省略，服务端逻辑身份租约不证明其他外部工具没有连接设备。
- 开始动作通过 `PUT /upgrades/{id}/events/0` 提交 phase=preflight 与最终观测摘要，Server 原子复核权限、发布状态、策略和租约，返回 accepted 后 App 才允许启动 SMP 写入。该事件必须在线送达；授权已经 revoked/expired 时拒绝。之后事件使用 sequence>=1；查询接口返回授权状态与租约状态。
- 缓存键包含 server identity、principal、package_id 和 SHA。切换服务或撤销权限后不把另一身份缓存直接作为授权；活跃本机升级的只读 lease 在完成/人工恢复前保留，清理缓存不能中断正在读取的镜像。
- 本地导入可先检查文件，但在自建服务管理模式下，真正升级仍须经管理员导入/发布和 operator 授权；不能通过本地 bin 绕过服务权限。
- Server 返回授权不等于远程设备已开始。重新进入页面先 reconcile；不得因超时重新创建升级、重发 reset 或自动确认镜像。
- 错误响应：`{error:{code,message,retryable,request_id}}`；400 参数、401 未认证、403 无权、404 不存在/不可见、409 冲突、410 会话过期、413 限额、422 包无效/不兼容、507 存储不足。`retryable=true` 不表示可盲目重放升级写操作。
- Server 下载通过制品 ID 定位本地可信存储，不接受 App 提供任意 URL 让 Server 抓包；自定义 endpoint 是 App 的服务配置，不是未经限制的服务端代理。

## 6. 升级状态与冻结条件

`authorized → downloading → verifying_package → preflight → uploading → validating_image → rebooting → verifying_running_image → succeeded`；另有 failed、cancelled、needs_attention。进度按阶段展示，bytes_sent 仅是镜像传输，不是整体完成比例。

Server 默认将 App 上报结果标为 reported。App 只有在该 profile 的运行镜像/版本/确认条件都观测通过后才提交 succeeded；证据不足时提交 needs_attention，不能只依据 UI 动画或 SDK 布尔值。审计既不篡改为设备签名证明，也不承诺无条件回滚。

协议冻结前需确定：目标实物板型/运行包、稳定身份获取、签名信任、公钥/bootloader 约束、SMP 读取与确认能力、设置与录音保留策略。验收至少覆盖角色越权、撤销、不同主体缓存隔离、篡改/截断/恶意 ZIP、重复请求、配额、撤下与活跃升级竞争、断电/断网、进程重启、双客户端争用、同版本不同构建和升级后配置/录音仍可用。硬件未到时只能完成模拟与服务验证，不能把这张清单标为完成。
