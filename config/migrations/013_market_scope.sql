-- 013_market_scope.sql —— 市场归属标签
--
-- 背景（2026-07-28，Lawrence 转达老板指示）：B9 从只爬币圈新闻扩展到接入
-- 美股/港股/日股/韩股/世界主要经济新闻，需要一个字段区分"这条事件属于
-- 哪个市场"，供前端做筛选、供排序做权威加权参考。这是一个新维度，跟已有的
-- news_type（market/policy/security/project/macro/other，判的是事件性质）
-- 完全不同、不能复用同一列——一条"美联储加息"新闻，news_type=macro，
-- market_scope=us_stock，两者独立正交。
--
-- 幂等：MySQL 8.0 不支持 ADD COLUMN IF NOT EXISTS，用存储过程包一层
-- （沿用 004/005 等既有迁移的写法）。
--
--   mysql -uroot -p crypto_news < config/migrations/013_market_scope.sql

USE crypto_news;

DROP PROCEDURE IF EXISTS add_market_scope_column;
DELIMITER //
CREATE PROCEDURE add_market_scope_column()
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND COLUMN_NAME = 'market_scope') THEN
        -- crypto / us_stock / hk_stock / jp_stock / kr_stock / macro_policy / general。
        -- 默认 crypto：本次迁移前的存量事件全部是币圈新闻，默认值天然语义正确，
        -- 不需要额外 UPDATE 回填。
        ALTER TABLE news_events
            ADD COLUMN market_scope VARCHAR(20) DEFAULT 'crypto'
                COMMENT '市场归属：crypto/us_stock/hk_stock/jp_stock/kr_stock/macro_policy/general';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND INDEX_NAME = 'idx_market_scope') THEN
        ALTER TABLE news_events ADD INDEX idx_market_scope (market_scope);
    END IF;
END //
DELIMITER ;

CALL add_market_scope_column();
DROP PROCEDURE add_market_scope_column;
