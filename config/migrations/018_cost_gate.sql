-- 018 成本硬闸（ADR-002 块 A）——2026-08-02
--
-- 三张改动，对应需求的三件事：
--   ① runtime_flags        —— "是否使用个人 API key"开关，DB 里改立刻生效
--   ② llm_credentials_meta —— 公司 key 的**元数据**（到期日/健康度），永不存 key 本身
--   ③ raw_items_staging    —— 加 defer 账本列，"停掉后能有记录/可查"
--
-- 本迁移**不改变任何现有行为**：开关行默认 value='0'（关闭个人 key）与代码里的
-- fail-closed 默认一致，新列全部可空。行为变化只能来自代码侧接上闸口。

-- ── ① 运行时开关 ────────────────────────────────────────────────────
-- 为什么单独一张表而不是塞进 strategy_config：strategy_config 是**排序策略**的
-- 版本化配置（要做版本对比、回滚、部署），而这里是**运行时开关**，语义完全不同，
-- 混在一起会让"部署某个策略版本"意外连带改动成本闸——那是灾难性的耦合。
CREATE TABLE IF NOT EXISTS runtime_flags (
  flag_key    VARCHAR(64)  NOT NULL PRIMARY KEY,
  flag_value  VARCHAR(255) NOT NULL,
  -- 到点自动失效。个人 key 是"紧急才用"，而人在救火时最容易忘记关回去——
  -- 把"忘记关"从流程纪律变成机制保证：过期即视为关闭，不需要任何人记得。
  expires_at  DATETIME     NULL,
  updated_by  VARCHAR(64)  NULL,
  note        TEXT         NULL,
  updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                           ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='运行时开关。成本闸相关，与 strategy_config(排序策略)刻意分开';

-- 默认关闭。与 crawler/llm_gate.py 的 fail-closed 默认一致——
-- 表读不到、行不存在、值解析失败，一律当"关闭"处理。
INSERT INTO runtime_flags (flag_key, flag_value, expires_at, updated_by, note)
VALUES ('allow_personal_key', '0', NULL, 'migration-018',
        '个人 OpenAI key 总闸。0=禁用(默认,任何异常也回落到这里) 1=紧急启用。'
        '启用必须带 expires_at，见 llm_gate.enable()')
ON DUPLICATE KEY UPDATE flag_key = flag_key;   -- 已存在则原样保留，不覆盖运行中的值

-- 紧急模式的两道边界，做成可调配置而不是写死在代码里
INSERT INTO runtime_flags (flag_key, flag_value, updated_by, note) VALUES
  ('emergency_max_priority', '2', 'migration-018',
   '紧急放行的 staging.priority 上限(含)。0=权威大盘 1=大盘指数 2=加密头部 '
   '3=长尾 4=个股。实测 P0-P2 占全量 28.3%'),
  ('emergency_daily_item_cap', '2000', 'migration-018',
   '紧急模式单日最多用个人 key 处理多少条。防"开着的几小时里量突然暴涨"')
ON DUPLICATE KEY UPDATE flag_key = flag_key;

-- ── ② 公司 key 元数据（不含密钥本身）────────────────────────────────
-- 秘密留在 Mac（~/.b9/credentials.json，600）。理由不是安全加固（那是红线外），
-- 而是**只有 Mac 用得上公司 key**（VM 连不通内网网关），把只有 Mac 能用的秘密
-- 复制进挂着公网隧道的 VM，纯粹白扩大暴露面、零收益。
-- 这张表只承载观测与告警：还剩几天到期、上次成功调用是什么时候、连续失败几次。
CREATE TABLE IF NOT EXISTS llm_credentials_meta (
  name                 VARCHAR(64) NOT NULL PRIMARY KEY,
  provider             VARCHAR(32) NOT NULL DEFAULT 'litellm-gateway',
  status               VARCHAR(16) NOT NULL DEFAULT 'active',   -- active/expired/disabled
  expires_at           DATE        NULL,
  last_ok_at           DATETIME    NULL,
  last_error           TEXT        NULL,
  consecutive_failures INT         NOT NULL DEFAULT 0,
  items_processed      BIGINT      NOT NULL DEFAULT 0,
  updated_at           DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP
                                   ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_status_expires (status, expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='公司 key 元数据(到期/健康度)。**永不存 key 本身**，密钥在 Mac 本地';

-- ── ③ defer 账本：为什么这条还没被处理 ──────────────────────────────
-- staging 表本身就是待办账本（consumed_at IS NULL = 待处理），缺的只是
-- "为什么还没处理"。不新建队列表，避免两套状态互相打架。
ALTER TABLE raw_items_staging
  ADD COLUMN deferred_count   INT         NOT NULL DEFAULT 0
      COMMENT '因成本闸被跳过的次数',
  ADD COLUMN last_deferred_at DATETIME    NULL
      COMMENT '最后一次被跳过的时间',
  ADD COLUMN defer_reason     VARCHAR(64) NULL
      COMMENT '跳过原因: personal_key_disabled / below_emergency_priority / daily_cap_reached';

-- 积压查询要按"最老未消费"扫，补一个复合索引。
-- 窗口从 7 天放宽到 30 天后这张表会显著变大（约 6000 条/天 → 30 天约 18 万行），
-- 没有索引的话 backlog 端点和 fetch_staged_items 都会退化成全表扫。
ALTER TABLE raw_items_staging
  ADD INDEX idx_unconsumed_age (consumed_at, fetched_at);
