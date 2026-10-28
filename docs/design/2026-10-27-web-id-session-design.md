# 可信开发网络：用户 ID 登录

用户明确要求：不用密码、凭证文件，只输入用户 ID。网页自动连接当前 Server。

- 首次输入已登记用户 ID，Server 设置 7 天的 HttpOnly / SameSite=Strict Cookie；HTTPS 使用 Secure。刷新和下次打开自动恢复，退出立即撤销。
- ID 仅选择账户，不能防冒用已知 ID；限当前可信开发网络，启动参数 `--allow-id-login` 显式开启，默认关闭。
- 网页不接触会话密钥。会话随机值仅在 Cookie 中传输，Server 存 SHA-256；失效、停用用户、退出和关闭该模式后不再接受。
- 文件仍按当前用户分区。Cookie 会话只获得用户角色，开发者操作继续使用原有 Bearer 认证。
- 新接口：POST /api/boa/v1/session 输入 user_id；GET 查询当前会话；DELETE 退出。同源检查保护 Cookie 写操作。
- App Bearer、Clip DTLS 凭证和绑定不变，不开放设备自助认领，不自动创建用户。
- 普通界面只显示用户 ID 与“进入”；开发者令牌登录折叠保留，无凭证文件。

验收：会话恢复和退出、过期/停用、跨用户文件隔离、开发者权限限制、跨站请求拒绝、原 Bearer 与 DTLS 回归，以及远程 Chrome 实际登录与播放。

接口补充：Cookie 业务请求必须带 X-Boa-User，与当前 Cookie 身份不符返回 409 session_user_changed；旧页面清空本地身份/录音，不撤销其他页新会话。写操作另查 Origin；恢复接口用于发现当前身份。支持显式环境变量 BOA_ALLOW_ID_LOGIN=1。
