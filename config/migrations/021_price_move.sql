-- 021 冲击力语义字段落库（2026-08-02）
--
-- price_move 是 enrich 阶段 LLM 给出的"这个百分数是不是价格变动"的语义判断，
-- 用来根治靠正则+排除表猜幅度的老问题（排除表连补四轮仍在漏，一度让
-- "BIP-110 满额信号 100%" 这种协议投票阈值排到首屏第一）。
--
-- 存成 JSON 而不是拆三列：这三个字段是**一次判断的三个侧面**，必须同生共死
-- ——move_pct 只在 is_price_move=true 时有意义，拆开存会出现
-- "is_price_move=false 但 move_pct 有值" 这种自相矛盾的中间态。
ALTER TABLE news_events
  ADD COLUMN price_move JSON NULL
      COMMENT '{is_price_move, move_pct, move_horizon} —— LLM 语义判断，见 crawler/scoring.compute_punch';
