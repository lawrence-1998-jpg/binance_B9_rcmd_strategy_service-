-- 迁移 002：OpenAI 用量与成本追踪字段
--
-- 对应 crawler/usage_tracker.py。官方 usage/costs API 权限不够（403 缺
-- api.usage.read scope），改为应用层每次调用自己统计，写进这里。
--
--   mysql -uroot -p crypto_news < config/migrations/002_usage_tracking.sql

USE crypto_news;

DROP PROCEDURE IF EXISTS _migrate_002;

DELIMITER $$

CREATE PROCEDURE _migrate_002()
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'pipeline_runs'
                     AND COLUMN_NAME = 'llm_input_tokens') THEN
        ALTER TABLE pipeline_runs ADD COLUMN llm_input_tokens INT DEFAULT 0 AFTER error_msg;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'pipeline_runs'
                     AND COLUMN_NAME = 'llm_output_tokens') THEN
        ALTER TABLE pipeline_runs ADD COLUMN llm_output_tokens INT DEFAULT 0 AFTER llm_input_tokens;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'pipeline_runs'
                     AND COLUMN_NAME = 'llm_cached_tokens') THEN
        ALTER TABLE pipeline_runs ADD COLUMN llm_cached_tokens INT DEFAULT 0 AFTER llm_output_tokens;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'pipeline_runs'
                     AND COLUMN_NAME = 'embedding_tokens') THEN
        ALTER TABLE pipeline_runs ADD COLUMN embedding_tokens INT DEFAULT 0 AFTER llm_cached_tokens;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'pipeline_runs'
                     AND COLUMN_NAME = 'estimated_cost_usd') THEN
        ALTER TABLE pipeline_runs ADD COLUMN estimated_cost_usd DECIMAL(10,6) DEFAULT 0 AFTER embedding_tokens;
    END IF;
END$$

DELIMITER ;

CALL _migrate_002();
DROP PROCEDURE _migrate_002;
