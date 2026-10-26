# 当前固件排查入口

| 现象 | 先确认什么 | 说明 |
|---|---|---|
| 配网保存成功，但没有上传 | `UPLOADAUTO?`、配置完整性、设备忙闲及待传文件 | `saved:true`只表示已保存，不表示已联网或服务器可达 |
| `NETCHECK`成功，但上传失败 | 校时、DNS、DTLS、服务器UDP端口与认证 | NETCHECK只测Wi-Fi关联和DHCP；见[协议](protocol.md#ble-network-validation-and-automatic-upload-control) |
| 偶发联网／握手很慢 | ready、关联、DHCP、ARP和DTLS分别计时 | UDP没有TCP建连，但DHCP／ARP和DTLS重传仍存在；见[网络诊断](network.md) |
| UDP 9527收不到 | 监听、主机防火墙和上层网络的UDP放行 | TCP 9527可用不能证明UDP已放行 |
| 上传中按录音，暂时未录 | `record_pending`、`record_error`和实际`recording` | pending表示已排队，需完成资源清理后启动 |
| 文件又上传了一次 | 目标指纹、长度、状态CRC及服务器偏移 | 换目标或本地状态无效可重新发现；以服务器检查点续传 |
| production上传后设备列表为空 | `delete_after_upload`、`session_deleted` | 整段全部确认后默认删除；默认诊断版保留 |
| 电量显示不下降 | VBUS／充电状态、原始SoC、显示平滑和Wi-Fi未校准电流 | 不等于没有耗电；见[功耗](power.md) |
| 拔USB后没有串口 | CDC自动关闭、物理数据线和USB开关 | 可通过BLE开启USB，必要时接回后再次开启；不是直接证明设备重启 |
| 切换默认版／production后蓝牙配对报错 | 两端绑定是否匹配 | SDK绑定配置标志不同，可能需移除主机旧绑定并重新配对；不要直接擦除设备设置或录音 |
| SD空闲后关闭 | SD空闲电源管理 | 下次访问按原有流程重新挂载；持续扫描／日志会影响休眠 |
| 64位计数JSON输出`ld/lu` | 目标格式化库的64位支持 | 当前BATTDIAG显式转换十进制；不要用截断为32位掩盖溢出 |
| 镜像无法启动／验签失败 | 设备Bootloader信任的密钥、镜像类型及布局 | 进入[USB恢复](usb_dfu.md)，使用匹配回退包；不把问题直接归因于网络 |

默认版按已启用的编译开关提供资源、网络和性能诊断；production不保证存在调试命令。
抓包、设备状态和服务器日志需对齐时间边界，保留失败样本；不要为复现直接清空用户录音。
