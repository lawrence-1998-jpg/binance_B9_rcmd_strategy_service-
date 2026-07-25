# B9 新闻召回覆盖率交叉验证报告

测试时间：2026-07-25 21:29 – 21:57 UTC（VM 时间）
被测事件库：`crypto_news.news_events`，508 行（其中 `time_event` 落在近 48h 的 323 行）
上一次生产 pipeline 运行：20:00:04 → 20:17:41 UTC
全部脚本与中间数据：VM `/tmp/covtest/`（可复跑）

> 测试期间事件库是静止的：全程 508 行不变，`max(created_at)` 停在 21:17:36，
> 期间没有 pipeline 写入，所有数字取自同一个快照。
> 注意 21:23 有一次 `scripts/backfill_dedup.py --apply` 把库从 944 行合并删到 508 行，
> 这**发生在本测试开始之前**，且经核查是正确的重复合并（见 §0 与 `/tmp/dedup_apply.log`）。

---

## 0. 结论先说

| 指标 | 数值 |
|---|---|
| **事件级覆盖率（人工判定口径，主口径）** | **29.9%**（85/284） |
| 条目级覆盖率（人工判定口径） | 45.1%（169/375） |
| 条目级覆盖率（纯语义 cosine ≥ 0.75） | 22.9%（86/375） |
| 条目级覆盖率（纯关键词 overlap ≥ 0.5） | 8.8%（33/375） |
| **3 家及以上对照媒体共同报道的事件** | **16/16 = 100%，一条没漏** |
| 2 家对照媒体报道的事件 | 14/18 = 77.8% |
| 仅 1 家对照媒体报道的事件 | 55/250 = 22.0% |

**上次 91.9% 的结论不成立。** 它高估的原因有两个，都已在本次测试中消除：
一是只做关键词重合、把"同主题不同事件"算成命中；二是当时库里 944 行中有 436 行是
重复行（21:23 的 `backfill_dedup.py --apply` 已合并删除，见 `/tmp/dedup_apply.log`），
重复行让任意一条对照都更容易撞上某一行。

**但 29.9% 这个数字本身也需要正确解读**：漏掉的几乎全是"只有一家媒体写过"的长尾条目。
凡是 3 家以上媒体共同报道的事件，本系统一条都没漏。真正的问题不是"漏大新闻"，
而是"信源盘子太小"——77.4% 的漏召是所有抓取路径都没有这条内容。

---

## 1. 对照组构成

对照组**刻意不复用** `crawler/sources.py` 与 `crawler/web_search.py`，否则无法测量
web_search 模块的增量。共 31 个独立 feed，48h 窗口内去重后 **834 条**，
经 LLM 分类后在范围内的真实事件 **386 条**（公平窗口 375 条，见第 2 节）。

### 1.1 抓取成功的源

| 源 | 类型 | 原始条数 | 48h 内 | 在范围内事件数 |
|---|---|---|---|---|
| GN-中文 / GN-中文2 | Google News | 145 | 145 | 60 |
| CryptoPanic（代理） | 盲区代理 | 100 | 99 | 43 |
| GN-行情异动 / 2 | Google News | 100 | 100 | 36 |
| GN-监管 / 2 | Google News | 62 | 62 | 37 |
| GN-安全 / 2 | Google News | 45 | 45 | 24 |
| GN-项目动态 / 2 | Google News | 80 | 80 | 33 |
| GN-宏观美股 / 2 | Google News | 77 | 77 | 25 |
| Reuters（代理） | 盲区代理 | 100 | 92 | 2 |
| Odaily（代理） | 盲区代理 | 42 | 41 | 21 |
| U.Today | 直连 RSS | 91 | 32 | 22 |
| 华尔街见闻 | 直连 RSS | 54 | 54 | 16 |
| CryptoBriefing | 直连 RSS | 30 | 30 | 9 |
| AMBCrypto | 直连 RSS | 16 | 16 | 11 |
| BeInCrypto | 直连 RSS | 12 | 12 | 5 |
| CryptoSlate | 直连 RSS | 10 | 10 | 6 |
| Bitcoin.com | 直连 RSS | 10 | 10 | 5 |
| NewsBTC | 直连 RSS | 10 | 10 | 10 |
| Bitcoinist | 直连 RSS | 8 | 8 | 8 |
| Investing-Crypto | 直连 RSS | 10 | 8 | 7 |
| Investing-Econ | 直连 RSS | 10 | 10 | 2 |
| MarketWatch | 直连 RSS | 10 | 10 | 0 |
| CoinJournal | 直连 RSS | 9 | 4 | 2 |
| Protos | 直连 RSS | 10 | 4 | 1 |
| CNBC-Econ | 直连 RSS | 30 | 1 | 1 |
| Fed-Press | 直连 RSS | 20 | 0 | 0 |

