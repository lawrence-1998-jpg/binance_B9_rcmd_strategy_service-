---
name: no-security-hardening
description: Lawrence 明确要求不要主动改动服务器安全配置
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-25T19:31:58.893Z
---

2026-07-26，我提议帮忙关掉云主机的 SSH 密码登录（只留密钥认证），Lawrence 回复"不要。不要搞安全问题。"

**Why:** 这是他自己的开发/实验环境，改安全配置有把自己锁在门外的风险，收益也不明显；他要的是把精力放在业务功能上。

**How to apply:** 不要主动提议或执行安全加固类操作（改 sshd_config、防火墙、权限收紧、轮换密钥等）。发现凭据泄露风险可以简单提一句，但不要反复建议，更不要直接动手。

相关：[[b9-vm-access]]
