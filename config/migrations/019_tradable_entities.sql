-- 019 交易实体（ADR-002 块 B）——2026-08-02
--
-- 老板反馈排序结果"刺激标的物交易的感觉不足"。根因实测：占池 50% 的美股内容
-- 标的物覆盖率只有 0.8%（coins 字段按设计只抓加密 ticker），而 Benzinga 编辑部
-- 标注的真实 ticker（98.1% 覆盖）一直躺在 raw_items_staging.matched_symbols 里
-- 被丢弃。这一列把它接进来。
--
-- 结构：[{"symbol":"NVDA","name":"英伟达","market":"us_stock","venue":"US",
--         "tradable":true,"source":"editorial_ticker"}, ...]
-- 判据见 crawler/tradable.py：加密看 binance_spot、美股看大盘蓝筹白名单。

ALTER TABLE news_events
  ADD COLUMN tradable_entities JSON NULL
      COMMENT '可交易标的物列表，见 crawler/tradable.py。tradable=true 表示币安用户真买得到';

-- 加分项要按"有没有可交易标的"快速筛，冗余一个标量列避免每次解 JSON。
-- 值由 pipeline 写入时一并算好（tradable.tradable_count），不做生成列——
-- 生成列在 JSON 上的表达式索引跨 MySQL 版本行为不一致，踩过一次不再用。
ALTER TABLE news_events
  ADD COLUMN tradable_count TINYINT UNSIGNED NOT NULL DEFAULT 0
      COMMENT '可交易标的数量（tradable=true 的个数），排序加分项直接读它';

ALTER TABLE news_events
  ADD INDEX idx_tradable (tradable_count, date);