去重掉的组内重复 126 条。分桶：直连 219 / Google News 411 / 盲区代理 204。
语种：英文 623 / 中文 211。

### 1.2 三个盲区源的处理结果

| 源 | 尝试过的入口 | 结果 |
|---|---|---|
| **CryptoPanic** | `/news/rss/`、`/news/rss`、`/api/v1/posts/`、`/api/free/v1/posts/`、`/api/developer/v2/posts/`、首页 HTML 抽取 | **直连仍失败**。`/news/rss/` 返回 200 但内容是 Vue SPA 的 HTML（站点已无公开 RSS）；三个 API 端点分别 403 / 404 / 404，均要 `auth_token`；HTML 里没有可抽取的标题（前端渲染）。 |
| **Odaily** | 官方 `/v1/openapi/feeds`、rsshub.app、rssforever、pseudoyu、本地 RSSHub、官网 HTML、`api.odaily.news` 9 条路径枚举、Next.js JS chunk 里扒 API 地址 | **直连仍失败**。RSSHub 公共实例 403/503/522，本地实例 503；官网是 Next.js App Router，RSC 流里只有导航/页脚文案，正文列表是客户端拉取；`api.odaily.news` 是活的 JSON 网关但 9 条候选路径全返回 `No endpoint`。 |
| **Reuters** | `feeds.reuters.com`（两个路径）、`reutersagency.com`、`reuters.com/arc/outboundfeeds/`、`/rssfeed/`、`/tools/rss`、openrss.org | **直连仍失败**。`feeds.reuters.com` DNS 已注销（NXDOMAIN）；`reuters.com` 全站 Akamai 反爬，返回 401「Please enable JS」；arc feed 404；openrss 503。 |

三者均改用 **Google News `site:` 代理**（`when:1d site:cryptopanic.com` 等）取得了
真实标题，分别拿到 99 / 41 / 92 条。这是可用的替代观测，但要注意两点局限：
(1) 是 Google 索引到的子集，不等于该站全量；(2) Reuters 代理拿到的 92 条里
只有 2 条落在加密/宏观范围内，其余是通用时政，对本测试贡献很小。
**结论：三个源的"直连"能力仍是盲区，但"内容盲区"已通过代理基本消除。**

---

## 2. 方法与两个必须说明的口径问题

### 2.1 公平窗口

上一次生产 pipeline 在 20:00:04 开始抓取。对照组在 21:29:32 采集。
**20:00 之后发布的新闻，系统在物理上不可能收录**。386 条在范围内条目里有 11 条属于
这种情况，已从主口径剔除，得到公平窗口 **375 条**。两个口径差别很小（45.6% → 45.1%），
说明这不是主要影响因素，但为严谨仍按公平窗口报数。

### 2.2 匹配方法：为什么主口径不是 cosine

按要求做了三种匹配，并且**实测了前两种的错误率**：

| 方法 | 覆盖率 | 相对人工判定的精确率 | 相对人工判定的召回率 |
|---|---|---|---|
| 语义 cosine ≥ 0.75 | 22.9% | 93.3%（83/89） | 47.2%（83/176） |
| 关键词 overlap ≥ 0.5 | 8.8% | — | — |
| **LLM 逐条判定（主口径）** | **45.1%** | 参考基准 | 参考基准 |

