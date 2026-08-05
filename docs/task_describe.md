# B9 推荐策略服务 — 任务描述（Task Describe）

> 本文件描述当前正在进行的四个核心任务，供后续 Agent 或工程师无缝接手。
> 最后更新：2026-07-26，由 Manus AI 整理。

---

## 任务总览

```
Step 1: 数据召回层修复（✅ 已完成）
Step 2: LLM 结构化 Pipeline 优化（✅ 已完成）
Step 2.5: 去重重构 + H 因子 + 数据清洗（✅ 已完成，2026-07-26）
Step 3: 推荐策略设计与文档（✅ 已完成，持续迭代）
Step 4: 推荐策略 API 服务（🔄 进行中）
```

---

## Step 2.5：去重重构（Pipeline v2.0，2026-07-26）

**状态**：✅ 已完成

**问题背景**：事件库实测冗余率 48.7%（855 行中 416 行是重复），单个事件最多占 8 行。
skill 文档写的四层去重管线里，DC-1/DC-2/DC-4 三层从未实现，DC-3 用 TF-IDF **词频**
相似度冒充语义向量——对同义改写完全失效。

**三个叠加的根因与修复**：

| 根因 | 修复 |
|---|---|
| `generate_event_id()` 拿 LLM 改写后的 `title_en` 做 hash，每轮措辞不同→id 不同→`ON DUPLICATE KEY UPDATE` 形同虚设 | LLM 新增输出规范化事件三元组（`event_subject`/`event_action`/`event_date`），id 改由指纹派生，跨轮稳定 |
| `aggregate_events()` 用 TF-IDF 词频，抓不住同义改写 | 换成 OpenAI `text-embedding-3-small`（256 维），四层管线补齐 |
| 只在**单轮内**去重，cron 每 4h 一轮、抓取窗口重叠，跨轮完全不设防（量最大的漏口） | 新增 DC-4：写库前拉近 72h 既有事件比对指纹+向量，命中则复用 id 走 UPDATE |

**关键实测发现**：文档写的 cosine≥0.65 在真实数据上会严重过度合并（把"油价破100美元"
和"特斯拉周跌18%"当成同一事件）。在 855 条真实事件、28 万配对上分档标定后改为
**0.82**，详见 `docs/skill-macro-news-recommendation-v1.md` 第三章的阈值修订说明。

**同批完成的另两项**：
- **H 因子补全**：此前只有 `log1p(source_count)`，X 的赞/转/评/引数据落在 `x_raw_posts`
  表里却没接进来。现按文档实现 `H = 0.6×log归一(社交互动) + 0.4×min(独立信源数/8,1)`
- **陈年内容过滤**：YahooFinance 混进 2024 年个人理财常青文、Blockworks 混进 2025-12
  存档，日期错误污染 T 因子。抓取层加 7 天时间窗，实测每轮拦掉约 79 条

**新增/重构文件**：
```
crawler/dedup.py       # 四层去重管线（新）
crawler/scoring.py     # Macro v1 五因子打分，含新 H（新）
crawler/storage.py     # MySQL 读写 + 跨轮归并（新）
crawler/pipeline.py    # 瘦身为 LLM 结构化 + 编排
scripts/backfill_dedup.py          # 存量向量回填 + 历史去重（一次性运维）
config/migrations/001_dedup_fields.sql
```

**运维注意**：`news_events` 新增 `embedding` BLOB 列，API 的 `SELECT *` 会因无法 JSON
序列化而 500。已改为显式列清单（`api/server.py:EVENT_COLUMNS`）——**改 schema 后
务必同时重启 `crypto-news-api`**。

---

## Step 1：数据召回层修复

**状态**：✅ 已完成（v2.1）

**问题背景**：原始爬虫只有 9 个信源、240 条/轮，中文快讯全部缺失，X KOL 未接入，存在多个隐蔽 bug 导致数据静默丢失。

