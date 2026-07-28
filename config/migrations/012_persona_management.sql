-- 迁移 012：评测 Agent（persona）管理 + 评测结果留档 + 校准闭环
--
-- 背景（2026-07-28，Lawrence）：LLM 评测室原来的 5 个 persona 是 api/eval_tools.py
-- 里的一段硬编码常量 —— 改一次人设要改代码 + 重启服务，评测结果只在浏览器里活着
-- （除非用户手动点"保存结果"），也没有任何机制把"用户觉得这个 agent 判得不对"
-- 这件事沉淀回 agent 本身。本次把这三件事补齐：人设进库可增删改查、每次评测自动
-- 留档、用户 comment 能反过来更新 agent。
--
--   mysql -uroot -p crypto_news < config/migrations/012_persona_management.sql
--
-- 五张表的关系：
--
--   eval_personas ──1:N──> eval_persona_versions   (每改一次留一份快照，可回滚)
--        │
--        └──1:N──> persona_eval_results <──N:1── persona_eval_runs
--                        │                        (一次评测任务 = 一条 run，
--                        │                         一个 persona 一条 result)
--                        └──1:N──> persona_calibrations  (用户对某条结果的校准意见)
--
-- 为什么 results 要单独一张表而不是像 tool_results 那样整坨存 JSON：
-- tool_results 的定位是"把用户看到的那个响应原样留个底"，查询需求只有"按 tool 和
-- 时间倒序列出来"。这里不一样 —— 需要按 persona 聚合算均分、算与人工标注的偏差、
-- 按版本号切分做校准前后对比，这些都是列级查询，塞进 JSON 里每次都要全表扫 + 应用层
-- 解析。所以拆列存，且刻意冗余一个 persona_version 列（见下）。

USE crypto_news;