阈值标定用的是实际配对样本（`match.py` 输出的分档抽样）：

- `[0.85, 1.0]` n=33：全部真命中
- `[0.80, 0.85)` n=26：全部真命中
- `[0.75, 0.80)` n=30：抽查 5 条全部真命中（Dango 停运 0.795、BitMEX 集体诉讼 0.756、
  Peirce 表态 0.780、Robinhood CEO 被黑 0.758）
- `[0.70, 0.75)` n=44：约一半真命中（Samsung 稳定币 0.729 真、World Foundation 融资 0.707 真；
  Dogecoin ETF vs Bitcoin ETF 0.703 假、朝鲜黑客两条不同事件 0.723 假）
- `[0.60, 0.70)` n=109：多数为假，但夹杂真命中（World Foundation 同一笔融资 0.601）

所以 **0.75 是精确率合格的取值（93.3%），但召回率只有 47.2%** ——跨媒体改写的同一
事件大量落在 0.60–0.75 区间。一个直接的例子：smoke test 里
"Bitcoin plunges below \$60,000 amid ETF outflows" 与 "BTC drops under \$60k as spot
ETFs bleed" 余弦只有 **0.775**，已经贴着阈值。因此**纯 cosine 会系统性低估覆盖率约一倍**，
不能作为主口径。文档里的 0.65 更不能用于覆盖率匹配（该档位多数是不同事件）。

主口径改为：cosine 取 top-12 + 独立的 MySQL 模糊关键词召回一并作为候选，交给
`gpt-5.4` 逐条判定"是否同一真实事件"。抽样复核显示该判定对 60 条 miss 样本的
假阴性率 30%、对 40 条 hit 样本的假阳性率 12.5%——这两项误差正是把主口径从 cosine
换成 LLM 判定的原因。归因环节的配对另做了一轮**严格二次校验**（152 对里剔除 74 对
过度匹配，存活率 51.3%），因此归因数字比初版保守。

### 2.3 分母的选择

834 条池子里，230 条 `out_of_scope`（体育、无市场角度的国际时政、消费电子等）、
207 条 `non_event`（"5 个该买的币"清单、纯技术分析观点、推广稿、社媒随笔）已剔除，
不计入分母。这两类占池子 52%，主要来自 Google News 长尾和 Reuters 通用线。
把它们算进分母会人为压低覆盖率，算成"应召回"也不合理。

---

## 3. 分类别覆盖率

公平窗口，条目级；括号内为纯 cosine / 纯关键词口径。

| 类别 | 对照条目 | 命中 | **覆盖率** | cosine≥0.75 | 关键词≥0.5 |
|---|---|---|---|---|---|
| 行情异动类 | 93 | 39 | **41.9%** | 20.4% | 4.3% |
| 宏观美股交叉类 | 46 | 16 | **34.8%** | 13.0% | 6.5% |
| 监管类 | 73 | 44 | **60.3%** | 34.2% | 16.4% |
| 安全事故类 | 38 | 18 | **47.4%** | 26.3% | 5.3% |
| 项目动态类 | 125 | 52 | **41.6%** | 20.8% | 9.6% |
| 合计 | 375 | 169 | **45.1%** | 22.9% | 8.8% |

事件级（去掉同一事件的多篇报道后）：

| 类别 | 事件数 | 覆盖率 |
|---|---|---|
| 行情异动类 | 72 | 27.8% |
| 宏观美股交叉类 | 44 | 31.8% |
| 监管类 | 51 | 43.1% |
| 安全事故类 | 30 | 36.7% |
| 项目动态类 | 102 | 29.4% |

**读法**：监管类最好（60.3%）——监管消息通常多家媒体同步报道，容易被现有信源覆盖。
宏观美股交叉类最差（34.8%），而这恰恰是 B9 的差异化卖点；漏的多是
"油价/关税/芯片/央行"这类**先发生在传统财经媒体、几小时后才被加密媒体转述**的内容。
行情异动类条目级 41.9% 但事件级只有 27.8%，说明命中集中在少数几个被反复报道的大行情上，
中小市值币的异动基本没覆盖。

