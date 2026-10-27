# 上传固件工具

当前上传链路为可靠文件上传协议＋DTLS/UDP。服务器代码独立在
[`server/`](../../server/README.md)，本目录不再提供 HTTPS 构建或 TCP 调优入口。

| 入口 | 用途 |
|---|---|
| `build.py` | 构建完整录音应用的默认版或 production，生成日志，不自动刷机 |
| `device.py` | USB AT 配置和状态查询，私有配置从本机文件读取 |
| `hardware_probe.py` | 上传已知文件，采集资源、网络状态并核对接收结果 |
| `negative_probe.py` | 证书时间错误、取消及恢复的实机验证 |
| `backport_network.py` | 生成构建目录专用的 DHCP／ARP 修复副本 |
| `instrument_network.py` | 在构建目录生成网络阶段诊断副本 |
| `instrument_dtls_crypto.py` | 在构建目录生成 DTLS 加密耗时诊断副本 |
| `tests/` | 主机 C 逻辑、控制工具及服务端集成回归测试 |

## 构建

```sh
python3 tools/upload/build.py \
  --ncs /path/to/ncs \
  --sdk /path/to/zephyr-sdk \
  --build /path/to/ncs/build-clip-upload-default \
  --ca /absolute/path/to/public-ca.pem \
  --preset dtls-single
```

追加 `--production` 使用基线 production 配置并关闭调试接口；两种模式保留相同
的 DATA 性能设置。默认预设为 `dtls-single`。可用 `--extra-conf` 追加应用层配置，
例如 `applications/clip/dtls-prepare-profile.conf`；不允许关闭 DTLS 来切回旧 HTTPS。

CA 必须是公开证书，不能传入私钥。配置、令牌、证书私钥及测试数据不进入仓库。
运行脚本前先按项目约定同步源码；编译成功不代表实机验证通过，也不会自动刷机。

## 回归测试

从仓库根目录执行，Python 3.10+，固件 C 用例还需要 Clang：

```sh
CLIP_TEST_SDK=/absolute/path/to/pinned-sdk-fixture \
  python3 -m unittest discover -s tools/upload/tests -v
```

SDK fixture 用于核对被回移／插桩的固定 SDK 源码。未安装支持 DTLS API 的
pyOpenSSL 时，真实 DTLS 网络用例会明确跳过，需另在具备依赖的环境执行：

```sh
python3 -m unittest discover -s tools/upload/tests -p 'test_dtls_receiver.py' -v
```

构建／诊断脚本支持直接运行；其他脚本的参数以 `--help` 为准。实机工具可能修改
设备配置或启动上传，执行前应核对配置和测试范围。

## 兼容与历史

固件主调度入口现为 `applications/clip/src/upload_runtime.c`。仅移除旧 HTTPS/TCP
上传实现，保留 DTLS 所需的 TLS 加密库、证书校验、时钟、哈希和持久化状态。
设备 settings 中原有 `https/config` 键保留以兼容已保存的 Wi-Fi、接收端和自动上传
开关；该键名不表示仍使用 HTTPS。

原 `tools/https_poc/`、HTTPS 流和 TCP 调优实验可从历史提交 `7e7ab97` 查看。
当前 DTLS 方案见 [上传说明](../../docs/dtls-upload-core.md)，网络修复见
[DHCP／ARP 回移说明](../../docs/network.md)。
