-- 迁移 006：原始条目存档表
--
-- 对应 crawler/staging.py。解耦"抓取频率"和"LLM 处理频率"：免费源（RSS/HTML/
-- 搜索引擎/行情信号）可以高频抓取先存到这张表，主 pipeline 仍按现有节奏
-- （每 12 小时）批量消费存档 + 过一次 LLM，成本不变但不再受限于抓取窗口对齐。
--
--   mysql -uroot -p crypto_news < config/migrations/006_raw_staging.sql

USE crypto_news;

CREATE TABLE IF NOT EXISTS raw_items_staging (
    id           BIGINT       AUTO_INCREMENT PRIMARY KEY,
    source       VARCHAR(64)  NOT NULL,
    title        TEXT         NOT NULL,
    -- Google News 的 RSS 链接是 base64 编码的长路径，实测超过 1000 字符，
    -- 用 TEXT 而非 VARCHAR——唯一性约束不靠这列，靠下面的 url_hash
    url          TEXT         NOT NULL,
    url_hash     CHAR(64)     NOT NULL,
    summary      TEXT,
    published_at VARCHAR(64),   -- 原样存 ISO8601 字符串，消费时再解析，避免时区转换损耗信息
    lang         VARCHAR(8),
    authority    INT          DEFAULT 3,
    type         VARCHAR(16),
    fetched_at   DATETIME     DEFAULT CURRENT_TIMESTAMP,
    consumed_at  DATETIME     NULL,   -- NULL = 尚未被主 pipeline 消费
    UNIQUE KEY uk_url_hash (url_hash),
    INDEX idx_consumed (consumed_at),
    INDEX idx_fetched (fetched_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