### 3.1 按报道家数分层（最有决策价值的一刀）

| 有几家对照媒体报道 | 已覆盖事件 | 漏召事件 | 覆盖率 |
|---|---|---|---|
| **3 家及以上** | 16 | **0** | **100.0%** |
| 2 家 | 14 | 4 | 77.8% |
| 仅 1 家 | 55 | 195 | 22.0% |

**系统没有漏掉任何一条被 3 家以上独立媒体共同报道的新闻。** 漏召 100% 集中在
单家媒体报道的长尾。这个结论对"是否该紧急扩源"的判断至关重要——当前的问题不是
"错过大事"，而是"长尾密度不够"。

---

## 4. 漏召归因

公平窗口内 199 个漏召事件。归因方法：用系统自己的抓取层重跑一轮
（`fetch_baseline.py`，RSS+HTML+币安广场+CoinMarketCal+X KOL 共 771 条，
外加三个新模块共 389 条，候选池 1160 条），把漏召标题与候选池做向量召回 + LLM 判定，
再对每个配对做严格二次校验。

| 归因 | 事件数 | 占比 |
|---|---|---|
| **A. 信源没接：本轮任何抓取路径都没有这条** | **154** | **77.4%** |
| E. 基线源没有，只有新模块抓到 | 30 | 15.1% |
| D. 抓到并进了 LLM，但没落成独立事件 | 15 | 7.5% |
| B. 抓到了但被新鲜度过滤丢弃 | 0 | 0% |
| C. 抓到了但被粗去重误杀 | 0 | 0% |

**新鲜度过滤和粗去重都不是问题源头，一条都没误杀。**（初版归因曾报 B=5，
严格二次校验后全部证实为误配，已归零。）

按类别拆：

| 归因 | 行情异动 | 宏观美股 | 监管 | 安全事故 | 项目动态 |
|---|---|---|---|---|---|
| A. 信源没接 | 36 | 25 | 18 | 9 | 66 |
| E. 仅新模块可达 | 12 | 4 | 9 | 4 | 1 |
| D. 进了 LLM 没落库 | 3 | 1 | 1 | 6 | 4 |

**A 类的一个已知局限**：判定依据是"21:45 重跑抓取层时该内容不在源里"，
无法排除"20:00 时在 feed 里、之后被新内容挤出"的情况（多数 RSS 只保留 10–50 条）。
按新闻年龄拆开看这个偏差：

| 新闻年龄 | 漏召事件 | 其中判为"信源没接" |
|---|---|---|
| 1.5–6h | 27 | 18（67%） |
| 6–12h | 51 | 39（76%） |
| 12–24h | 88 | 68（77%） |
| 24–48h | 32 | 28（88%） |

年龄越大 A 占比越高，说明确实存在滚屏偏差；但**最新鲜的 1.5–6h 档仍有 67% 判为信源没接**，
这一档滚屏影响最小，因此"信源覆盖不足"是真实结论，不是测量假象。

### 4.1 漏召样本清单（40 条）

归因代码：A=信源没接，D=抓到但没落库，E=仅新模块可达。

**行情异动类**

1. `E` Wall Street Money is Flowing into Ethereum ETFs and Out of Hyperliquid — BeInCrypto｜本轮 web_search 抓到
2. `D` Worldcoin Crashes 10% After the Project Sells 217 Million Tokens for Funding — BeInCrypto｜本轮 baseline/TechFlow深潮 抓到「Worldcoin 基金会折价出售 2.174 亿枚 WLD」
3. `A` DOGE slides below \$0.070 as market sentiment weakens — CoinJournal
4. `A` BTC ETF flows turn negative for over half of 2026 — CryptoBriefing
5. `E` Why is DEXE up 147% today? – Volume, liquidations & more… — AMBCrypto｜web_search
6. `E` Hyperliquid loses its key trendline – THESE 3 factors are driving sell-off — AMBCrypto｜web_search
7. `A` Shiba Inu Netflow Exits Bullish Zone With 69 Billion SHIB but Price Says Otherwise — U.Today
8. `A` Dogecoin ETFs Go Quiet Again After Brief \$345K Inflow Surge — U.Today

