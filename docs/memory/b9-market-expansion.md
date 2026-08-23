---
name: b9-market-expansion
description: B9从纯币圈扩展到美股/港股/日股/韩股/宏观新闻——market_scope标签、情绪排序、dxFeed机构新闻源
metadata: 
  node_type: memory
  type: project
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-28T14:23:53.409Z
---

2026-07-28 起 B9 不再只处理币圈新闻，接入美股/港股/日股/韩股/宏观政策（明确
排除 A 股），根因是 `crawler/pipeline.py` 的 GENERIC-TECH FIREWALL 曾把"无清晰
加密传导路径的大盘新闻"系统性打成 D 档雪藏——**这是一条通用教训**：任何"防止
不相关内容冒充相关"的规则，当产品范围扩大后都要重新检查是不是变成了系统性
压制，不能想当然认为旧规则依然适用新范围。

**关键设计**：
- `market_scope` 字段（crypto/us_stock/hk_stock/jp_stock/kr_stock/
  macro_policy/general）与 `news_type`（事件性质）正交，两套分级体系独立
  （加密用一套 S/A/B/C/D，非加密市场用另一套，判据不同）
- 情绪排序（[[b9-market-expansion]] 的核心）**不动 `crawler/scoring.py` 的
  五因子公式**——只在查询时做有界（≤15%）重排，写回会污染策略实验室/去重
  依赖的 `importance_score` 口径
- `crawler/dxfeed_news.py`：Lawrence 转发的公司真实 dxFeed 试用凭据
  （`news.dxfeed.com`，Basic Auth，binance/该密码，config/.env 里
  `DXFEED_NEWS_USER`/`DXFEED_NEWS_PASS`），机构级实时美股新闻，MT
  Newswires 聚合。**symbol 参数一次最多传 10 个**，超过直接 400，不是限流。
  Benzinga/Massive 那份资料核实后**没有真实 key**，只是示例数据。

详见 WORKLOG #61、REQUIREMENTS_LOG 2026-07-28。
