-- 迁移 007：评测/策略工具历史结果 + 全站埋点 + 反馈收集
--
-- 对应三张新表，一起加是因为都是同一批"结果保存 + 埋点统计 + 用户反馈"需求
-- （2026-07-26）的产物，实现见 api/history_tools.py：
--
--   A. tool_results          评测/策略工具的"保存结果"功能落地表。payload 原样
--      存调用方已经拿到手的响应 JSON，不做二次加工——不同 tool 的响应结构差异
--      很大（Duplicate Tester 是分组表格，LLM 评测室是多 persona 卡片，AB 对比
--      是重合度+GSB，策略实验室两个子工具是排序列表），没必要也不应该拆列存储。
--
--   B. analytics_events      全站埋点管道：page_view / tab_switch / tool_run 等。
--      meta 是 JSON，具体字段随 event_type 自由变化，这里不强约束 schema。
--
--   C. feedback_submissions  "Tell me more" 反馈模块：工具反馈 / 需求 / bad case。
--
--   mysql -uroot -p crypto_news < config/migrations/007_history_analytics.sql

USE crypto_news;

CREATE TABLE IF NOT EXISTS tool_results (
    id         BIGINT PRIMARY KEY AUTO_INCREMENT,
    tool       VARCHAR(32) NOT NULL,   -- duplicate_tester | llm_eval | ab_compare | lab_weight | lab_ab_compare
    label      VARCHAR(255),           -- 用户自定义备注，可为空
    payload    JSON NOT NULL,          -- 该工具那次调用的完整响应 JSON，原样存，不做二次加工
    cost_usd   DECIMAL(10,6) DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tool_created (tool, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS analytics_events (
    id         BIGINT PRIMARY KEY AUTO_INCREMENT,
    event_type VARCHAR(32) NOT NULL,   -- page_view | tab_switch | tool_run | feedback_submit 等
    page       VARCHAR(64),
    meta       JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_event_created (event_type, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS feedback_submissions (
    id           BIGINT PRIMARY KEY AUTO_INCREMENT,
    category     VARCHAR(32) NOT NULL,  -- 工具反馈 | 需求 | bad case 等，用户在下拉里选
    content      TEXT NOT NULL,
    page_context VARCHAR(128),          -- 提交时用户在哪个 tab/页面，方便定位上下文
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
