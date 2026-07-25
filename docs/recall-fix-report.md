# 召回质量修复报告：币圈新闻数据 Pipeline v2

**日期**：2026-07-25 ｜ **执行环境**：云电脑 `~/crypto-news-crawler` ｜ **版本**：v2.0（召回全面性修复）

## 一、修复总览

本次修复以「召回不足/有偏/错误一定不能接受」为最高优先级。修复前的系统存在三个致命问题：中文源全部失效（PANews、BlockBeats、金色财经、Odaily 的 RSS 均已 404 或停服）、X KOL 与币安广场搜索从未真正生效、OKX 交易所公告因权威分过高刷屏 Top 榜。修复后单轮召回从 **240 条 / 9 个信源** 提升到 **约 520 条 / 35 个信源**，中文源全面恢复，X KOL 推文单独落表并参与事件生成。

| 指标 | 修复前 | 修复后（第八轮验证） |
|------|--------|---------------------|
| 单轮原始召回 | 240 条 | 521 条 |
| 有效信源数 | 9 个（全英文+OKX公告） | 35 个（中英文+X KOL+币安广场） |
| 中文事件占比 | 0% | 36%（168/466） |
| X KOL 事件 | 0 | 77 个（另有 79 条原始推文落表） |
| 入库事件 | 240（含公告噪音） | 466（S5/A30/B85/C117/D229） |
| LLM/写库丢失 | 未监控 | **0 丢失**（重试+datetime 规范化后） |

## 二、信源承诺 vs 落地对照表

此前方案承诺的信源逐一验证落地，不允许「方案漂亮、落地变形」。每个信源都经过实际抓取测试并确认条数：

| # | 信源 | 落地方式 | 状态 | 条数/轮 |
|---|------|---------|------|--------|
| 1 | 吴说区块链 | 官方 RSS `wublock123.com/feed`（实时中文50条） | ✅ | 30 |
| 2 | BlockBeats 律动 | 自建 RSSHub `theblockbeats/newsflash` + `article` | ✅ | 40 |
| 3 | 金色财经 | 自建 RSSHub `jinse/lives` | ✅ | 1-10 |
| 4 | Followin 中文快讯（聚合） | 自建 RSSHub `followin/news/zh-Hans` | ✅ | 14-40 |
| 5 | ChainCatcher 链捕手 | HTML 解析（NUXT SSR 数据提取） | ✅ | 14-20 |
| 6 | PANews | 快讯页 HTML 解析 | ✅ | 9 |
| 7 | TechFlow 深潮 | 官方 RSS | ✅ | 24-30 |
| 8 | X KOL（16 个核心账号） | X API get_user_posts | ✅ | 79 |
| 9 | 币安广场 Binance Square | ddgs 搜索 `site:binance.com square` | ✅ | 26 |
| 10 | 币安上币/Launchpool 公告 | RSSHub `binance/announcement`（其余交易所公告已全移除） | ✅ | 16 |
| 11 | 英文头部媒体 ×6 | CoinDesk/TheBlock/Cointelegraph/Decrypt/Blockworks/TheDefiant RSS | ✅ | ~170 |
| 12 | 宏观/美股 | CNBC/YahooFinance RSS（泛科技防火墙降权至 D 级） | ✅ | ~60 |
| — | Odaily 星球日报 | 直连全部失效（RSS 404、开放 API 关闭）；由 Followin/金色聚合**间接覆盖** | ⚠️ | — |
| — | Foresight News | RSSHub 路由全部 404；由 Followin 聚合**间接覆盖** | ⚠️ | — |

X KOL 名单：WuBlockchain、wublockchain12、PANewsCN、BlockBeatsAsia、lookonchain、EmberCN、spotonchain、glassnode、MessariCrypto、SlowMist_Team、PeckShield、CertiKAlert、binance、binancezh、cz_binance、heyibinance、SECGov。聪明钱、链上安全、官方公告三类热点由此保障分钟级捕捉。

## 三、落地防变形：本轮实际抓到并修复的隐蔽 Bug

