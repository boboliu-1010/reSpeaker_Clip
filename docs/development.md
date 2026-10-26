# 开发、验证与代码维护

维护仓库为 [BofAI/reSpeaker_Clip](https://github.com/BofAI/reSpeaker_Clip)。当前上传源码
在 `feature/dtls-upload-core-0.1.2`；源码结构和构建入口见 [architecture.md](architecture.md)
及 [tools/upload/](../tools/upload/README.md)。

## 分支与提交

采用 `feature/* → develop → release/vX.Y.Z → main` 的维护方向。功能在 feature 验证后
再合入 develop；发布准备阶段按需建立 release 分支，验收后进入 main。
`release/*` 不是每次开发都必须创建。当前 main、develop 的远端提交为 `845713be`，
上传功能清理提交为 `112ad51`，不能把功能分支内容当成 main 已包含的功能。
远端另有 `boa/*` 专项分支；本说明不把它们纳入当前上传功能维护链路，也不更改它们。

改动在本地维护，检查并保留已有修改；不向上游 Seeed 仓库误推。提交前核对实际差异和
验证范围，推送明确指定 `bofai` 和目标分支。构建镜像、私钥、设备令牌、Wi-Fi 凭据及
录音不入源码库。临时展示 HTML 和测试数据留本地。

## 开发与构建流程

使用 Mac 本地开发 → Ubuntu 编译 → Mac 设备测试。编译服务器只承担源码同步和构建，
不维护另一条未核对的源码线。首次或改变规则时先 dry-run，再 rsync；默认不 `--delete`。
源码改名／删除时检查远端残留，必要时使用独立源码与构建目录。

从仓库根目录执行，路径按实际环境填写：

```sh
python3 tools/upload/build.py \
  --ncs /path/to/ncs --sdk /path/to/zephyr-sdk \
  --build /path/to/ncs/build-clip-upload-default \
  --ca /path/to/public-ca.pem --preset dtls-single
```

追加 `--production` 选择 production。两种模式的数据通路性能参数一致；默认版提供
UART／资源／网络／性能诊断，production 关闭这些调试入口并默认整段上传后删除。
`CLIP_UPLOAD` 为上传总开关，CA 构建变量为 `CLIP_UPLOAD_CA_FILE`；没有 HTTPS 构建回退。
底层 TLS 库仍服务 DTLS 的加密和证书校验。

构建记录保存 Git 提交、未提交差异和新增源码快照、实际工具链／依赖版本、最终配置、
日志、分区、签名镜像、ELF/map及资源报告。产物本地按版本目录维护以便回退与对比；
尚未实机验证的临时构建与测试记录放 `.analysis/`，不冒充已验收发布版本。

## 验证入口

```sh
CLIP_TEST_SDK=/path/to/pinned-sdk-fixture \
  python3 -m unittest discover -s tools/upload/tests -v
python3 -m unittest discover -s tools/upload/tests -p 'test_dtls_receiver.py' -v
```

主机 C 用例需要 Clang，SDK回移用例需要固定源码fixture。真实DTLS网络用例还需支持
DTLS API 的pyOpenSSL。跳过的网络用例应在具备依赖的隔离环境补测；不干扰运行接收服务。

清理提交 `112ad51` 的验证范围：110项主机用例执行完成（3项真实DTLS本机跳过），
接收服务器隔离环境23项DTLS／存储测试通过；默认版及production编译、签名、ZIP及
分区检查通过。这些用例存在重叠，不能简单相加当作独立测试数量，也不等于实机验收。

## 当前资源基准

以下为 `112ad51` 对应清理源码的完整录音应用构建，非裁剪上传实验版：

| 构建 | 应用 Flash | 静态 RAM | 应用 RAM 区域剩余 |
|---|---:|---:|---:|
| 默认版 | 852,228 B | 448,542 B | 2,018 B |
| production | 809,220 B | 444,974 B | 5,586 B |

应用 Flash 区域933,376 B，RAM区域450,560 B。静态RAM包括堆和线程栈预留，不能再把
运行时堆分配叠加计算；“区域剩余”也不是堆中可用空间。要判断上传峰值，需采样实际
堆、线程栈和独立网络池。清理旧的未编入HTTPS源码没有释放大块运行时RAM。

## 实机与发布

编译与刷机分开；升级方式见 [usb_dfu.md](usb_dfu.md)。保留当前回退镜像和匹配的
外置Wi-Fi补丁布局，确认签名和分区后再测试。清理版本尚未因为编译通过就视为已刷机。

按改动选择持续上传、同一连接批量上传、录音抢占续传、断网、服务重启、硬复位及
真实掉电测试。每次记录文件数／大小／SHA-256、配置、网络、时间边界、失败及重传。
DATA速率和整任务速率分别统计，不把本机局域网结果与公网结果直接混为一个指标。
耗电结论需满足 [power.md](power.md) 的测量与校准条件。
