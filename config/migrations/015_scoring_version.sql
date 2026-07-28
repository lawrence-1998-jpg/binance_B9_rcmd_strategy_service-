-- 015_scoring_version.sql —— 给持久化打分加版本标记（2026-07-29）
--
-- 起因见 crawler/scoring.py 的 SCORING_VERSION 注释：`importance_score` 是
-- 由其它列算出来后写回库的派生值，公式改过三次，但老行从来没有重算过。
-- 事发时全库 3174 行里只有 402 行（13%）是按现行公式算的，而库里**没有任何
-- 字段能告诉你某一行是哪个版本算的**——只能反算比对去猜。
--
-- 这一列把"这行的分是哪个版本算的"从一次考古变成一次 WHERE 查询：
--   SELECT COUNT(*) FROM news_events WHERE scoring_version < 2;
--
-- 存量统一标 2：015 之前已经由 scripts/rescore_factors.py 全量重算到七因子
-- 口径（3168/3168 逐行比对吻合，误差 < 0.002），所以这个标记是真的，不是
-- 拍脑袋填的默认值。**如果没跑过重算就上这个 migration，不要标 2**——
-- 那样只是把"不知道"伪装成"已知"，比没有这一列更糟。

ALTER TABLE news_events
  ADD COLUMN scoring_version TINYINT UNSIGNED NOT NULL DEFAULT 2
    COMMENT '打分公式版本：1=五因子(M/T/H/A/Q)，2=七因子(+B广度 +I冲击力)。改公式必须同步 crawler/scoring.py 的 SCORING_VERSION 并重算存量',
  ADD INDEX idx_scoring_version (scoring_version);

-- 存量已由 rescore_factors.py 重算过，显式写一遍表明这是核对过的结论
UPDATE news_events SET scoring_version = 2 WHERE score_market_impact IS NOT NULL;