**宏观美股交叉类**

9. `A` Top Democrat criticizes Trump administration for worsening chip shortage — CryptoBriefing
10. `E` Kuwait denies WSJ report on military strikes against Iran, rattling markets — CryptoBriefing｜web_search
11. `A` Houthi rebels attack Saudi oil tankers, sending Brent crude past \$100 and testing Bitcoin — CryptoBriefing
12. `A` Supreme Court strikes down Trump tariffs in landmark ruling — CryptoBriefing
13. `A` Bitcoin slips 1.5% on Iran tensions and U.S. tariffs, but set for mild weekly gain — Investing-Crypto
14. `A` BofA warns oil volatility could force central banks to abandon "look-through" policy — Investing-Econ
15. `A` China economic growth set to slow in H2 as Beijing avoids broad stimulus — Investing-Econ
16. `A` 美伊谈判希望重燃，原油一度跌超5%，科技股压制美股反弹，芯片指数暴跌4% — 华尔街见闻

**监管类**

17. `A` SEC Enforcement Deputy Sam Waldon To Step Down As Agency Reshuffles Leadership — NewsBTC
18. `A` Is Vietnam's new crypto framework the first step towards a ban? — AMBCrypto
19. `E` 'Pass the DAM Clarity Act': Ripple CTO Emeritus Gives Stalled US Crypto Bill New Identity — U.Today｜web_search
20. `A` Crypto Mining Banned in Another US Town — U.Today
21. `A` 香港微调杠杆及反向产品监管框架，引入投资者保障新措施 — 华尔街见闻
22. `A` 证监会原副主席方星海被查 — 华尔街见闻
23. `E` SEC Clears Zcash – ZEC Price Rockets To Six-Month High — GN-行情异动2｜web_search
24. `A` Seizing Ayatollah's Bitcoin: America's New Fort Knox Plan Races The Midterm Clock — GN-宏观美股

**安全事故类**

25. `D` Crypto Payments Firm Triple-A Hit by \$9.7 Million Wallet Drain — BeInCrypto｜x_search/X/CryptoPatel
26. `A` Two Ethereum bridges lose \$31.7M within hours as third protocol halts staking — CryptoSlate
27. `D` Triple-A Hot Wallets Drained of \$9.7M Across Six Chains: What Peckshield Found — Bitcoin.com｜web_search/Bitcoin News
28. `A` Elliptic Report Shows How Bitcoin ATM Scams Move From Cash To On-Chain Wallets — NewsBTC
29. `D` Triple-A exploit drains \$9.7mln across 4 chains – What we know so far — AMBCrypto｜x_search
30. `A` HKMA Warns of Fake HSBC and HKDAP Tokens Amid Stablecoin Rollout — GN-监管2
31. `A` Solana Reassesses Security After \$280M Drift Exploit as Markets Roil — GN-安全
32. `E` \$9.7M Drained Across Ethereum, Solana, TRON, and TON in Triple-A Exploit — GN-安全｜x_search

**项目动态类**

33. `A` WEEX Named Most Secure Crypto Exchange at CoinGape Web3 Innovation Awards 2026 — BeInCrypto
34. `A` TRON Reaches \$90B+ USDT on the Network, \$887M+ in Crypto Card Volume in Q2 — Bitcoin.com
35. `A` Frax Proposal Would Allow Early frxETH Redemptions With 4% Penalty — Bitcoinist
36. `A` Frax Community Weighs Morpho Market For bdUSD And frxUSD Liquidity — Bitcoinist
37. `A` EigenLayer ELIP-018 Proposes Irreversible Exit Route For Restakers — Bitcoinist
38. `A` Uniswap RFC Explores Private Swap Execution Using v4 Hooks And UniswapX — Bitcoinist
39. `A` Kraken Adds USDT0 Deposits And Withdrawals On Tempo Network — Bitcoinist
40. `A` Arbitrum Security Council Moves To Correct 51M ARB Voting Power Discrepancy — Bitcoinist

