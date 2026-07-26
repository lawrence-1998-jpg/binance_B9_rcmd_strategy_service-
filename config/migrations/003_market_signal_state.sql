-- 003_market_signal_state.sql —— 行情异动事件生成模块（crawler/market_signals.py）
-- 的跨轮状态表
--
-- （文件头原本自称"迁移 002"，是复制上一个迁移时漏改的：002 是 usage_tracking，
--   照着底下那行示例命令跑会执行错文件。2026-07-26 订正。）
--
-- 用途：market_signals 每轮（现由 scripts/stage_fetch.py 每 2 小时驱动）都要跨轮
-- 记住三类状态才能做抑制/去重：
--   1) emitted —— 某个 (信号类型,币,方向) 上次播报的时间和幅度，用于冷却期判断
--      与"幅度扩大才提前解禁"的升级豁免
--   2) price   —— 某个交易对上一轮的收盘价，用于判断这一轮是否发生了"整数关口
--      的真实穿越"（而不是价格一直趴在关口下方就每轮都播）
--   3) oi      —— 某个永续合约上一轮的持仓量快照，免费接口只给当前值不给历史
--      序列，只能自己攒
--
-- 用一张通用 KV 表承载这三类，用 state_kind 区分，避免建三张结构几乎相同的表。
-- 幂等：重复执行不会报错。
--
--   mysql -uroot -p crypto_news < config/migrations/003_market_signal_state.sql

USE crypto_news;

CREATE TABLE IF NOT EXISTS market_signal_state (
    state_key       VARCHAR(191)  NOT NULL,
    state_kind      VARCHAR(16)   NOT NULL,   -- 'emitted' | 'price' | 'oi'
    -- emitted 的量纲**随 kind 而变**：price_move/oi_jump 等是百分比，liquidation
    -- 是美元金额。升级豁免的判定必须按量纲分别处理，见 market_signals.allows()。
    numeric_value   DOUBLE        NOT NULL,   -- emitted→幅度(%)或金额(USD), price→收盘价, oi→持仓量USD
    -- 应用侧写入时**显式传 naive UTC**（market_signals._now_naive()），不依赖下面
    -- 这两个 CURRENT_TIMESTAMP —— 它们取 MySQL 服务器时区，和读回来做减法用的
    -- UTC 对不上就会让冷却期整体偏移。这里保留只是兜底给手工 INSERT 用。
    updated_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                   ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (state_kind, state_key),
    INDEX idx_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='crawler/market_signals.py 跨轮状态：冷却/价格基线/持仓量基线';
