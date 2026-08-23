---
name: schema-drift-breaks-star-select
description: "给主表加列会打破任何用 SELECT * 往固定结构备份表里灌数据的脚本，而且往往炸在'要删数据了'那一步；备份/归档一律取两表列交集显式写列名"
metadata:
  type: feedback
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-08-01T18:13:58.290Z
---

2026-08-02 B9 给 `news_events` 加了两列（tradable_entities / tradable_count）。
当天跑例行清理脚本 `purge_untrusted_stale.py` 直接 1136
"Column count doesn't match value count"。

根因链条：脚本用 `CREATE TABLE IF NOT EXISTS purged_stale_20260729 LIKE
news_events` 建备份表——表名带日期，`IF NOT EXISTS` 会**复用几天前建的那张**，
它是按当时的表结构建的；然后 `INSERT INTO 备份表 SELECT * FROM news_events`
就比目标表多出两列。

**Why 这个坑特别值得记**：
1. **每次给主表加列都会重演**，而加列是最常见的迭代动作之一。
2. **炸的位置最坏**：脚本的顺序是"先备份、再删除"，报错发生在备份这一步——
   如果哪天有人把备份包在 try/except 里"容错"，就会变成不备份直接删。
3. 平时不跑不报错，等到真要清理数据那天才发现，属于潜伏型。

**How to apply**：
1. 任何"把行搬进备份/归档表"的代码，**不要用 `SELECT *`**。运行时取两表的
   列交集，显式写列名，加列减列都不受影响。
2. 交集之外的新列要**显式打印警告**（"备份表缺少新列 [...]，这些列不会进
   备份"），而不是静默忽略——删除本身仍安全，但恢复时得知道少了什么。
3. 加列的迁移做完后，顺手把"读写这张表的周边脚本"跑一遍。本项目相关的至少
   有：purge_untrusted_stale、rescore_factors（它的 backup 表同理）、
   各处 EVENT_COLUMNS/POOL_COLUMNS 投影。
相关：[[mass-rewrite-guardrails]]、[[lab-prod-must-share-formula]]
