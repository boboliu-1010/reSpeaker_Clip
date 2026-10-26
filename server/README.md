# Clip 录音接收服务

服务端源码独立放在本目录。当前使用可靠文件上传协议＋DTLS 1.2＋UDP，默认端口为
9527；旧 HTTPS 接收端已移除。设备构建和控制工具仍在 `tools/https_poc/`。

## 文件

| 文件 | 职责 |
|---|---|
| `dtls_upload_server.py` | 服务入口、连接调度、设备认证与连接接管 |
| `dtls_server_transport.py` | OpenSSL DTLS 握手、加密数据报收发 |
| `dtls_upload_protocol.py` | 数据包格式和协议常量 |
| `dtls_upload_session.py` | OPEN／DATA／QUERY／FINISH 状态处理 |
| `dtls_upload_store.py` | 窗口接收、持久检查点与完整文件校验 |
| `resume_store.py` | 共用落盘、恢复、原子检查点及错误类型 |
| `profile_timing.py` | 可选存储耗时采样 |
| `make_credentials.py` | 隔离测试使用的临时证书生成工具 |

## 启动

从仓库根目录运行，使用 Python 3.10+，并安装支持 DTLS API 的 pyOpenSSL。
依赖需提供 `SSL.DTLS_SERVER_METHOD`、DTLS cookie 回调及密文 MTU 设置接口。
`--help` 不读取凭据、不启动监听：

```sh
python3 -m server.dtls_upload_server --help
python3 -m server.dtls_upload_server \
  --root /home/roger/clip-receiver \
  --directory /home/roger/clip-receiver/experiments/dtls-upload-v1/data \
  --identities /home/roger/clip-receiver/experiments/dtls-upload-v1/private/identities.json \
  --port 9527
```

`--root` 下需要 `private/server-chain.pem` 和 `private/server.key`。
`--identities` 指向设备标识到令牌的 JSON 映射。私钥和令牌放在源码目录外，
不得提交、打印或复制到构建环境。服务端证书必须受设备内置 CA 信任，且覆盖设备
配置的服务器地址。云网络与防火墙需要允许 **UDP 9527**。

数据目录应仅供一个接收进程使用。迁移代码目录时保留原数据、检查点、设备令牌及
证书；本次源码整理没有更换协议、证书或数据格式。

## 当前部署与迁移

当前运行实例仍使用迁移前部署的文件布局：

```text
roger@100.58.19.213
/home/roger/clip-receiver/experiments/dtls-upload-v1/app/dtls_upload_server.py
用户服务：clip-dtls-upload-v1.service
```

本次仓库目录调整不自动替换运行实例。后续部署时应将整个 `server/` 包复制到部署
工作目录，例如 `<deployment>/server/`，并从 `<deployment>` 使用
`python3 -u -m server.dtls_upload_server` 启动。服务的证书、令牌和数据参数保持原值。

## 回归验证

从仓库根目录运行：

```sh
python3 -m unittest discover -s tools/https_poc -p 'test_*.py'
```

其中包含 DTLS 接收、断点续传、连接接管、存储故障以及固件 C 逻辑测试。
固件主机测试另需 Clang 及对应 SDK fixture；未安装 pyOpenSSL 的环境会跳过真实
DTLS 网络用例，因此还需在有该依赖的环境执行：

```sh
python3 -m unittest discover -s tools/https_poc -p 'test_dtls_receiver.py' -v
```

协议与固件集成说明见 [DTLS 上传方案](../docs/dtls-upload-core.md)。