这些问题恰好说明「方案正确但落地变形」的风险，全部已修复并验证：

| 问题 | 根因 | 修复 | 验证结果 |
|------|------|------|---------|
| X KOL 77 条事件全部丢失 | LLM 输出 ISO8601 时间（`...T14:02:54.000Z`），MySQL DATETIME 拒绝写入 | `_to_mysql_dt()` 入库前规范化 | 第八轮 77 条 X 事件全部入库 |
| 131 条 LLM 调用静默丢失 | 429 限流无重试 | 指数退避重试 4 次 + 402 提前退出 | 第八轮 0 丢失 |
| cron 定时任务 401 挂掉 | `os.environ.setdefault` 不覆盖旧环境变量 | 强制覆盖 `os.environ[k]=v` | 已修复 |
| OKX 公告刷屏 Top 榜 | authority=5 + prompt 官方公告 0.9+ | 移除全部交易所运营公告 | Top20 无公告噪音 |
| 泛科技新闻混入高分区 | 无防火墙规则 | GENERIC-TECH FIREWALL | DeepSeek/Anthropic 类全部 D 级、M≤0.08 |

## 四、第八轮全量验证结果（gpt-5.4）

**流水**：raw 521 → dedup 482 → LLM enriched 482（0 丢失）→ 聚合 466 events → 写库 466（0 写入错误）。谣言标记 34 条（保留但降权）。

**Top 榜画风抽查**（与币安 Macro Insight 需求对齐）：Top 20 由 ETF 资金流、欧盟制裁 HTX、BitMEX 关停、日本国家比特币储备、CLARITY 法案博弈、AFX 黑客换仓、Worldcoin 折价抛售构成——监管、机构、安全、聪明钱四类核心热点全部在位。MEME 板块召回 TRUMP 解锁、DOGS Launchpool、Robinhood 链；安全类召回 AFX/BMX/朝鲜黑客；多信源交叉验证生效（如 AFX 事件聚合了 ChainCatcher + X/EmberCN + 吴说三源）。

**source_names 字段**已落表为 JSON 数组并可经 API 筛选：

```
GET /api/news?source=吴说区块链   → 30 个事件（中文参数需 URL 编码）
GET /api/news?source=X/lookonchain → 聪明钱事件
GET /api/sources                  → 全部信源分布统计
```

## 五、LLM 配置（当前生效）

模型为 **gpt-5.4**（你的 OpenAI 官方 key，TPM 500k / RPM 500，无限流压力），并发 4，单轮全量约 17 分钟、成本约 $1-2。此前 ofox.ai 账户已欠费（-$0.09），如需切回请充值后改 `config/.env` 两行即可。

## 六、付费 API 采购建议（可选增强）

当前免费信源组合已覆盖中文快讯全景 + X KOL + 币安生态，付费 API 属锦上添花：

| API | 价格 | 价值 | 建议 |
|-----|------|------|------|
| Tree of Alpha / Phoenix News | ~$50-100/mo | 交易员级低延迟快讯，listing/hack 全网最快 | **优先考虑**（若追求分钟级时效） |
| CryptoPanic Pro | ~$150/mo | 200+ 源聚合 + 社区情绪投票 | 中优先级，补英文长尾 |
| CoinMarketCal | 免费层可用 | 板块催化剂日历（解锁/主网/会议） | 可直接接入免费层 |
| X API 升级 Pro | $5000/mo | KOL 扩量至数百账号 | 暂不需要（16 账号配额够用） |
| CoinDesk Data（CryptoCompare） | 分级订阅 | 机构级新闻+情绪标签 | 低优先级 |

## 七、运行方式

- **定时**：cron 每 4 小时自动跑一轮（0/4/8/12/16/20 点）
- **手动**：`cd ~/crypto-news-crawler && python3 run_pipeline.py`
- **API**：`http://34.138.247.158:8080`，鉴权 `Authorization: Bearer ***REMOVED***`
- **依赖**：RSSHub Docker 容器（localhost:1200），挂掉需 `docker start rsshub`
