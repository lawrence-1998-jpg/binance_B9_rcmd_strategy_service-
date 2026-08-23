---
name: b9-enrich-bridge
description: B9的本地Claude预处理桥——Mac worker拉任务用Claude Max额度结构化，VM缓存命中免OpenAI费；已跑通，15分钟/100条/并发6
metadata: 
  node_type: memory
  type: project
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-26T10:24:12.075Z
---

2026-07-26 上线 enrich bridge：Mac 上 launchd 每 15 分钟跑（2026-07-26 晚提速：100条/批、并发6，OpenAI 仅剩 $40 时本机优先） `~/.b9/local_enrich_worker.py`
（源文件在仓库 `scripts/`），从 VM `/api/enrich/pending` 拉 staging 待处理条目，
本地 `claude -p --model sonnet` 按 VM 下发的同一 prompt 结构化，回传
`llm_enrich_cache` 表；pipeline Step 4 命中缓存的条目零 OpenAI 成本，miss 走原路径。

关键机制：prompt_hash 闸门（prompt 一变旧缓存自动失效）；Mac 离线=全 miss=行为
与从前一致；两路径共用 normalize_tags 后处理。embedding 刻意不走本地（便宜且
0.82 阈值绑定该向量空间）。

CLI 认证已解锁（2026-07-26 晚用户 /login 完成），worker 实测跑通：
10条/91秒/并发5，全部成功，质量卡在分档规则内。

**How to apply**: 查桥的水位用 `GET /api/enrich/stats?token=...`；pipeline 日志里
看 "Step 4 bridge: N/M items pre-enriched"。改 SYSTEM_PROMPT 后不用清缓存，
hash 闸门自动处理。Worker 源文件改动后要重新 cp 到 ~/.b9/（launchd 因 macOS TCC
不能直接跑 Desktop 下的脚本）。相关：[[b9-vm-access]]、[[b9-x-api-capacity]]
