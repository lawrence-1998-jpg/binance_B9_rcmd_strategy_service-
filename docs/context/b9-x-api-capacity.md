---
name: b9-x-api-capacity
description: B9 的 X API 额度远比现在用的多，search/recent 端点一直没开发
metadata: 
  node_type: memory
  type: project
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-25T20:06:47.297Z
---

2026-07-26 实测：B9 项目的 X Bearer Token 可以调 `GET /2/tweets/search/recent`，限额 **450 请求 / 15 分钟**（≈43,200 次/天）。

**Why 重要：** 现有爬虫只用了 `GET /2/users/:id/tweets`（拉 32 个 KOL 的时间线，约 192 请求/天），等于全网关键词搜索这块能力完全闲置。加密行业新闻在 X 上首发的比例很高，这是欠召的一个大缺口。

**How to apply:** 讨论召回不足或加数据源时，先想到把 search/recent 用起来——它是**免费已有**的额度，优先级高于任何付费 API 采购。关键词搜索可以覆盖 KOL 名单之外的突发（黑客、上币、大额清算），也能按 `-is:retweet lang:zh` 之类的过滤条件定向补中文快讯。

相关：[[b9-project-shape]]
