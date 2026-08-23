---
name: b9-strategy-live-metrics
description: B9推荐策略已上线三个位置(早午日报/Macro/Sector)，指标体系v1已交付
metadata:
  type: project
---

2026-08-20 Lawrence 确认：**我们设计的推荐策略已上线币安产品**。核心位置：
001 早午日报（内容策略 07-25 上线、人群策略 07-31 上线）、006 Macro Insight、
005 Sector Insight。全景见 Confluence《B9 内容推荐策略 All in One》
(pageId=598858876，**匿名可 curl**，不需要浏览器会话)。
架构选型 LLM4Rec (Lite OneRec)：候选池百~千级、分钟/小时级延迟可接受、分群优先于 uid 个性化。

**Why:** 这推翻了此前"币安前端未接入"的记录（那是 08-20 盘点时的准确状态，之后上线）。
所有对外描述、README、服务盘点里的"未上线"口径都要更新。

**How to apply:** 指标体系 v1 已交付（docs/analysis/metrics-system.html +
artifact 2e1ef49b）：核心逻辑=乘法链 捕得全×排得对×说得准×有人看，
北极星=S/A级事件有效触达率@6h，4 主指标+对角制衡防刷。
落地依赖：基准池每日爬取 job（新增）+ 端上三个位置的埋点 ID（外部依赖，
Colson/Fosal/winnie 侧）。相关：[[b9-price-sensitivity-study]] 的"看后行动率"
是 L4 与交易业务的连接点。
