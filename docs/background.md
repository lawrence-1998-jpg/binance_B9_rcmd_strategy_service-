# B9 推荐策略服务 — 项目背景（Background Memory）

> 本文件由 Manus AI 于 2026-07-26 整理，供后续 Agent 或工程师快速理解项目上下文。

---

## 一、产品背景：Binance B9 推荐模块

**B9** 是 Binance App 中的一个内容推荐模块，主要面向普通用户提供加密货币相关的新闻、板块动态和市场洞察。该模块下设两个核心推荐场景：

| 模块 | 定位 | 核心问题 |
|---|---|---|
| **Sector Insight（板块推荐）** | 为用户当前持仓/关注的板块推荐相关新闻 | 相关性优先，宁缺毋滥 |
| **Macro Insight（宏观新闻流）** | 全市场重要性排序，不依赖用户持仓 | 重要性优先，保底供给 |

**业务痛点（启动本项目的直接原因）**：线上推荐效果存在明显问题——
- 交易所运营公告（OKX 上新、Coinbase 暂停某币）刷屏 Top 榜，挤占真正重要的市场新闻
- 泛科技新闻（DeepSeek 融资、Nvidia 芯片、SpaceX 发射）混入高分区，与币圈无关
- 中文快讯信源（吴说、BlockBeats、ChainCatcher）未被召回，导致中文用户体验差
- 聪明钱/链上动向（lookonchain、EmberCN）完全缺失，错过高价值信号
- 数据召回层存在隐蔽 bug（X KOL 77 条事件因 datetime 格式丢失、LLM 限流导致 131 条静默丢失）

---

## 二、推荐策略设计（已沉淀）

### 2.1 Sector Insight v5.1（板块相关性推荐）

**核心公式**：
```
硬门：Rel < 0.5 → Score = 0（不相关直接淘汰）
打分：Score = (Rel ^ 1.5) × (0.25T + 0.25H + 0.20A + 0.30M)
去重：cosine ≥ 0.75，同事件只留 1 条，Top ≤ 3
```

因子说明：
- **Rel**（相关性）：新闻与目标板块的语义相关度，硬门控
- **M**（市场影响）：事件对价格/资金流的潜在影响，权重最高（0.30）
- **T**（时效性）：发布时间衰减，24h 内满分
- **H**（热度）：多源交叉报道 + 社交互动
- **A**（权威性）：信源可信度分级

### 2.2 Macro Insight v1（全市场重要性排序）

**核心公式**：
```
无硬门（保底供给）
打分：Score = 0.35M + 0.20T + 0.15H + 0.15A + 0.15Q
去重：cosine ≥ 0.65（激进），四层管线，保底 ≥ 3 条
```

新增因子 **Q**（质量/体裁）：分析 > 快讯 > 价格播报，过滤低价值内容。

**对称设计原则**：Sector 解决"相关吗"，Macro 解决"重要吗"；Sector 宁缺毋滥，Macro 保底供给。

### 2.3 关键防火墙规则

- **GENERIC-TECH FIREWALL**：DeepSeek/Nvidia/SpaceX/Anthropic 类泛科技新闻 → 强制 D 级，M ≤ 0.08
- **交易所运营公告过滤**：OKX/Coinbase/Bybit 上新/下架公告 → 移除，不进推荐池
- **体裁前置淘汰**（Sector）：价格播报、市场综述、广告类 → Score = 0

---

## 三、数据基础设施

### 3.1 部署环境

| 组件 | 位置 | 说明 |
|---|---|---|
| 云电脑（GCP EC2） | `34.138.247.158` | 项目主机，Ubuntu 22.04 |
| 项目路径 | `~/crypto-news-crawler/` | 爬虫 + pipeline + API |
| MySQL 数据库 | localhost:3306 | 数据库 `crypto_news` |
| RSSHub 容器 | localhost:1200 | 自建，pipeline 依赖，挂掉需 `docker start rsshub` |
| Flask API | 0.0.0.0:8080 | 对外开放，systemd 管理 |
| Cron 定时任务 | 每 4 小时 | 0/4/8/12/16/20 点自动运行 |

### 3.2 API 访问

```
Base URL:  http://34.138.247.158:8080
Auth:      Authorization: Bearer ***REMOVED***

GET /health                          # 健康检查
GET /api/news?limit=20               # 最新事件（按 importance_score 排序）
GET /api/news?source=吴说区块链       # 按信源筛选（中文需 URL 编码）
GET /api/news?sector=DeFi            # 按板块筛选
GET /api/news?tier=A                 # 按事件级别筛选（S/A/B/C/D）
GET /api/sources                     # 信源分布统计
GET /api/x_posts?limit=20            # X KOL 原始推文
```