两条值得单独点名的漏召（都是 A 类，属于"本该抓到的量级"）：
**"Two Ethereum bridges lose \$31.7M within hours"**（CryptoSlate）和
**"Solana \$280M Drift Exploit"**（GN-安全）——千万美元级安全事故，现有信源盘子里没有。
另外 Bitcoinist 一家就贡献了 6 条协议治理类漏召（35–40），说明**协议治理/提案类内容
是一个成片的空白**。

---

## 5. 三个新模块的增量贡献

三个模块均按要求实跑一轮（`run_modules.py`，21:38–21:40 UTC），产出与实测基本一致：

| 模块 | 本轮产出 | 耗时 | 关键水位 |
|---|---|---|---|
| `market_signals` | **18 条** | 6.6s | 检测 20 条（涨跌 7 / 突破 3 / 周期极值 1 / 放量 9），保留 18 |
| `web_search` | **171 条** | 46.2s | 28 次请求，276 条原始 → 171 条；丢弃：离题 73、重复 URL 17、重复标题 11、过期 4 |
| `x_search` | **200 条** | 34.2s | 38 次请求，3461 条原始 → 200 条（封顶）；丢弃 94%，其中互动量不足 2478、成本封顶 312、垃圾 153 |

对 199 个漏召事件的增量贡献（**已经过严格二次校验，数字比初版保守**）：

| 模块 | 命中漏召事件 | 占漏召 | 基线拿不到的 | 三模块中独占 |
|---|---|---|---|---|
| `web_search` | **30** | **15.1%** | 26 | 23 |
| `x_search` | **10** | **5.0%** | 5 | 2 |
| `market_signals` | **2** | **1.0%** | 2 | 2 |
| 三者合计（去重） | — | — | **30（15.1%）** | — |

对照参考：本轮任一抓取路径（含基线）可达的漏召事件共 45/199 = 22.6%。
也就是说，**在所有"本轮能被抓到却没进库"的漏召里，三分之二只有新模块这条路能拿到**。

**逐个评价：**

- **`web_search` 是三者中价值最高的，且优势明显**：单独覆盖 26 个基线源完全没有的事件，
  独占 23 个。命中的都是基线源结构性缺失的类型——AMBCrypto/BeInCrypto 这类二线英文站的
  行情解读、Zcash 获批这种被中小站首发的监管消息、以及 Kuwait/Iran 这类宏观突发。
  它的来源分布也印证了这点：CryptoRank 23、Cryptonews.net 13、PANews 12、Binance 11、
  Bitcoin News 10——全部不在 `sources.py` 的 25 个源里。**建议保留并扩大 query 覆盖面。**
- **`x_search` 价值确认但偏窄**：10 条命中里有 5 条基线也能拿到（与 KOL 时间线重叠），
  真正独占只有 2 条。不过它有一个不可替代的特性——**首发速度**：Triple-A 被盗 970 万美元
  这条，x_search 从 `X/CryptoPatel` 抓到的版本与 web_search 从 Bitcoin News 抓到的
  版本同时出现在候选池里，而 X 侧通常早于媒体侧。代价是 3461 抓 200（丢弃 94%）、
  38 次 API 请求。**建议保留，但把预算重心放在安全事故类 query 上。**
- **`market_signals` 对"媒体报道型"漏召几乎没有贡献（2 条），但这不代表它没用**：
  它产出的 18 条是**行情信号本身**（DEXE 涨 37.2%、EUL 涨 60.4%、SHIB 突破 4.5e-06、
  AERO 成交额放大 8 倍），这类内容按定义就不会有媒体写，所以在"与媒体对照"的框架里
  天然测不出分。它命中的 2 条恰好是媒体也写了的（DEXE 暴涨被 AMBCrypto 写成
  "Why is DEXE up 147% today?"）。**它的价值要用另一套指标衡量（信号准确率、
  是否领先媒体报道），本测试无法证伪也无法证实。**

---

## 6. 结论与下一步

### 6.1 现在还欠召什么

