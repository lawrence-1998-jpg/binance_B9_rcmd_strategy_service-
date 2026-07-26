-- 005_coin_metrics.sql —— 币种市值标签 + 内容理解标签
--
-- 两组字段一起加，因为它们是同一次「内容理解与标签体系增强」的产物：
--
--   A. 币种市值标签（crawler/market_cap.py，纯查表，0 次 LLM 调用）
--      产品要求「所有涉及具体【币】的，都加上【市场价值】和【相对于 BTC 的
--      xx 倍市值】标签」。市值是客观数字，绝不让 LLM 猜。
--
--   B. 内容理解标签（crawler/pipeline.py 的 NEWS_SCHEMA / SYSTEM_PROMPT）
--      实体 / 情绪 / 板块相关度。其中 sector_relevance 是「真相关才打」的量化落地：
--      LLM 给每个板块打相关度分并写出判定锚点，低于阈值的不进 sectors 列。
--      sectors 列本身保持不变（仍是过滤后的字符串数组），前端无需改造。
--
-- 幂等：MySQL 8.0 不支持 ADD COLUMN IF NOT EXISTS，用存储过程包一层。
--
--   mysql -uroot -p crypto_news < config/migrations/005_coin_metrics.sql

USE crypto_news;

DROP PROCEDURE IF EXISTS add_coin_metric_columns;
DELIMITER //
CREATE PROCEDURE add_coin_metric_columns()
BEGIN
    -- ── A. 市值标签 ────────────────────────────────────────────────
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND COLUMN_NAME = 'coin_metrics') THEN
        ALTER TABLE news_events
            -- 每个 coin 一个对象：symbol / status / market_cap_usd / btc_ratio /
            -- cap_tier / asset_class / binance_spot / flags。
            -- 用 JSON 是因为一个事件可能涉及多个币（实测最多 6 个）。
            -- status ∈ ok / ambiguous / equity / unknown —— 匹配不到时**明确标记**，
            -- 不给市值数字，见 market_cap.py 顶部的四道消歧闸。
            ADD COLUMN coin_metrics JSON,
            -- 以下四列是从 coin_metrics 里抽出来的标量，纯粹为了让 SQL 能排序/
            -- 过滤（JSON 列建不了普通索引）。取事件里市值最大的那个已匹配币。
            ADD COLUMN primary_coin VARCHAR(32) DEFAULT NULL,
            -- DECIMAL 而非 FLOAT：BTC 市值 1.29e12，FLOAT 只有 7 位有效数字，
            -- 存进去会掉到百万位精度，前端展示「$1,290,155,000,000」会抖动
            ADD COLUMN primary_coin_market_cap DECIMAL(24,2) DEFAULT NULL,
            -- 相对 BTC 的市值倍数（BTC 自己 = 1.0）。绝大多数币 <0.01，
            -- 用 DOUBLE 保住小数位
            ADD COLUMN primary_coin_btc_ratio DOUBLE DEFAULT NULL,
            -- mega / large / mid / micro / small，阈值依据见 market_cap.CAP_TIERS
            ADD COLUMN coin_cap_tier VARCHAR(16) DEFAULT NULL;
    END IF;

    -- ── B. 内容理解标签 ────────────────────────────────────────────
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND COLUMN_NAME = 'entities') THEN
        ALTER TABLE news_events
            -- [{"name":"SEC","type":"organization"}, ...]
            -- type ∈ person / organization / project / chain / region / product
            ADD COLUMN entities JSON,
            -- bullish / bearish / neutral —— 对加密市场的方向性影响，
            -- 不是文章语气（"暴跌" 的中性陈述仍是 bearish）
            ADD COLUMN sentiment VARCHAR(16) DEFAULT NULL,
            -- -1(极度利空) ~ +1(极度利多)，符号与 sentiment 一致，绝对值是强度
            ADD COLUMN sentiment_score FLOAT DEFAULT NULL,
            -- [{"sector":"MEME","relevance":0.9,"anchor":"PNUT"}, ...]
            -- 「真相关才打」的量化：relevance < 0.55 的不会进 sectors 列，
            -- 但仍保留在这里供调阈值和 badcase 复盘。
            -- 0.55 是唯一正确的数字，以 pipeline.SECTOR_PUBLISH_THRESHOLD 为准
            -- （这里原来写的 0.6 是笔误）。阈值漂移在本项目吃过大亏——去重那次
            -- 文档写 0.65、实测该取 0.82，照文档配就废掉了整层去重，所以只要
            -- 看到两处阈值对不上，一律以代码常量为准并回来订正注释。
            ADD COLUMN sector_relevance JSON,
            -- immediate(<24h) / short_term(1-7d) / medium_term(1-4w) / long_term(>1m)
            -- 市场影响兑现的时间尺度，推荐流做「时效性 vs 重要性」权衡时用
            ADD COLUMN impact_horizon VARCHAR(16) DEFAULT NULL;
    END IF;

    -- ── 索引 ───────────────────────────────────────────────────────
    IF NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND INDEX_NAME = 'idx_primary_coin') THEN
        -- 「只看 BTC 相关」「只看大盘币新闻」是最高频的两个筛选维度
        ALTER TABLE news_events ADD INDEX idx_primary_coin (primary_coin);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND INDEX_NAME = 'idx_cap_tier') THEN
        ALTER TABLE news_events ADD INDEX idx_cap_tier (coin_cap_tier);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND INDEX_NAME = 'idx_sentiment') THEN
        ALTER TABLE news_events ADD INDEX idx_sentiment (sentiment);
    END IF;
END //
DELIMITER ;

CALL add_coin_metric_columns();
DROP PROCEDURE add_coin_metric_columns;
