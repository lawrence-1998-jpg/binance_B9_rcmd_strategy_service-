-- 011_shift_utc_to_utc8.sql —— 把存量时间戳从 UTC 平移到 UTC+8。
--
-- 背景：Lawrence 要求"这个项目的所有时间都改成 utc+8"。上一轮只切了 VM 系统
-- 时区、cron 和 MySQL，**代码写入口径漏改**，于是：
--   · crawler 用 datetime.now(timezone.utc) 给 time_get_data 盖戳 → 一直是 UTC
--   · mysqld 在 2026-07-26 20:38:26 CST 才重启，之前 CURRENT_TIMESTAMP 也是 UTC
-- 症状：7/26 20:00 那轮跑成功了（20:13 写完），却被记成 12:13，前端「生产轮次」
-- 下拉里整轮消失，晚间轮的数据混进了早间轮的桶。
--
-- 边界很干净，不会误伤：
--   mysqld 重启前的 CURRENT_TIMESTAMP 最大值 = 12:38（UTC），
--   重启后的最小值 = 20:38（CST），两段之间不存在取值。
--   所以 "< 2026-07-26 20:38:26" 就等价于"这是个 UTC 值"。
--
-- 幂等：每张表都用一个 marker 记录已迁移，重复执行不会平移两次。

USE crypto_news;

CREATE TABLE IF NOT EXISTS schema_migrations (
    name       VARCHAR(128) PRIMARY KEY,
    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

DROP PROCEDURE IF EXISTS shift_utc_to_utc8;
DELIMITER //
CREATE PROCEDURE shift_utc_to_utc8()
BEGIN
    DECLARE boundary DATETIME DEFAULT '2026-07-26 20:38:26';

    IF NOT EXISTS (SELECT 1 FROM schema_migrations WHERE name = '011_shift_utc_to_utc8') THEN

        -- news_events：time_get_data / time_event 由 Python 写入，全部是 UTC；
        -- date 是 published_at 的日期部分，跟着 time_event 一起重算，
        -- 否则 date_from/date_to 过滤和 time_event 会对不上。
        UPDATE news_events
           SET time_get_data = DATE_ADD(time_get_data, INTERVAL 8 HOUR)
         WHERE time_get_data IS NOT NULL;
        UPDATE news_events
           SET time_event = DATE_ADD(time_event, INTERVAL 8 HOUR)
         WHERE time_event IS NOT NULL;
        UPDATE news_events
           SET date = DATE(time_event)
         WHERE time_event IS NOT NULL;
        UPDATE news_events
           SET created_at = DATE_ADD(created_at, INTERVAL 8 HOUR)
         WHERE created_at IS NOT NULL AND created_at < boundary;
        UPDATE news_events
           SET updated_at = DATE_ADD(updated_at, INTERVAL 8 HOUR)
         WHERE updated_at IS NOT NULL AND updated_at < boundary;

        -- pipeline_runs.run_at 走 MySQL 默认值，按边界判断
        UPDATE pipeline_runs
           SET run_at = DATE_ADD(run_at, INTERVAL 8 HOUR)
         WHERE run_at IS NOT NULL AND run_at < boundary;

        -- x_raw_posts：published_at 来自 X API（Python 转换，UTC）；fetched_at 走默认值
        UPDATE x_raw_posts
           SET published_at = DATE_ADD(published_at, INTERVAL 8 HOUR)
         WHERE published_at IS NOT NULL;
        UPDATE x_raw_posts
           SET fetched_at = DATE_ADD(fetched_at, INTERVAL 8 HOUR)
         WHERE fetched_at IS NOT NULL AND fetched_at < boundary;

        -- 以下几张表都是 CURRENT_TIMESTAMP 默认值，且 20:38 之后仍在写入，
        -- 必须按边界只平移前半段，否则会把已经正确的 CST 行推到未来。
        UPDATE analytics_events
           SET created_at = DATE_ADD(created_at, INTERVAL 8 HOUR)
         WHERE created_at IS NOT NULL AND created_at < boundary;

        UPDATE feedback_submissions
           SET created_at = DATE_ADD(created_at, INTERVAL 8 HOUR)
         WHERE created_at IS NOT NULL AND created_at < boundary;
        UPDATE feedback_submissions
           SET notified_at = DATE_ADD(notified_at, INTERVAL 8 HOUR)
         WHERE notified_at IS NOT NULL AND notified_at < boundary;

        UPDATE tool_results
           SET created_at = DATE_ADD(created_at, INTERVAL 8 HOUR)
         WHERE created_at IS NOT NULL AND created_at < boundary;

        UPDATE llm_enrich_cache
           SET created_at = DATE_ADD(created_at, INTERVAL 8 HOUR)
         WHERE created_at IS NOT NULL AND created_at < boundary;
        UPDATE llm_enrich_cache
           SET consumed_at = DATE_ADD(consumed_at, INTERVAL 8 HOUR)
         WHERE consumed_at IS NOT NULL AND consumed_at < boundary;

        UPDATE raw_items_staging
           SET fetched_at = DATE_ADD(fetched_at, INTERVAL 8 HOUR)
         WHERE fetched_at IS NOT NULL AND fetched_at < boundary;
        UPDATE raw_items_staging
           SET consumed_at = DATE_ADD(consumed_at, INTERVAL 8 HOUR)
         WHERE consumed_at IS NOT NULL AND consumed_at < boundary;

        INSERT INTO schema_migrations (name) VALUES ('011_shift_utc_to_utc8');
    END IF;
END //
DELIMITER ;

CALL shift_utc_to_utc8();
DROP PROCEDURE shift_utc_to_utc8;
