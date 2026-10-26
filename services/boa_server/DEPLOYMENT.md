# 开发环境部署

运行进程：services/boa_server/run.py。默认同一端口9528提供 HTTPS/TCP 和 DTLS/UDP。使用单独虚拟环境安装 requirements.txt，service 的 Restart=on-failure、UMask=0077，设置固定代码目录与独立持久目录。

更新时：备份旧 unit/配置；停止旧服务并备份 SQLite 与文件；登记已确认的用户归属；运行新代码的测试；切换 service，验证 HTTPS 上传/下载和 DTLS，再启动客户端。保留旧代码、虚拟环境和 unit 以便回滚，备份不进入 Git。

客户端配置使用原 HTTPS 地址和用户凭据。DTLS 配置指向同一主机/端口，固件需信任 DTLS CA；部署后仍需验证外部网络 UDP 可达性。
