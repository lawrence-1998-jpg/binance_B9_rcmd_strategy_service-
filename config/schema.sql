-- 币圈新闻爬虫 MySQL Schema v1.3
-- Database: crypto_news
--
-- v1.3 变更（去重重构）：
--   news_events 新增 event_subject / event_action / event_fingerprint / embedding /
--   social_interactions 五列。前三列构成稳定事件指纹（id 由指纹派生，不再依赖 LLM
--   改写后的标题）；embedding 存 256 维 float32 向量供跨轮语义归并；
--   social_interactions 存关联 X 推文的互动总量，供 H 因子使用。

USE crypto_news;

CREATE TABLE IF NOT EXISTS news_events (
    -- id 现在 = event_fingerprint，见 crawler/dedup.py:build_fingerprint
    id                   VARCHAR(64)  PRIMARY KEY,
    title_en             TEXT         NOT NULL,
    title_zh             TEXT         NOT NULL,
    date                 DATE         NOT NULL,
    time_event           DATETIME,
    time_get_data        DATETIME     NOT NULL,
    description_short_en TEXT         NOT NULL,
    description_short_zh TEXT         NOT NULL,
    description_long_en  TEXT,
    description_long_zh  TEXT,
    sectors              JSON,
    coins                JSON,
    news_type            VARCHAR(32),
    event_tier           VARCHAR(4),
    score_market_impact  FLOAT,
    score_timeliness     FLOAT,
    score_hotness        FLOAT,
    score_authority      FLOAT,
    score_quality        FLOAT,
    importance_score     FLOAT,
    credibility_score    FLOAT,
    is_rumor             BOOLEAN      DEFAULT FALSE,
    rumor_reason         TEXT,
    sources              JSON         NOT NULL,
    source_names         JSON,
    source_count         INT          DEFAULT 1,
    is_verified          BOOLEAN      DEFAULT FALSE,
    language_origin      VARCHAR(8)   DEFAULT 'en',
    cluster_id           VARCHAR(64),
    merged_sources_count INT          DEFAULT 1,
    -- ── v1.3 去重字段 ──────────────────────────────────────────────
    event_subject        VARCHAR(128),          -- 规范化事件主体 slug，如 us_spot_btc_eth_etf
    event_action         VARCHAR(128),          -- 规范化事件动作 slug，如 net_outflow
    event_fingerprint    VARCHAR(64),           -- sha256(subject|action|event_date)[:16]，= id
    embedding            BLOB,                  -- 256 维 float32 向量（1024 字节），跨轮语义归并用
    social_interactions  INT          DEFAULT 0,-- 关联 X 推文互动总量（赞+转+评+引），H 因子用
    -- ── v1.5 币种市值标签（迁移 005，crawler/market_cap.py，纯查表 0 次 LLM 调用）──
    coin_metrics            JSON,               -- 每个 coin 一个对象：symbol/status/market_cap_usd/
                                                -- btc_ratio/cap_tier/asset_class/binance_spot/flags
                                                -- status ∈ ok/ambiguous/equity/unknown，匹配不到明确标记不猜
    primary_coin            VARCHAR(32),        -- 事件里市值最大的已匹配币（下面三列都是它的）
    primary_coin_market_cap DECIMAL(24,2),      -- 市值 USD。用 DECIMAL 是因为 FLOAT 7 位有效数字
                                                -- 存不下 1.29e12 而会在百万位抖动
    primary_coin_btc_ratio  DOUBLE,             -- 相对 BTC 的市值倍数（BTC 自己 = 1.0）
    coin_cap_tier           VARCHAR(16),        -- mega/large/mid/small/micro，阈值见 market_cap.CAP_TIERS
    -- ── v1.5 内容理解标签（迁移 005，crawler/pipeline.py 的 NEWS_SCHEMA）────────
    entities                JSON,               -- [{"name":"SEC","type":"organization"}, ...]
                                                -- type ∈ person/organization/project/chain/region/product
    sentiment               VARCHAR(16),        -- bullish/bearish/neutral，指对市场的方向性影响
    sentiment_score         FLOAT,              -- -1(极度利空) ~ +1(极度利多)，符号与 sentiment 一致
    sector_relevance        JSON,               -- [{"sector":"MEME","relevance":0.9,"anchor":"PNUT"}, ...]
                                                -- 「真相关才打」的量化：relevance < 0.55 的不进 sectors 列，
                                                -- 但仍留在这里供调阈值与 badcase 复盘
    impact_horizon          VARCHAR(16),        -- immediate/short_term/medium_term/long_term
    -- ── v1.6 市场归属（迁移 013，2026-07-28）───────────────────────────
    market_scope         VARCHAR(20) DEFAULT 'crypto',  -- crypto/us_stock/hk_stock/jp_stock/
                                                         -- kr_stock/macro_policy/general
                                                         -- 与 news_type（事件性质）正交，不要合并
    -- 真实性校验（migration 004；2026-07-26 review 发现基线漏收，补齐——
    -- 否则用本文件引导的新库会让 /api/news 的 EVENT_COLUMNS 白名单直接 500）
    verification_status     VARCHAR(16)  DEFAULT NULL,  -- VERIFIED/PROBABLE/UNVERIFIED/DISPUTED
    verification_score      FLOAT        DEFAULT NULL,
    verification_reason     TEXT,
    verification_flags      JSON,
    independent_source_count INT         DEFAULT 1,
    created_at           DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_date (date),
    INDEX idx_news_type (news_type),
    INDEX idx_market_scope (market_scope),
    INDEX idx_importance (importance_score DESC),
    INDEX idx_event_tier (event_tier),
    INDEX idx_is_rumor (is_rumor),
    INDEX idx_created (created_at DESC),
    INDEX idx_fingerprint (event_fingerprint),
    INDEX idx_primary_coin (primary_coin),
    INDEX idx_cap_tier (coin_cap_tier),
    INDEX idx_sentiment (sentiment),
    INDEX idx_verification (verification_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS x_raw_posts (
    tweet_id             VARCHAR(32)  PRIMARY KEY,
    news_event_id        VARCHAR(64),
    kol_username         VARCHAR(64)  NOT NULL,
    kol_display_name     VARCHAR(128),
    kol_followers_count  INT,
    kol_verified         BOOLEAN      DEFAULT FALSE,
    kol_profile_url      VARCHAR(256),
    tweet_title          TEXT,
    tweet_body           TEXT         NOT NULL,
    tweet_url            VARCHAR(512) NOT NULL,
    tweet_lang           VARCHAR(8),
    like_count           INT          DEFAULT 0,
    retweet_count        INT          DEFAULT 0,
    reply_count          INT          DEFAULT 0,
    quote_count          INT          DEFAULT 0,
    impression_count     INT          DEFAULT 0,
    published_at         DATETIME     NOT NULL,
    fetched_at           DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_kol (kol_username),
    INDEX idx_event (news_event_id),
    INDEX idx_published (published_at DESC),
    INDEX idx_likes (like_count DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id                   INT          AUTO_INCREMENT PRIMARY KEY,
    run_at               DATETIME     DEFAULT CURRENT_TIMESTAMP,
    raw_count            INT          DEFAULT 0,
    deduped_count        INT          DEFAULT 0,
    enriched_count       INT          DEFAULT 0,
    events_count         INT          DEFAULT 0,
    rumors_count         INT          DEFAULT 0,
    duration_seconds     FLOAT,
    status               VARCHAR(16)  DEFAULT 'success',
    error_msg            TEXT,
    -- v1.4 用量追踪字段（见 crawler/usage_tracker.py，官方 usage API 无权限访问，
    -- 改为应用层每次调用自己统计 resp.usage）
    llm_input_tokens     INT          DEFAULT 0,
    llm_output_tokens    INT          DEFAULT 0,
    llm_cached_tokens    INT          DEFAULT 0,
    embedding_tokens     INT          DEFAULT 0,
    estimated_cost_usd   DECIMAL(10,6) DEFAULT 0,
    stage_timings        JSON,        -- 各环节耗时秒数（migration 008）
    INDEX idx_run_at (run_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
