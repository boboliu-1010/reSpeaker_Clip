# External Wi-Fi patch maintenance

## Mac 一体化升级工具

`upgrade.py` 串联 Recovery 应用核刷写、双次备份、离线 LittleFS 迁移、Wi-Fi 补丁
写入、完整回读、录音固件安装及启动通信检查。内置 SMP 串口客户端，不调用 nrfutil。
`build_macos.py` 把它、Python 运行环境、所有依赖和指定镜像打包，最终用户无需安装
Python、SDK、nrfutil 或命令行工具。当前交付形式为 ZIP，解压后双击
`开始升级.command`，Terminal 中选择首次升级、继续、恢复或仅检查安装包。

这不是适用于任意 Clip 的通用刷机包：当前仅处理 v0.1.2 的109块旧 LittleFS到107块
布局，要求已知原应用镜像、原网络核及 Bootloader 兼容。安装前验证三份应用镜像的
SHA-256、RSA-2048 签名和公钥指纹，验证固定 SDK Wi-Fi 补丁。首次 Recovery 的应用核
摘要必须匹配随包原布局回退镜像；未知出厂版本拒绝。公钥由安装包提供，安装包本身
仍须通过可信渠道分发；最终设备是否接受签名由已安装 Bootloader 决定。

### 最终用户流程

1. 停止录音，数据线直连 Mac，按已验证按键方式进入 Recovery Mode。
2. 双击 `开始升级.command`，选择首次迁移，确认后自动执行整个流程。
3. 保留程序显示的恢复目录。默认在
   `~/Library/Application Support/reSpeaker Clip Upgrade/Runs/`，包含原备份、迁移镜像、
   原子状态文件、阶段日志、回读报告和错误类型；目录0700、文件0600，不上传。
4. 失败后选择“继续上次升级”并输入同一目录；程序绑定 USB 序列号和维护协议设备 ID，
   不因串口编号变化切换设备，不允许两个进程同时使用同一恢复记录。
5. 部分写入时拒绝自动继续，选择“从原备份恢复”；完整恢复原布局后再装回退镜像。
   如果在备份阶段失败、尚未开始写外置 Flash，可以直接安装原布局回退镜像。

程序在运行中用 macOS 自带 `caffeinate` 阻止空闲休眠；仍不要合盖或切断供电。
当前恢复能力经过模拟故障测试，真实迁移中断电/断线恢复还需实机验证。
旧回退固件 USB 可能默认关闭，恢复后需观察屏幕/蓝牙，不能把无串口误判为启动失败。
新固件完成提示只代表镜像、Flash 回读和启动通信检查，不代替录音、Wi-Fi、上传和
BLE OTA 功能验收。

### 开发者打包

在目标架构的 Mac 上使用 Python 3.10+ 和独立虚拟环境：

```sh
python3 -m venv /path/to/upgrader-venv
/path/to/upgrader-venv/bin/pip install -r tools/flash_maintenance/build-requirements.txt
/path/to/upgrader-venv/bin/python tools/flash_maintenance/build_macos.py \
  --maintenance /path/to/maintenance.signed.bin \
  --firmware /path/to/firmware.signed.bin \
  --firmware-config /path/to/firmware-build/.config \
  --rollback /path/to/known-original-layout.signed.bin \
  --patch /path/to/pinned/nrf70.bin \
  --public-key /path/to/signing-public.pem \
  --output /path/to/Clip-Upgrade-macOS-arm64
```

不会打包私钥、用户配置、设备备份或开发环境。只更新应用核，保留网络核、Bootloader
和 SD 录音。Apple Silicon 与 Intel 分别构建，不宣称通用架构。PyInstaller 的本地
ad-hoc 签名不等于 Developer ID 签名或公证；本工具当前产生开发验证包。正式分发前
必须完成整套实机流程、原厂版本兼容性验收、Developer ID 签名和公证。

维护、目标和回退固件均由命令行路径传入，不绑定某次编译的版本号或摘要。最终固件
变更后，用新的签名 BIN 和对应最终 `.config` 重新打包，重新生成摘要及安装包验证；
不要手工替换已生成包内的文件。分区、Wi-Fi 补丁或签名方案变化则需重新评估本工具
支持范围，不能仅替换 BIN。生成物、测试数据和设备备份放仓库外，或已忽略的
`tools/flash_maintenance/.local/`；不提交程序包、固件或用户恢复目录。

源码运行入口也可用于开发调试；`inspect` 不访问设备，其他操作会更新设备：

```sh
python tools/flash_maintenance/upgrade.py inspect --bundle /path/to/bundle
python tools/flash_maintenance/upgrade.py run --bundle /path/to/bundle
python tools/flash_maintenance/upgrade.py resume --bundle /path/to/bundle --state-dir /path/to/original-run
python tools/flash_maintenance/upgrade.py restore --bundle /path/to/bundle --state-dir /path/to/original-run
```

协议参考：[SMP 串口传输](https://docs.zephyrproject.org/latest/services/device_mgmt/smp_transport.html)。

## 底层维护协议与手动操作

This temporary USB application accesses the SPI NOR directly without mounting
LittleFS, starting Bluetooth/Wi-Fi, or opening recording files. It is an
application-only replacement: preserve the installed bootloader and network core.
Opening its CDC port at 1200 baud enters the existing USB recovery bootloader.

The writable range is strictly `0x130000..0x800000`; both OTA slots below it are
protected by the firmware. Writes start locked. The host verifies the device ID,
backup, migration plan, unchanged source image, per-chunk CRC, and final complete
readback. Keep power connected throughout a write.

Install the pinned requirements in a separate virtual environment. Backups and
migration output contain Bluetooth keys and configuration: keep them private,
outside Git, with directory mode 0700 and file mode 0600. Never upload them.

After flashing the maintenance application and identifying the CDC port:

```sh
python flash_tool.py --port /dev/cu.usbmodem11301 info
python flash_tool.py --port /dev/cu.usbmodem11301 backup --output /private/tmp/clip-backup
python migrate.py --backup /private/tmp/clip-backup --patch /path/to/nrf70.bin --output /private/tmp/clip-migration
python flash_tool.py --port /dev/cu.usbmodem11301 apply --backup /private/tmp/clip-backup --image /private/tmp/clip-migration/migrated.bin --plan /private/tmp/clip-migration/migration.json --report /private/tmp/clip-migration/apply.json --allow-write
```

Backup reads the entire 109-block region twice and compares the results. Migration
opens the source read-only without automatic formatting, creates a 107-block
LittleFS 2.1 filesystem, and verifies every directory, file, and user attribute
after remounting. The last two 64-KiB blocks hold the exact SDK patch plus erased
padding. The old filesystem remains unchanged in the backup.

Only after successful full readback should the external-patch application be
uploaded through USB recovery. Validate Bluetooth identity/settings, recording,
downloads, and Wi-Fi startup on the device.

For rollback, return to the maintenance application, restore the original region,
then upload the known-good internal-patch application:

```sh
python flash_tool.py --port /dev/cu.usbmodem11301 restore --backup /private/tmp/clip-backup --report /private/tmp/clip-backup/restore.json --allow-write
```

An interrupted write must be restored before attempting normal application boot.
Restore compares against the current flash and repairs changed blocks; apply
deliberately refuses a device that no longer matches the original backup. Do not
reuse an existing report filename. Recovery does not depend on LittleFS or Wi-Fi.

Run host verification with:

```sh
python -m unittest discover -s tools/flash_maintenance -v
```
