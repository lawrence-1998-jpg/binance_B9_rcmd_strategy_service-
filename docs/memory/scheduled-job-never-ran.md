---
name: scheduled-job-never-ran
description: 定时任务（launchd/cron）装完必须确认它真的成功跑过一次——注册成功≠跑起来；macOS 上 launchd 读不了 ~/Desktop/~/Documents，指过去的软链会永远 EPERM 且只写进日志不报警
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-08-04T11:25:21.701Z
---

2026-08-04 B9 生产停摆 3 天。表现：网站轮次停在 8-01，大盘情绪空白。

根因：Mac 上的 enrich worker（`com.lawrence.b9-enrich-worker`，每 5 分钟一次）
**从装上那天起一次都没成功跑过**。日志里是同一行重复了两千遍：

    can't open file '/Users/user/.b9/local_enrich_worker.py': [Errno 1] Operation not permitted

`~/.b9/local_enrich_worker.py` 是一条指向 `~/Desktop/claude code/.../scripts/` 的**软链**。
**macOS TCC 保护 ~/Desktop、~/Documents、~/Downloads**：我的终端有权限所以读得到，
launchd 起的 agent 没有 Full Disk Access，穿过软链就 EPERM。
装的时候我只确认了"文件在、plist 注册上了"，没看它跑一次的结果。

**同时暴露的连锁问题**（一个没跑起来的定时任务能藏住多少东西）：
1. VM 侧成本闸每轮如实记 `personal_key_disabled: 801` 并且**行为完全正确**
   （fail-closed，个人 key 分文未花），所以日志"看起来很正常"，没有 ERROR。
2. 积压涨到 1.1 万条也只是 WARNING。**"按设计延后"和"下游死了"在日志里长得一样。**
3. 3 天里没有任何告警，是用户自己看出来的。

**How to apply**：
1. **装完定时任务，必须等它自然触发一次并确认退出码 0 + 有预期副作用**
   （`launchctl list` 第二列是上次退出码；2 就是失败）。手动跑通不算数——
   手动跑用的是我的权限上下文，跟 launchd/cron 的完全不同。
2. **别把可执行文件软链进 ~/Desktop / ~/Documents / ~/Downloads**。要么放
   `~/.local/bin`、`~/.b9` 这类无 TCC 保护的位置，要么放实体副本。
   （代价：副本要跟着源码更新，改完记得同步。）
3. **"上游正常延后"必须能与"下游挂了"区分开**。判据不是"有没有报错"，
   而是**端到端产出**：最近 N 小时有没有新事件落库、积压是否在下降。
   加一条"库里最新事件超过 X 小时没更新就告警"，比任何组件级健康检查都有效。
4. 这条对所有"我装了个后台任务"都成立：cron、launchd、systemd timer、
   GitHub Action —— 装完看它真的跑成功一次，再说"已部署"。

相关：[[agent-file-exists-not-agent-done]]、[[definition-of-done-user-surface]]、
[[verify-write-not-just-return-code]]、[[b9-enrich-bridge]]
