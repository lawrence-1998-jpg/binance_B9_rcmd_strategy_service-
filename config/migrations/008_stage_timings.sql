-- 补建 pipeline_runs.stage_timings 列。
--
-- 背景：2026-07-26 给 run_pipeline() 加了各环节耗时统计（pipeline.py 里的 lap()），
-- storage.record_run() 也已经在写这一列，但**当时漏了建列的迁移**。record_run 的
-- 写库整体包在 try/except 里，所以这个错误被静默吞掉了 —— 表现是日志里能看到
-- "Stage timings (s): {...}"，但库里查不到，直到做前端流程图标注时才发现。
--
-- 教训同 P2（改 schema 要同步）：加字段时「写入代码」和「建列迁移」必须成对提交。

ALTER TABLE pipeline_runs
  ADD COLUMN stage_timings JSON NULL COMMENT '各环节耗时秒数，如 {"fetch":245.35,"llm_enrich":899.28}';
