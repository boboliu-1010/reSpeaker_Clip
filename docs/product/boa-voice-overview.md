# Boa Voice：首期只做音频文件列表

**v0.6｜2026-10-23｜设计约定，新增接口尚未实现。**

## 1. 首期目标

**录音上传到同一个 Server，App 能看到自己的音频文件。**

App 只有一个文件列表：文件名、大小、时间、来源（App / Clip），支持手动刷新，按时间倒序。Clip 原始文件标注“原始录音”，首期不要求可播放，不等待转码。

![首期：接收录音并显示本人文件](images/boa-audio-files-mvp.png)

转写、摘要、模型配置、固件管理、分享、标签、文件编辑和自助设备认领均不进入首期；原有已实现功能保留，不因缩减设计而删除代码。

## 2. 只保留三组必要接口

目标只有一个 Boa Server。开发机业务入口当前为 `https://100.58.19.213:9528`，Clip 暂用同机 9527；接收模块并入后统一入口。

| 功能 | API | 必要信息与成功条件 | 当前状态 |
| --- | --- | --- | --- |
| App 查看自己的文件 | GET `/api/boa/v1/audio-files?offset=0&limit=50` | 用户 token；返回完整接收的文件元数据，见下节 | **唯一新增的 App 列表接口，未实现** |
| App 上传本地录音 | POST `/api/audio/uploads`；PUT `/api/audio/uploads/{id}/parts/{index}`；POST `/api/audio/uploads/{id}/complete`；GET `/api/audio/uploads/{id}` | 创建带 filename/size/sha256/mime；分片带 X-Content-SHA256；查询到 complete 才列入文件清单 | 已有上传；用户归属/列表索引待补 |
| Clip 上传原始录音 | GET/PUT `/v2/devices/{device}/recordings/{session}/{segment}` | 设备 token；整片大小/SHA，PUT 另带 Content-Length/Upload-Offset/本块 SHA；stored 后登记列表 | 实验已有接收；合并/归属/索引待补 |

不另加文件详情、下载、播放、任务进度、重试或后台管理 API。原上传分片、Clip 续传的具体字段保持原协议，见 [存储基线](../contracts/storage-http-v1.md)、[Clip 接收基线](../contracts/clip-ingest-app-server-bridge.md)。

现有 `/api/audio/recordings` 继续只服务原来的 complete 标准音频；新增只读列表将 App 文件与 Clip 原始片段放在同一个视图，避免把原始片段伪装成可播放音频，也不破坏旧客户端。

## 3. 文件列表协议

请求带 `Authorization: Bearer <user_token>`。offset 默认 0 且 ≥0；limit 默认 50、范围 1..100；按 created DESC、id DESC 排序。200 响应如下（示例，不是现有服务响应）：

```json
{
  "items": [
    {
      "id": "f_0dcaed10342c49d689a6f32ecb3e409e",
      "filename": "Clip-20261023090000-1.bin",
      "size": 160044,
      "created": 1792720800,
      "source": "clip_direct"
    }
  ]
}
```

- id：Server 生成的稳定不透明字符串；App 不解析，也不作为访问凭证。
- filename：显示名称，不是服务器磁盘路径。size：字节。created：Server 建立记录的 Unix 秒，**不代表录音发生时间**。
- source：`app_upload` 或 `clip_direct`。空列表返回 `{"items":[]}`；不足 limit 表示当前页已到末尾。
- 清单只收完整落盘且校验通过的文件；未完成/失败上传不展示。原件、SHA 和来源键保留在 Server，列表不传音频字节、token 或磁盘路径。
- App 文件沿用上传 ID 建索引；Clip 以 `(device_id,binding_epoch,session,segment)` 建唯一来源索引。沿同一来源键重传且大小/SHA 一致不新增行，不同内容冲突；App 重新创建上传会产生新来源，不承诺全文件去重。Server 重启后索引与文件可恢复，不靠 App 在线补登记。

## 4. 归属只保留必要规则

| 来源 | Server 如何确认归属 |
| --- | --- |
| App 上传 | user_token → user_id；创建上传时固定 owner_user_id |
| Clip 上传 | device_token → 已登记设备与用户绑定；核对路径设备一致，首次接收时固定 owner_user_id 和 binding_epoch |
| App 查列表 | Server 按认证用户的 owner_user_id 过滤；客户端不能传用户 ID 切换归属 |

开发者通过受控 CLI 预登记用户、设备和凭据，不建设管理后台或自助绑定 API。换绑先核清旧数据、未传录音和上传，再撤销旧凭据；历史文件不改归属。未绑定设备拒绝上传；缺失/无效 token 返回 401。

**当前共享音频 token 尚无用户隔离。** 需要补独立用户凭据、owner 索引和查询过滤。历史原始文件若缺少可信设备/用户映射，先由开发者核对，不猜归属、不直接向用户开放。

## 5. 首期验收与边界

1. App 文件或 Clip 原始片段上传完成后，刷新能看到一条记录，名称/大小/时间/来源正确。
2. 中断上传不入列表；同源重传、Server 重启不产生重复记录或丢失归属。
3. 两个用户分别只能看到自己的文件，无效 token 不能列出内容。

先完成“接收 → 归属 → 持久索引 → 本人文件列表”。**能列文件不等于能播放、能转写或已完成真机联调。**

旧 AI、自动串联与固件文档仅作后续参考，不再作为首期需求或依赖。本轮只精简设计，不改 App/Server/固件运行代码、不部署。
