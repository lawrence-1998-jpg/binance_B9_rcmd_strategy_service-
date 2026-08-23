---
name: b9-dedup-gap
description: B9 去重曾有 48.7% 冗余，2026-07-26 已重构修复；语义阈值实测应取 0.82 而非文档的 0.65
metadata: 
  node_type: memory
  type: project
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-25T20:07:03.682Z
---

2026-07-26 接手 B9 时实测：`news_events` 表 855 行里有 416 行是同事件重复（**48.7%**），单个事件最多占 8 行。已重构修复（Pipeline v2.0）。

**三个叠加的根因：** ①`generate_event_id()` 拿 LLM 改写后的 `title_en` 做 hash，每轮措辞不同就生成新 ID，`ON DUPLICATE KEY UPDATE` 形同虚设；②聚合层用 TF-IDF **词频**相似度冒充文档写的 embedding，对同义改写完全无效；③只在单轮内去重，cron 每 4h 一轮而抓取窗口重叠，跨轮完全不设防（量最大的漏口）。

**修复：** 事件 ID 改由 LLM 输出的规范化三元组（subject/action/date）派生；聚合换成 `text-embedding-3-small` 256 维；新增写库前的跨轮归并。代码在 `crawler/dedup.py` / `storage.py`。

**最值得记住的一条经验：** skill 文档写的语义阈值 cosine≥0.65 在真实数据上**会严重过度合并**（把"油价破100美元"和"特斯拉周跌18%"当成同一事件）。在 855 条真实事件、28 万配对上分档标定后取 **0.82**："应合并"最低 0.859、"应分开"最高 0.761，中间有 0.098 的干净空隙。

**Why 阈值该偏高：** 召回由三元组精确匹配保障（不受阈值影响），向量层的职责是抓指纹漂移的漏网之鱼，两层互补。同时往召回方向调的代价是把两件真实事件合并成一件——那比漏一条重复严重得多。

**How to apply:** 以后再调任何语义相似阈值，都先在真实数据上分档抽样标定，不要直接照抄文档里的数字。

相关：[[b9-vm-access]]、[[b9-project-shape]]
