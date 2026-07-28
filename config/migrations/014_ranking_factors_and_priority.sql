-- 014_ranking_factors_and_priority.sql —— 排序因子扩展 + 处理优先级队列
--
-- 对应 PRD-03 / ADR-001（2026-07-29）。三组改动一起加，因为它们是同一次
-- 「热度氛围改造」的产物：
--
--   A. raw_items_staging.priority —— 处理优先级。权威大盘媒体插队，
--      dxFeed 个股垫底。用优先级而不是过滤，是为了保留 Lawrence 要的大底池
--      （个股新闻今天没价值≠以后做个股页时没价值，过滤不可逆、优先级可逆）。
--
--   B. news_events.breadth_level / impact_score —— 两个新排序因子的落库位。
--      广度由 LLM 判（跨市场/单市场大盘/板块/多标的/单标的），冲击力由
--      「数值幅度正则 + 权威共振」算，都不是 LLM 直接给分。
--
--   C. market_scope 新增 social_signal —— 对外正名为「新闻类型」，
--      边界是「地缘冲突/自然灾害/社会事件，且必须有对市场的传导路径」。
--      枚举本身是 VARCHAR 不需要改结构，这里只更新列注释以免口径漂移。
--
-- 幂等：沿用 004/005/013 的存储过程写法（MySQL 8.0 不支持 ADD COLUMN IF NOT EXISTS）。
--
--   mysql -uroot -p crypto_news < config/migrations/014_ranking_factors_and_priority.sql

USE crypto_news;

DROP PROCEDURE IF EXISTS add_ranking_factor_columns;
DELIMITER //
CREATE PROCEDURE add_ranking_factor_columns()
BEGIN
    -- ── A. 处理优先级 ──────────────────────────────────────────────
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'raw_items_staging'
                     AND COLUMN_NAME = 'priority') THEN
        -- 0=权威大盘媒体 1=dxFeed大盘/ETF 2=加密头部+行情异动 3=其他 4=dxFeed个股
        -- 默认 3：新接入的源在没被显式归档之前走中间档，不会意外插队也不会饿死。
        ALTER TABLE raw_items_staging
            ADD COLUMN priority TINYINT NOT NULL DEFAULT 3
                COMMENT '处理优先级 0(最高)~4(最低)，见 crawler/staging.py SOURCE_PRIORITY';
    END IF;

    -- 消费顺序索引。ORDER BY priority ASC, fetched_at ASC 是热路径
    -- （每轮 pipeline 都要跑），没有这个索引会在积压几千条时全表排序。
    IF NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'raw_items_staging'
                     AND INDEX_NAME = 'idx_priority_fetched') THEN
        ALTER TABLE raw_items_staging
            ADD INDEX idx_priority_fetched (consumed_at, priority, fetched_at);
    END IF;

    -- dxFeed 条目命中的 symbol。优先级判定要靠它区分大盘(SPX/QQQ...)与个股，
    -- 抓取侧不记录就没法在入库时定档。非 dxFeed 来源为 NULL。
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'raw_items_staging'
                     AND COLUMN_NAME = 'matched_symbols') THEN
        ALTER TABLE raw_items_staging
            ADD COLUMN matched_symbols VARCHAR(255) DEFAULT NULL
                COMMENT 'dxFeed 命中的 symbol 逗号分隔，用于区分大盘/个股优先级';
    END IF;

    -- ── B. 两个新排序因子 ──────────────────────────────────────────
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND COLUMN_NAME = 'breadth_level') THEN
        ALTER TABLE news_events
            -- cross_market / market_index / sector / multi_asset / single_asset
            -- 由 LLM 判定，映射成 0-1 的 B 因子（见 crawler/scoring.py BREADTH_VALUES）
            ADD COLUMN breadth_level VARCHAR(20) DEFAULT NULL
                COMMENT '影响广度：cross_market/market_index/sector/multi_asset/single_asset',
            -- 广度因子 0-1（由 breadth_level 映射，见 scoring.BREADTH_VALUES）
            ADD COLUMN score_breadth FLOAT DEFAULT NULL
                COMMENT '广度因子 B，0-1',
            -- 冲击力 0-1 = 0.65*数值幅度 + 0.35*权威共振，纯计算无 LLM。
            -- 刻意叫 punch 不叫 impact：impact 已经被 score_market_impact（影响面 M）
            -- 占用，两个都叫 impact 会在代码和口径上长期混淆。
            ADD COLUMN score_punch FLOAT DEFAULT NULL
                COMMENT '冲击力因子 I，0-1，见 crawler/scoring.py compute_punch',
            -- 提取到的最大百分比幅度，留档便于复盘"为什么这条冲击力高"
            ADD COLUMN punch_magnitude_pct FLOAT DEFAULT NULL
                COMMENT '标题/摘要中提取到的最大涨跌幅百分比（绝对值）';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND INDEX_NAME = 'idx_breadth') THEN
        ALTER TABLE news_events ADD INDEX idx_breadth (breadth_level);
    END IF;
END //
DELIMITER ;

CALL add_ranking_factor_columns();
DROP PROCEDURE add_ranking_factor_columns;

-- ── C. market_scope 口径更新（新增 social_signal）────────────────────
-- 列类型不变（VARCHAR(20) 已够放 social_signal），只更新注释统一口径。
ALTER TABLE news_events MODIFY COLUMN market_scope VARCHAR(20) DEFAULT 'crypto'
    COMMENT '新闻类型（对外叫法）：crypto/us_stock/hk_stock/jp_stock/kr_stock/macro_policy/social_signal/general';
