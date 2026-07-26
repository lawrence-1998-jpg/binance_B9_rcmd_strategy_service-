-- 008_stage_timings.sql —— 补建 pipeline_runs.stage_timings 列。
--
-- 背景：2026-07-26 给 run_pipeline() 加了各环节耗时统计（pipeline.py 里的 lap()），
-- storage.record_run() 也已经在写这一列，但**当时漏了建列的迁移**。record_run 的
-- 写库整体包在 try/except 里，所以这个错误被静默吞掉了 —— 表现是日志里能看到
-- "Stage timings (s): {...}"，但库里查不到，直到做前端流程图标注时才发现。
--
-- 教训同 P2（改 schema 要同步）：加字段时「写入代码」和「建列迁移」必须成对提交。
--
-- 幂等：MySQL 8.0 不支持 ADD COLUMN IF NOT EXISTS，用存储过程包一层（写法同
-- 004_verification.sql）。原来这里是一条裸 ALTER，是全套迁移里唯一不幂等的一个：
-- 按顺序重跑整个 migrations 目录时会在这里报 1060 Duplicate column name 中断，
-- 后面的 009 就不会执行了。补建迁移最容易被重复执行，更不能省这一层。
--
--   mysql -uroot -p crypto_news < config/migrations/008_stage_timings.sql

USE crypto_news;

DROP PROCEDURE IF EXISTS add_stage_timings_column;
DELIMITER //
CREATE PROCEDURE add_stage_timings_column()
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'pipeline_runs'
                     AND COLUMN_NAME = 'stage_timings') THEN
        ALTER TABLE pipeline_runs
            ADD COLUMN stage_timings JSON NULL
                COMMENT '各环节耗时秒数，如 {"fetch":245.35,"llm_enrich":899.28}';
    END IF;
END //
DELIMITER ;

CALL add_stage_timings_column();
DROP PROCEDURE add_stage_timings_column;
