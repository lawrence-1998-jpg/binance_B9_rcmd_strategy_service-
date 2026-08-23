---
name: parallel-agents-ssh-limit
description: 并行 agent 同时 SSH 同一台机器会打爆 sshd 连接槽位，必须开 ControlMaster 复用
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-25T20:29:41.180Z
---

2026-07-26，同时跑 4 个 agent 去 `ssh manus-vm` 做测试，结果 22 端口开始对我的 IP 返回 "Connection refused"，持续约 25 分钟。停掉 agent 后**立刻**恢复。

**Why:** 不是 fail2ban（没装），也不是 OOM（内存 48.9%、load average 0.00）。是 sshd 的 `MaxStartups`（未认证并发连接上限，默认 `10:30:100`）被打满——每个 agent 都在独立开 SSH 连接，超过上限 sshd 直接拒绝新连接。症状具有欺骗性：机器活着、其他端口（8080 的 API）完全正常，只有 22 被拒，很容易误判成被封 IP 或机器宕机。

**How to apply:** 已在 `~/.ssh/config` 的 `manus-vm` 配置里加了连接复用（`ControlMaster auto` + `ControlPath` + `ControlPersist 10m`），实测 10 次并发调用在服务端只占 1 条 TCP 连接。**以后要并行跑多个 agent 操作同一台远程机器，先确认 ControlMaster 已开**，否则重演。诊断口诀：SSH refused 但其他端口正常 → 先怀疑连接数上限，别急着怀疑封禁或宕机。

相关：[[b9-vm-access]]
