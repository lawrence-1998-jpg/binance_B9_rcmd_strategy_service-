-- 020 缓存携带 embedding（ADR-002 A4）——2026-08-02
--
-- 目的：消灭最后两个个人 key 付费点（semantic_prefilter 与 aggregate_events
-- 的 embedding 调用）。已实测公司 LiteLLM 网关支持 text-embedding-3-small
-- 且维度可指定 256——与 crawler/dedup.py 用的**完全一致**，换通道不换语义，
-- 已有的 0.82 阈值和存量向量都不用重新标定。
--
-- 做法：Mac worker 拿到条目后本来就要算 enrich，顺手把 embedding 一起算了
-- 回传。单条 embedding 成本约为 enrich 的千分之一量级，几乎不增加网关压力。
--
-- 为什么存在缓存表而不是直接进 news_events.embedding：
-- 缓存是"结构化结果"的载体，而 embedding 正是从结构化结果（title_en +
-- description_short_en）算出来的，两者天然同生命周期——同一个 prompt_hash
-- 下它们必须配套，分开存会出现"换了 prompt 但向量还是旧文本算的"这种
-- 对不上的状态。news_events.embedding 仍然是最终归宿，由 pipeline 写入。

ALTER TABLE llm_enrich_cache
  ADD COLUMN embedding BLOB NULL
      COMMENT 'float32 紧凑存储的 256 维向量（1024 字节），由 Mac 经公司网关算好回传；
               NULL 表示该条没带向量，pipeline 会照旧退化为规则去重';
