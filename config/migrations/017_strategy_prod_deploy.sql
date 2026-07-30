-- 017_strategy_prod_deploy.sql —— 基线"部署到生产"标记（2026-07-30）
--
-- 需求原话："版本管理这里增加一个'部署到agent'的选项，确认后就真的发到生产里"。
--
-- is_active（实验室默认）与 is_prod（生产运行）是**两个独立的指针**：调参时
-- 实验室可以随意切版本对照，生产纹丝不动；哪个版本敢上生产，是一次显式的、
-- 带确认的独立动作。两个指针可以指向不同版本——这正是"先在实验室把 v6 调
-- 顺手、生产还跑 v5"的工作流。
--
-- 唯一性约束与 016 的 active_flag 同一手法：生成列 + 唯一索引，"最多一行
-- is_prod=1"由数据库保证，不靠应用层记得先清旧的。
--
-- ⚠️ 刻意没有种子行：上线这张列的瞬间**没有任何版本处于已部署状态**，生产
-- /api/news 走原路径（存量 importance_score 排序），行为与迁移前逐字节一致。
-- 生产行为的任何变化都必须来自用户点"部署"那一下，绝不来自这次迁移的副作用。

ALTER TABLE strategy_config
  ADD COLUMN is_prod TINYINT(1) NOT NULL DEFAULT 0
    COMMENT '1=当前部署到生产(01/02/03排序用这版参数)，全表最多一行；与is_active(实验室默认)独立',
  ADD COLUMN prod_flag TINYINT(1) AS (IF(is_prod = 1, 1, NULL)) STORED
    COMMENT '仅为唯一索引服务：保证最多一行 is_prod=1',
  ADD COLUMN deployed_at DATETIME NULL COMMENT '最近一次被部署到生产的时间',
  ADD UNIQUE KEY uk_prod (prod_flag);
