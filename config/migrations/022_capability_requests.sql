-- 022：原子能力申请单（ADR-003，2026-08-06）
--
-- 策略实验室「新增原子能力」tab 的数据层。三类申请（label 新标签 / quota 保量策略 /
-- rag 语料）共用一张表，kind 区分、payload 按类存 JSON——三类的字段差异大且都还在
-- 演化，各建一张表会把"加个字段"变成"加三次迁移"。
--
-- 状态机（本期刻意没有"自动生效"态）：
--   pending → approved →（Claude Code 按正常流程开发上线后）applied
--           ↘ rejected（decide_note 必填拒绝原因，列表对所有人可见）
--
-- 纯新增表：不改任何存量表结构，回滚 = DROP TABLE，不伤现有数据。
CREATE TABLE IF NOT EXISTS capability_requests (
    id            INT PRIMARY KEY AUTO_INCREMENT,
    kind          ENUM('label','quota','rag') NOT NULL,
    title         VARCHAR(120) NOT NULL,
    payload       JSON NOT NULL,
    status        ENUM('pending','approved','rejected','applied')
                  NOT NULL DEFAULT 'pending',
    submitted_by  VARCHAR(64) NOT NULL DEFAULT '',
    submitted_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at    DATETIME NULL,
    -- 拒绝原因 / 批准备注。产品要求"status 更新且所有人可见"，所以它不是审计
    -- 侧写，是列表页的一级展示字段。
    decide_note   TEXT NULL,
    -- 批准时生成的变更单（markdown）：需求原文 + 既定落地路径 + 预计改动文件 +
    -- 成本估算 + 测试与回滚方式。Claude Code 开发时读这里。
    change_order  MEDIUMTEXT NULL,
    applied_at    DATETIME NULL,
    KEY idx_status_time (status, submitted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
