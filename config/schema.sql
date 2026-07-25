-- 币圈新闻爬虫 MySQL Schema v1.2
-- Database: crypto_news

USE crypto_news;

CREATE TABLE IF NOT EXISTS news_events (
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
    created_at           DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_date (date),
    INDEX idx_news_type (news_type),
    INDEX idx_importance (importance_score DESC),
    INDEX idx_event_tier (event_tier),
    INDEX idx_is_rumor (is_rumor),
    INDEX idx_created (created_at DESC)
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
    INDEX idx_run_at (run_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