-- ── A. persona 主表 ────────────────────────────────────────────────────
--
-- 人设拆成五个字段（人格/故事/偏好/记忆/心情）而不是塞一大段 system_prompt，
-- 是为了让"后台基于校准意见更新人格和偏好"这件事有明确的作用靶点 —— 归纳出来的
-- 结论要能精确写回 personality/preferences 这两列，而不是拿一整段 prompt 让模型
-- 重写（那样每次都会顺手改掉不该改的地方，几轮下来人设就漂了）。
--
-- prompt_override：留给"我就是要手写整段 prompt"的场景。非空时五要素只作展示，
-- 实际发给模型的是这一列。刻意不做成"覆盖某几个字段"的复杂合并语义。
CREATE TABLE IF NOT EXISTS eval_personas (
    id              VARCHAR(48) PRIMARY KEY,          -- slug，如 office_lady / swe_steady / pro_trader
    name            VARCHAR(64)  NOT NULL,
    emoji           VARCHAR(16)  DEFAULT '🙂',
    tagline         VARCHAR(160),                     -- 一句话标签，卡片上展示
    assets_usd      BIGINT       DEFAULT 0,           -- 资产规模（美元）；0 = 未设定
    personality     TEXT,                             -- 人格：性格底色、说话方式、决策风格
    story           TEXT,                             -- 故事：来历、经历过什么、为什么是现在这样
    preferences     TEXT,                             -- 偏好：想看什么、讨厌什么、打分倾向
    memory          TEXT,                             -- 记忆：长期设定，比如踩过的坑、认准的信源
    mood            TEXT,                             -- 心情：当前所处的情绪状态（会影响评分宽严）
    calib_memory    TEXT,                             -- 校准记忆：用户 comment 的累积，系统自动维护，不建议手改
    prompt_override TEXT,                             -- 非空则直接当 system_prompt，忽略上面五要素的拼装
    is_active       TINYINT(1)   DEFAULT 1,           -- 0 = 停用（不参与评测，但历史记录还在）
    is_builtin      TINYINT(1)   DEFAULT 0,           -- 内置三人组，删除时前端给二次确认
    sort_order      INT          DEFAULT 100,
    version         INT          DEFAULT 1,           -- 当前版本号，每次改动 +1
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_active_sort (is_active, sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── B. persona 版本快照 ────────────────────────────────────────────────
--
-- 每次改动（手改 / 校准归纳 / 文件导入 / 回滚）都留一份完整快照。回滚不是"删掉
-- 新版本"，而是"把旧快照的内容再写一遍并产生一个更新的版本号"——所以版本序列
-- 永远只增不减，审计链完整。
CREATE TABLE IF NOT EXISTS eval_persona_versions (
    id            BIGINT PRIMARY KEY AUTO_INCREMENT,
    persona_id    VARCHAR(48) NOT NULL,
    version       INT         NOT NULL,
    snapshot      JSON        NOT NULL,      -- 那一版的完整字段
    change_note   VARCHAR(512),              -- 人话说明这次改了什么
    change_source VARCHAR(24) DEFAULT 'manual',  -- seed | manual | calibration | file_import | rollback
    created_at    DATETIME    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_persona_version (persona_id, version),
    INDEX idx_persona_created (persona_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── C. 评测任务 ────────────────────────────────────────────────────────
--
-- 一次 persona-eval 调用 = 一条 run。批量评测时 N 条新闻产生 N 条 run，共享同一个
-- batch_uid，这样批量矩阵既能整体展示、单条也还是标准的评测记录，不需要为批量
-- 另起一套表。
CREATE TABLE IF NOT EXISTS persona_eval_runs (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    run_uid     VARCHAR(36)  NOT NULL UNIQUE,  -- 对外引用用，前端不碰自增主键
    input_mode  VARCHAR(16)  NOT NULL,         -- text | image | event_id
    event_id    VARCHAR(64),                   -- input_mode=event_id 时有，用来关联生产库做效度分析
    news_title  VARCHAR(512),                  -- 从正文截的标题，历史列表展示用
    news_text   MEDIUMTEXT,
    batch_uid   VARCHAR(36),                   -- 批量评测时同批共享；单条评测为 NULL
    importance_score DECIMAL(6,4),             -- input_mode=event_id 时抄一份生产分，算相关性用
    cost_usd    DECIMAL(10,6) DEFAULT 0,
    model       VARCHAR(48),
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_created (created_at),
    INDEX idx_batch (batch_uid),
    INDEX idx_event (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── D. 单个 persona 的评测结果 ─────────────────────────────────────────
--
-- persona_version 是刻意的冗余：它记录"这条结果是拿哪一版人设跑出来的"。没有它就
-- 没法做校准前后对比 —— 人设改过之后，历史结果会被误当成新人设的表现，校准到底
-- 有没有让 agent 更贴近人工判断就永远说不清。
--
-- human_score 是人工标注基准（可空）：用户认为这个人群实际应该打几分。它同时是
-- 校准闭环的目标函数 —— |score - human_score| 的均值（MAE）就是这个 agent 当前的
-- 偏差，校准有没有效看这个数字降没降。
CREATE TABLE IF NOT EXISTS persona_eval_results (
    id                     BIGINT PRIMARY KEY AUTO_INCREMENT,
    run_id                 BIGINT      NOT NULL,
    persona_id             VARCHAR(48) NOT NULL,
    persona_version        INT         DEFAULT 1,
    score                  INT,
    is_understandable      TINYINT(1),
    qualitative_assessment TEXT,
    understandable_reason  TEXT,
    improvement_suggestion TEXT,
    error                  VARCHAR(512),   -- 该 persona 这次调用失败时的原因；非空时上面几列为 NULL
    human_score            INT,            -- 人工标注基准分，可空
    human_score_at         DATETIME,
    created_at             DATETIME    DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_run (run_id),
    INDEX idx_persona_created (persona_id, created_at),
    INDEX idx_persona_version (persona_id, persona_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── E. 校准意见 ────────────────────────────────────────────────────────
--
-- 两段式生效，这是本次设计的关键取舍：
--   1) 提交即生效（零成本）：comment 立刻追加进 eval_personas.calib_memory，下一次
--      评测的 system_prompt 自动带上。用户点完就能看到 agent 变了，不用等、不花钱。
--   2) 攒够再归纳（一次 LLM 调用）：点"归纳进人格"时，把所有 applied_version IS NULL
--      的校准一次性喂给模型，让它改写 personality/preferences 两列，产出新版本。
--      归纳完这些行的 applied_version 被打上版本号，不会被重复归纳。
--
-- 为什么不做成"每提交一条就调一次 LLM 改人设"：每条校准都触发一次全量人设重写，
-- 几轮之后人设必然漂移（模型每次都会顺手润色不该动的地方），而且贵。
CREATE TABLE IF NOT EXISTS persona_calibrations (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    persona_id      VARCHAR(48) NOT NULL,
    result_id       BIGINT,          -- 关联到具体某条评测结果；为空表示是针对该 agent 的泛化意见
    comment         TEXT NOT NULL,
    suggested_score INT,             -- 用户认为该打几分，可空
    applied_version INT,             -- 已被归纳进哪一版人设；NULL = 尚未归纳
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_persona_applied (persona_id, applied_version),
    INDEX idx_result (result_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