**完成内容**：
- 信源从 9 个扩展到 35 个（含 7 个中文媒体 + 8 个英文媒体 + 32 个 X KOL + CoinMarketCal 催化剂日历 + 币安广场）
- 自建 RSSHub Docker 容器（localhost:1200），恢复 BlockBeats/金色/Followin/币安公告
- 修复三个隐蔽 bug：X KOL datetime 格式导致 77 条丢失、LLM 429 限流导致 131 条丢失、cron 环境变量残留
- 移除全部交易所运营公告（OKX/Coinbase 等），防止刷屏 Top 榜
- 新增 `source_names` JSON 字段落表，API 支持按信源筛选

**验证结果**：raw 521 条 → 入库 466 事件，LLM 和写库零丢失，X KOL 77 条全部入库。

**关键文件**：
- `crawler/sources.py`：信源配置（RSS URL、KOL 列表、权威分）
- `crawler/main.py`：抓取逻辑（RSS/HTML/X API/CoinMarketCal/ddgs）
- `config/schema.sql`：数据库 schema（含 source_names 字段）

**待观察**：
- 每轮 cron 后检查 `pipeline_runs` 表，确认 `enriched_count == deduped_count`（零丢失铁律）
- RSSHub 容器偶尔挂掉，需 `docker start rsshub`

---

## Step 2：LLM 结构化 Pipeline 优化

**状态**：✅ 已完成（gpt-5.4，并发 4，零丢失）

**问题背景**：LLM enrichment 阶段因 429 限流、模型不存在等原因大量丢失，且 prompt 缺乏防火墙规则导致泛科技新闻混入高分区。

**完成内容**：
- 切换到 OpenAI 官方 key + gpt-5.4（TPM 500k，无限流压力）
- 加入 429 指数退避重试（最多 4 次）+ 402 提前退出
- LLM prompt 新增五级事件分类（S/A/B/C/D）、GENERIC-TECH FIREWALL、板块边界规则
- 谣言检测：is_rumor + rumor_reason 字段，谣言保留但降权

**关键文件**：
- `crawler/pipeline.py`：LLM enrichment 完整逻辑（enrich_one / enrich_batch / run_pipeline）
- `run_pipeline.py`：Pipeline 入口，cron 调用

**LLM 配置（当前）**：
```
模型：gpt-5.4
并发：4（max_workers=4）
重试：429 指数退避，最多 4 次
单轮成本：约 $1-2（500 条）
单轮耗时：约 15-20 分钟
```

**待优化**：
- 考虑 gpt-5.4-mini 降低成本（质量 tradeoff 待评估）
- prompt 中 Macro Insight 五级打分可进一步细化（参考 `docs/skill-macro-news-recommendation-v1.md`）

---

## Step 3：推荐策略设计与文档

**状态**：✅ 已完成（持续迭代中）

**完成内容**：

### Sector Insight v5.1（板块相关性推荐）
- 公式：`Score = (Rel^1.5) × (0.25T + 0.25H + 0.20A + 0.30M)`，硬门 Rel < 0.5 → Score = 0
- 去重：cosine ≥ 0.75，Top ≤ 3
- 完整 Skill 文档：`docs/skill-sector-news-recommendation-v5.md`
- Mock 评测报告：`docs/sector-news-mock-evaluation.md`

### Macro Insight v1（全市场重要性排序）
- 公式：`Score = 0.35M + 0.20T + 0.15H + 0.15A + 0.15Q`，无硬门，保底 ≥ 3 条
- 去重：cosine ≥ 0.65（激进），四层管线
- 完整 Skill 文档：`docs/skill-macro-news-recommendation-v1.md`
- Mock 评测报告：`docs/macro-insight-mock-evaluation.md`

**待迭代**：
- Sector Insight：新增 badcase 时在对应因子章节追加 BC-x.x，版本升为 v5.2
- Macro Insight：考虑加入 X KOL 互动量作为 H 因子的补充信号
- 线上 A/B 评测：计划对比 Top30 换手率（事件级归并，以 30 为基数）