### 3.3 数据库主表

**`news_events`**（核心事件表）：
- `title_en` / `title_zh`：双语标题
- `sectors`：JSON 数组，板块标签（DeFi/Layer1/MEME/RWA 等）
- `event_tier`：S/A/B/C/D 五级
- `importance_score`：综合重要性分（0-1）
- `source_names`：JSON 数组，所有报道信源（支持 API 筛选）
- `is_rumor` / `rumor_reason`：谣言标记与原因

**`x_raw_posts`**（X KOL 原始推文）：
- `kol_username` / `kol_followers_count` / `kol_verified`
- `like_count` / `retweet_count` / `impression_count`

---

## 四、信源架构（v2.1，35 个信源 + 32 个 X KOL）

### 4.1 中文直连信源
| 信源 | 接入方式 | 每轮条数 |
|---|---|---|
| 吴说区块链 | 官方 RSS（wublock123.com/feed） | ~30 |
| BlockBeats 律动 | 自建 RSSHub theblockbeats/newsflash+article | ~40 |
| 金色财经 | 自建 RSSHub jinse/lives | 1-10 |
| Followin 中文快讯（聚合） | 自建 RSSHub followin/news/zh-Hans | 14-40 |
| ChainCatcher 链捕手 | HTML 解析（NUXT SSR 数据提取） | 14-20 |
| PANews | 快讯页 HTML 解析 | ~9 |
| TechFlow 深潮 | 官方 RSS | 24-30 |

### 4.2 英文 RSS 信源
CoinDesk、TheBlock、Cointelegraph、Decrypt、Blockworks、TheDefiant、CNBC、YahooFinance（后两者泛科技防火墙降权）

### 4.3 X KOL（32 个，全部经 API 验证）
| 类别 | 账号 |
|---|---|
| 媒体/快讯 | WuBlockchain, wublockchain12, PANewsCN, BlockBeatsAsia, bwenews, Tree_of_Alpha, WatcherGuru, solidintel_x, OdailyChina, Foresight_News, CoinDesk |
| 链上/聪明钱 | lookonchain, EmberCN, spotonchain, whale_alert, ai_9684xtpa, OnchainLens, DefiLlama |
| 数据/研究 | glassnode, MessariCrypto |
| 安全预警 | SlowMist_Team, peckshield, CertiKAlert |
| 官方 | binance, binancezh, cz_binance, heyibinance, BinanceResearch |
| 宏观 | KobeissiLetter, unusual_whales |
| 监管 | SECGov |

> **注意**：BinanceNews/binance_news/BinanceUpdates 全部被 X 封禁，无币安官方 news 账号。

### 4.4 其他信源
- **CoinMarketCal**：催化剂日历（硬分叉/主网/解锁），free tier，3000 req/月
- **币安广场**：ddgs 搜索 `site:binance.com square`
- **币安上币/Launchpool 公告**：RSSHub binance/announcement

---

## 五、关键 API Keys（已配置在 `config/.env`）

| Key | 用途 | 备注 |
|---|---|---|
| `OPENAI_API_KEY` | LLM 结构化（gpt-5.4） | OpenAI 官方 key，TPM 500k |
| `X_BEARER_TOKEN` | X API KOL 推文拉取 | 已配置，每天 192 req |
| `COINMARKETCAL_API_KEY` | 催化剂日历 | free tier，3000 req/月 |
| `API_SECRET_KEY` | Flask API 鉴权 | `***REMOVED***` |
| `MYSQL_PASSWORD` | 数据库密码 | `<见 config/.env 的 MYSQL_PASSWORD>` |

完整 key 值见 `config/.env`（仓库私有，安全存储）。

---

## 六、已知限制与待解决问题

1. **Odaily / Foresight 直连失效**：RSS 404、开放 API 关闭；由 Followin 聚合间接覆盖，非直接接入
2. **BeInCrypto 未接入**：中等规模英文媒体，有 RSS 可接，待决策是否加入
3. **Binance News 无法接入**：官方 news 账号被 X 封禁，无替代渠道
4. **ofox.ai 账户欠费**：如需切回 ofox，需充值后修改 `config/.env` 两行
5. **RSSHub 容器依赖**：pipeline 依赖 localhost:1200，云电脑重启后需手动 `docker start rsshub`（已有 systemd 自启，但偶尔失效）
