---
name: b9-price-sensitivity-study
description: "B9新课题\"用户价格敏感度建模\"是观察性研究——线上没有price alert产品"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-08-18T19:32:57.394Z
---

Lawrence 2026-08-19 启动的核心课题：**用户价格敏感度建模**——一个用户对多大幅度的
持仓资产价格波动才会敏感。敏感者高频低门槛发 price alert，反之高门槛低频。

**关键前提（他明确说的）：目前线上没有 price alert 产品。** 所以路径是：

```
自然价格波动 → 用户自然的访问/交易(针对其持仓标的) → 反推敏感度 → 0→1 上线产品
```

**Why:** 这个前提决定方法论。它意味着：(1) 不需要 alert 点击回流数据，监督信号来自
用户对自然行情的自发反应；(2) 没有推送干预，反向因果担忧减轻，但也**没有实验变异**，
上线前只能给相关性证据，不能声称因果；(3) 解释了 Data Map 里 price_alert 表族的怪象——
还在更新的都在 `cmc_dw.*`(CoinMarketCap 独立产品)，主站那几张 2024 年就停更，
因为主站根本没上过这功能，**这些表只是参考口径不是数据源**。

**How to apply:** 建模时把它当剂量反应曲线——横轴是持仓资产波动幅度分档，纵轴是该档位下
「交易或查看」的条件概率，拐点=触发阈值，斜率=敏感度。注意三个坑：持仓要用当时快照
不能用最新持仓回溯；零暴露用户(从没持有过波动资产)估不出参数要单独归入冷启动，
不能填默认值(见 [[never-default-missing-data]])；报结论时说清是相关性不是因果。

工作底稿在 repo 的 `docs/spade-access-plan.md`，跨会话续做看那里。
数据在币安 Spade 平台，见 [[spade-data-platform-access]]。