---

## Step 4：推荐策略 API 服务

**状态**：🔄 进行中

**目标**：将 Step 3 的推荐策略封装为可调用的 API，供 Binance B9 前端或下游系统消费。

**当前 API 能力**（已上线）：
```
GET /api/news?limit=20               # 按 importance_score 排序的事件列表
GET /api/news?sector=DeFi            # 板块筛选
GET /api/news?source=吴说区块链       # 信源筛选
GET /api/news?tier=A                 # 事件级别筛选
GET /api/sources                     # 信源分布
GET /api/x_posts                     # X KOL 原始推文
```

**待开发**：
1. **Sector Insight 推荐接口**：`GET /api/recommend/sector?sector=DeFi&user_holdings=ETH,AAVE`
   - 输入：目标板块 + 用户持仓（可选）
   - 输出：按 Sector Insight v5.1 公式打分排序的 Top 3 新闻
   - 需要实现 Rel 相关性计算（embedding cosine 或关键词匹配）

2. **Macro Insight 推荐接口**：`GET /api/recommend/macro?limit=10`
   - 输入：limit
   - 输出：按 Macro Insight v1 公式打分排序的全市场 Top N 新闻
   - 需要实现四层去重管线

3. **实时性增强**：当前 cron 4 小时一轮，考虑加 webhook 触发或缩短间隔到 1 小时

4. **前端展示**：`sector-news-ranking-guide` webdev 项目（Manus 托管）已有策略文档展示页，可扩展为 live demo

**接入方式**：
```
Base URL:  http://34.138.247.158:8080
Auth:      Authorization: Bearer YOUR_API_SECRET
```

---

## 快速上手（新 Agent 接手指南）

```bash
# 1. SSH 到云电脑
ssh ubuntu@34.138.247.158

# 2. 检查服务状态
sudo systemctl status crypto-news-api
docker ps  # 确认 rsshub 容器运行中

# 3. 手动跑一轮 pipeline
cd ~/crypto-news-crawler
python3 run_pipeline.py

# 4. 验证数据质量（零丢失铁律）
mysql -uroot -p'<见 config/.env 的 MYSQL_PASSWORD>' crypto_news -e "
SELECT run_at, raw_count, deduped_count, enriched_count, events_count, status 
FROM pipeline_runs ORDER BY run_at DESC LIMIT 5;"
# 确认 enriched_count == deduped_count，status == 'success'

# 5. 查看 Top 20 事件
curl -s "http://localhost:8080/api/news?limit=20" \
  -H "Authorization: Bearer YOUR_API_SECRET" | python3 -m json.tool
```

---

## 文件索引

```
binance_B9_rcmd_strategy_service-/
├── docs/
│   ├── background.md                        # 项目背景（本文件的姐妹文件）
│   ├── task_describe.md                     # 任务描述（本文件）
│   ├── skill-sector-news-recommendation-v5.md  # Sector Insight Skill 文档
│   ├── skill-macro-news-recommendation-v1.md   # Macro Insight Skill 文档
│   ├── sector-news-mock-evaluation.md       # Sector Insight Mock 评测报告
│   ├── macro-insight-mock-evaluation.md     # Macro Insight Mock 评测报告
│   └── recall-fix-report.md                 # 召回质量修复报告
├── crawler/
│   ├── sources.py                           # 信源配置（RSS/KOL/权威分）
│   ├── main.py                              # 抓取逻辑
│   └── pipeline.py                          # LLM 结构化 + 去重 + 写库
├── api/
│   └── server.py                            # Flask REST API
├── config/
│   ├── schema.sql                           # 数据库 schema
│   └── .env                                 # API Keys（私有仓库安全存储）
├── materials/
│   ├── exports/                             # 数据导出样本（CSV）
│   └── screenshots/                         # 原始截图材料
└── run_pipeline.py                          # Pipeline 入口
```
