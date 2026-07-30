-- 016_strategy_config.sql —— 排序策略配置化（2026-07-30）
--
-- 起因：Lawrence 要在策略实验室加一个「存为基线」按钮，点确认后把当前调好的
-- 那套参数变成全站默认。前提是**排序公式的参数必须真的可配置，而不是写死在
-- 代码里**——在此之前，七因子权重写死在 crawler/scoring.py 的
-- W_IMPACT/W_BREADTH/... 常量里，两个情绪加分系数写死在 crawler/market_mood.py，
-- 市场权重写死在 crawler/market_weight.py，新鲜度半衰期写死在
-- crawler/freshness.py。实验室能调，但调完只存在于那一次请求里，关掉页面就没了。
--
-- ## 为什么是一张「版本化的整份快照」表，而不是 key-value 参数表
--
-- 排序参数之间是**互相耦合**的：七个基础权重要归一化到 100%，两个加分项有
-- 合计封顶，市场权重和情绪权重共用同一套口径。key-value 表允许"改了 M 但
-- 忘了改 B"这种半完成状态，而排序公式在半完成状态下算出来的分没有任何意义。
-- 整份快照保证任何时刻读到的都是一套自洽的参数。
--
-- 同时这张表天然就是审计日志：每次存基线追加一行而不是原地改，
-- "上周五那版排序是什么参数"永远查得到，回滚就是把某个旧版本重新置为 active。
-- 这套模式直接沿用 012_persona_management.sql 的版本化思路（那边已经验证过
-- "版本+回滚不删历史"是对的）。
--
-- ## is_active 为什么允许多行为 0、但只允许一行为 1
--
-- 用**部分唯一索引**的等价写法：MySQL 没有 partial unique index，所以用
-- 生成列 active_flag —— is_active=1 时取固定值 1、否则取 NULL，再对它建唯一
-- 索引。NULL 在唯一索引里互不冲突，于是"最多一行 active"由数据库保证，
-- 而不是靠应用层记得先把旧的置 0（那种约束迟早会因为并发或漏改而破）。

CREATE TABLE IF NOT EXISTS strategy_config (
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  version       INT UNSIGNED NOT NULL COMMENT '自增版本号，从 1 开始',
  payload       JSON NOT NULL COMMENT '整份参数快照：base_weights/bonus/market_weights/freshness/mood',
  note          VARCHAR(255) NULL COMMENT '这版改了什么（存基线时可填）',
  created_by    VARCHAR(64) NOT NULL DEFAULT 'lab' COMMENT '来源：lab=策略实验室存基线，seed=初始种子',
  is_active     TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1=当前生效版本，全表最多一行',
  active_flag   TINYINT(1) AS (IF(is_active = 1, 1, NULL)) STORED
                COMMENT '仅为唯一索引服务：保证最多一行 is_active=1（见文件头说明）',
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_version (version),
  UNIQUE KEY uk_active (active_flag),
  KEY idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='排序策略参数的版本化快照。存基线追加新行并置 active，回滚=把旧版本重新置 active';

-- 种子：把**当前代码里写死的那套值**原样落成 v1，且置为 active。
--
-- 刻意用代码里的现行值而不是"我觉得更好的值"——这样上线这张表的瞬间，
-- 系统行为必须和上线前完全一致（配置化本身不该改变任何排序结果）。任何
-- 排序变化都应该来自之后主动存的新基线，而不是这次迁移的副作用。
-- 对应关系：
--   base_weights  ← crawler/scoring.py 的 W_IMPACT..W_QUAL（0.26/0.16/0.16/0.14/0.10/0.10/0.08）
--   bonus         ← crawler/market_mood.py 的 MOOD_ALIGN_BOOST / MOOD_REVERSAL_BOOST / BONUS_TOTAL_CAP
--   market_weights← crawler/market_weight.py 的 DEFAULT_MARKET_WEIGHTS
--   freshness     ← crawler/freshness.py 的 HALFLIFE_HOURS / MIN_MULTIPLIER
--   mood          ← crawler/market_mood.py 的 MOOD_LOOKBACK_HOURS；manual_override=null 表示用实时计算值
INSERT INTO strategy_config (version, payload, note, created_by, is_active)
SELECT 1,
  JSON_OBJECT(
    'base_weights', JSON_OBJECT('M',26,'B',16,'T',16,'I',14,'H',10,'A',10,'Q',8),
    'bonus',        JSON_OBJECT('k_align',0.25,'k_reversal',0.20,'cap',0.50),
    'market_weights', JSON_OBJECT(
        'us_stock',1.20,'crypto',1.00,'macro_policy',1.00,'social_signal',0.85,
        'general',0.70,'hk_stock',0.65,'jp_stock',0.60,'kr_stock',0.55),
    'freshness',    JSON_OBJECT('halflife_hours',48,'floor',0.15,'enabled',TRUE),
    'mood',         JSON_OBJECT('lookback_hours',24,'manual_override',NULL)
  ),
  '初始种子：与上线前代码里写死的值逐项对齐，配置化本身不改变任何排序结果',
  'seed', 1
WHERE NOT EXISTS (SELECT 1 FROM (SELECT 1) t WHERE (SELECT COUNT(*) FROM strategy_config) > 0);
