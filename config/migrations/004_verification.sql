-- 004_verification.sql —— 真实新闻验证字段（crawler/verification.py）
--
-- 背景：接入 x_search / web_search 两个新召回源后，信源不再是人工挑选的白名单，
-- 假新闻风险上升。原有的把关只有 LLM 单条主观判断（is_rumor / credibility_score）
-- 与只用于 H 因子加分的 source_count / is_verified，缺一套客观的验证结论。
--
-- 与既有字段的分工（都保留，不删不改）：
--   credibility_score / is_rumor  LLM 主观判断，现在只占 verification_score 的 10%
--   source_count / is_verified    按 name.split("/")[0] 去重的粗口径，仍供 H 因子用
--   independent_source_count      本次新增，按**机构**去重的严口径
--                                 （BlockBeats快讯 / BlockBeats文章 / X/BlockBeatsAsia
--                                  = 1 家，旧口径会算成 2~3 家）
--
-- 幂等：MySQL 8.0 不支持 ADD COLUMN IF NOT EXISTS，用存储过程包一层。

USE crypto_news;

DROP PROCEDURE IF EXISTS add_verification_columns;
DELIMITER //
CREATE PROCEDURE add_verification_columns()
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND COLUMN_NAME = 'verification_status') THEN
        ALTER TABLE news_events
            -- VERIFIED / PROBABLE / UNVERIFIED / DISPUTED；NULL = 尚未验证
            ADD COLUMN verification_status VARCHAR(16) DEFAULT NULL,
            -- 0~1 客观分：0.55·最强单源可信度 + 0.30·独立佐证 + 0.15·时间自洽，
            -- 再与 LLM credibility_score 按 9:1 混合
            ADD COLUMN verification_score FLOAT DEFAULT NULL,
            -- 中文可读判定依据，可直接透给前端做「未经证实 / 存在争议」提示
            ADD COLUMN verification_reason TEXT,
            -- 异常码 JSON 数组，如 ["TIME_STALE","SINGLE_LOW_TRUST_SOURCE"]
            ADD COLUMN verification_flags JSON,
            -- 按机构去重的独立信源数（严口径），与 source_count 并存
            ADD COLUMN independent_source_count INT DEFAULT 1;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'news_events'
                     AND INDEX_NAME = 'idx_verification') THEN
        -- 推荐流要按状态过滤/降权，单列索引即可；配合 importance_score 排序
        ALTER TABLE news_events ADD INDEX idx_verification (verification_status);
    END IF;
END //
DELIMITER ;

CALL add_verification_columns();
DROP PROCEDURE add_verification_columns;
