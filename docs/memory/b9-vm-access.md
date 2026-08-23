---
name: b9-vm-access
description: B9 推荐策略服务的运行环境是一台 GCP 虚拟机，本地已配 SSH 别名 manus-vm
metadata: 
  node_type: memory
  type: project
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-25T19:31:53.160Z
---

B9 推荐策略服务（binance_B9_rcmd_strategy_service-）的**代码运行环境不在本地**，而在一台 Manus 部署的 GCP 云主机上：`ubuntu@34.138.247.158`，项目路径 `~/crypto-news-crawler/`。

本地 `~/.ssh/config` 已配好别名，直接 `ssh manus-vm` 即可免密登录（2026-07-26 配置的公钥认证）。

**时区（2026-07-26 起）**：VM 系统/MySQL/cron 全部为 **Asia/Shanghai (UTC+8)**。
pipeline 每天 08:00/20:00 触发（实际时刻与旧 UTC 0/12 相同）。切换前的历史行
时间戳是 UTC，比北京时间早 8 小时，随老化淘汰不回填。

**How to apply:** 任何涉及跑 pipeline、查 MySQL、看服务状态的操作都要 ssh 过去做，本地仓库只是代码副本。常用检查：`systemctl status crypto-news-api`、`docker ps`（rsshub 容器必须在跑）、`mysql -uroot -p"$MYSQL_PASSWORD" crypto_news`。

相关：[[b9-dedup-gap]]

> 密码不写在本文件（仓库为 public）。取值：VM 上 `~/crypto-news-crawler/config/.env`
> 的 `MYSQL_PASSWORD`，或开发者本机 `~/.b9/SECRETS-INVENTORY.md`。
