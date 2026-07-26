-- enrich bridge：本地 Claude 预处理结果的缓存表。
--
-- 写入方：Lawrence Mac 上的 scripts/local_enrich_worker.py（经 /api/enrich/submit）
-- 读取方：crawler/pipeline.py run_pipeline() 的 Step 4（storage.load_enrich_cache）
--
-- prompt_hash 是一致性闸门：只有与当前 SYSTEM_PROMPT+NEWS_SCHEMA 指纹一致的行
-- 才会被 pipeline 采用；prompt 迭代后旧行自动失效（由 pending 端点的清理顺手删）。

CREATE TABLE IF NOT EXISTS llm_enrich_cache (
  url_hash    CHAR(64)    PRIMARY KEY,           -- staging._url_hash 同一把尺子
  prompt_hash CHAR(16)    NOT NULL,
  enriched    JSON        NOT NULL,              -- LLM 原始结构化输出（normalize 之前）
  model       VARCHAR(64) NOT NULL DEFAULT 'claude-local',
  created_at  DATETIME    DEFAULT CURRENT_TIMESTAMP,
  consumed_at DATETIME    NULL,
  INDEX idx_prompt_created (prompt_hash, created_at)
);
