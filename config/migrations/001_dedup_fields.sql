-- 迁移 001：去重重构所需字段（schema v1.2 → v1.3）
--
-- 对应 crawler/dedup.py 的四层去重管线。
-- 幂等：重复执行不会报错（MySQL 8 不支持 ADD COLUMN IF NOT EXISTS，
-- 这里查 information_schema 后用动态 SQL 实现同等效果）。
--
--   mysql -uroot -p crypto_news < config/migrations/001_dedup_fields.sql

USE crypto_news;

DROP PROCEDURE IF EXISTS _migrate_001;

DELIMITER $$

CREATE PROCEDURE _migrate_001()
BEGIN
    -- 已存在则跳过该列
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND COLUMN_NAME = 'event_subject') THEN
        ALTER TABLE news_events
            ADD COLUMN event_subject VARCHAR(128) AFTER merged_sources_count;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND COLUMN_NAME = 'event_action') THEN
        ALTER TABLE news_events
            ADD COLUMN event_action VARCHAR(128) AFTER event_subject;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND COLUMN_NAME = 'event_fingerprint') THEN
        ALTER TABLE news_events
            ADD COLUMN event_fingerprint VARCHAR(64) AFTER event_action;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND COLUMN_NAME = 'embedding') THEN
        ALTER TABLE news_events
            ADD COLUMN embedding BLOB AFTER event_fingerprint;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND COLUMN_NAME = 'social_interactions') THEN
        ALTER TABLE news_events
            ADD COLUMN social_interactions INT DEFAULT 0 AFTER embedding;
    END IF;

    -- 跨轮归并每轮都要按指纹查近 72h 的行，没索引会全表扫
    IF NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND INDEX_NAME = 'idx_fingerprint') THEN
        ALTER TABLE news_events ADD INDEX idx_fingerprint (event_fingerprint);
    END IF;
END$$

DELIMITER ;

CALL _migrate_001();
DROP PROCEDURE _migrate_001;