1. **长尾信源密度不足，这是压倒性的主因（77.4% 漏召）。** 二线英文加密站
   （Bitcoinist、AMBCrypto、BeInCrypto、CryptoSlate、U.Today、CoinJournal、
   CryptoBriefing、NewsBTC、Bitcoin.com、Protos）一个都没接，而它们贡献了大量
   漏召——仅 Bitcoinist 一家就有 6 条协议治理类。这些源全部是**直连 RSS 200 可用**，
   接入成本极低。
2. **协议治理/提案类是成片空白。** Frax 提案、EigenLayer ELIP、Uniswap RFC、
   Arbitrum 安全委员会——现有信源体系对"链上治理动态"几乎零覆盖。
3. **宏观美股交叉类最弱（34.8%），而这是差异化卖点。** 漏的是油价破百、关税裁决、
   芯片短缺、央行政策这类**先发于传统财经媒体**的内容。现在只接了
   YahooFinance / CNBC-Finance 两个，Investing.com、MarketWatch、路透（可用 Google News
   `site:` 代理）都没接。
4. **中文源偏科。** 华尔街见闻 16 条在范围内事件只命中 1 条；Odaily 代理的 21 条命中 10 条。
   中文侧现在靠 BlockBeats/金色/深潮/吴说，宏观财经中文源基本是空的。
5. **千万美元级安全事故会漏。** \$31.7M 双桥被盗、\$280M Drift 漏洞都不在信源盘子里。
   安全事故类事件级覆盖率只有 36.7%，而这是对用户最有价值的品类之一。

### 6.2 建议的下一步（按性价比排序）

1. **直接把对照组里已验证可用的 10 个二线英文 RSS 接进 `sources.py`**——
   BeInCrypto、CryptoSlate、Bitcoin.com、CoinJournal、Bitcoinist、NewsBTC、
   CryptoBriefing、AMBCrypto、U.Today、Protos。全部实测 HTTP 200、有标准 RSS、
   零改造成本。量化依据：154 条 A 类漏召里有 **34 条**的对照源就是这 10 家；
   把全部归因合并看，199 个漏召事件里有 **47 条**来自这 10 家。
2. **补宏观财经源**：Investing-Crypto、Investing-Econ、MarketWatch 直连 RSS 可用；
   路透用 `when:1d site:reuters.com` 的 Google News 代理接入（直连已确认无解）。
3. **给 `web_search` 扩 query**：它已被证明是长尾的主要抓手（独占 23 条）。
   优先补协议治理（"governance proposal"、"ELIP"、"RFC"、"DAO vote"）和
   安全事故（"bridge exploit"、"protocol drained"）两类 query。
4. **`x_search` 预算重配**：3461 抓 200 的漏斗里，互动量门槛砍掉了 2478 条。
   安全事故往往由小账号首发、互动量起量慢，建议对安全类 query 单独放宽互动阈值。
5. **D 类（15 条，7.5%）单独排查**：这些是抓到了、进了 LLM、但没落成独立事件的。
   Triple-A 被盗一条被三家对照媒体报道、系统三条抓取路径都抓到了却没落库，
   值得单独看一眼是结构化失败还是被错误合并。
6. **不要动新鲜度过滤和粗去重**：本次实测两者误杀数均为 0，不是问题源头。

### 6.3 关于这次测试本身

- 主口径用 LLM 逐条判定而非 cosine，是因为**实测 cosine@0.75 的召回率只有 47.2%**，
  会把覆盖率低报约一倍。若后续要复跑，建议沿用 LLM 判定口径，否则数字不可比。
- 归因结论中 A 类存在"feed 滚屏"偏差（无法区分"从没有"和"20:00 时有、之后被挤出"），
  已用年龄分层给出偏差量级；最新鲜档仍有 67% 判为信源没接，结论方向可靠。
- 三个盲区源的**直连**仍然拿不到，报告中所有涉及它们的数据均来自 Google News 代理。
- 本次未测量的：`market_signals` 的信号质量、事件分级（tier）准确率、去重后的
  召回损失率、以及 API 对外服务的实际返回质量。
