# Sector Insight 相关热点新闻推荐 — Skill v5 Mock 召回评测表

> 评测时间：2026-07-24（GMT+8）｜数据窗口：2026-07-20 ~ 07-24（近 96 小时真实新闻）
> 数据源：币安广场（Binance Square News）、X (Twitter)、CoinMarketCap、Odaily、BlockBeats、PANews
> 召回规则：skill v5 —— 硬门 Rel≥0.5 → Score = Rel^1.5 × (0.25T + 0.25H + 0.20A + 0.30M) → 标题归一化+事件指纹去重 → Top≤3
> **宁缺毋滥原则生效**：3 条是上限不是 KPI；候选池中没有足够相关的内容时输出 0/1/2 条，不为凑数降门槛。

---

## 一、总览

| 板块 | 板块类型 | 召回条数 | 候选池规模 | 说明 |
| :--- | :--- | :---: | :---: | :--- |
| MEME | 赛道型 | 3 | 12 | 候选充足，DOGE/Jimothy/监管三主题 |
| 游戏 | 赛道型 | 1 | 8 | **宁缺毋滥触发**：仅 1 条过硬门，拒绝硬揰 AI/meme 新闻 |
| bStocks | 平台机制型 | 3 | 14 | 机制新闻+成分正股 1 跳事件充足 |
| Launchpool | 平台机制型 | 1 | 6 | **宁缺毋滥触发**：近 7 天无新一期项目官宣 |
| Megadrop | 平台机制型 | 0 | 4 | **宁缺毋滥触发**：无机制类新闻，空板块合法输出 |
| 基础架构 | 赛道型 | 3 | 9 | LINK/ZRO 成分币事件+安全事件 |
| AI | 赛道型 | 2 | 11 | **宁缺毋滥触发**：Web2 AI 陷阱全部拦截，仅 2 条过门 |
| Solana | 公链生态型 | 3 | 10 | 链本身升级+链级数据充足 |

合计召回 16 条 / 上限 24 条，召回率 67%——对比线上版本"每板块硬凑 3 条、badcase 率 70%"，v5 用出条率换准确率。

---

## 二、逐板块召回明细

### 板块 1：MEME（赛道型）

| # | 标题 | 总结 | 来源链接 | Rel | T | H | A | M | Score |
| :-: | :--- | :--- | :--- | :-: | :-: | :-: | :-: | :-: | :-: |
| 1 | 白宫发布浣熊 Jimothy 推文，同名 Meme 币市值破 4000 万美元 | 白宫官方账号发布西雅图网红浣熊 Jimothy 推文后，Solana 生态同名 Meme 币 24 小时再涨 60%、市值突破 4000 万美元，成交量达 4400 万美元。政治级流量为动物系 meme 注入新叙事，短线情绪与资金活跃度显著抬升；该币未上币安现货，追高需注意流动性风险。 | [BlockBeats 快讯 7/24 00:06](https://www.theblockbeats.info/newsflash) ／ [Yahoo Finance 背景报道](https://finance.yahoo.com/markets/crypto/articles/jimothy-raccoon-solana-token-climbs-020000750.html) | 0.90 | 0.95 | 0.85 | 0.70 | 0.75 | **0.69** |
| 2 | 聪明钱 755 美元押中 Jimothy 浮盈 596 倍，仍持 1.27% 总量 | GMGN 数据显示，一聪明钱地址以 755 美元建仓 Jimothy，现持仓价值 44.7 万美元、回报约 596 倍，且仍持有 1279 万枚（占总供应 1.27%）。链上筹码集中度与聪明钱持仓动向是该 meme 币后续波动的关键变量，大户未离场支撑短期情绪，但也构成集中抛压风险。 | [Odaily 快讯 7/23 16:16](https://www.odaily.news/newsflash) | 0.85 | 0.80 | 0.60 | 0.55 | 0.55 | **0.49** |
| 3 | 参议院共和党发布更新版《清晰法案》，限制公职人员发行数字资产 | 616 页合并文本下周提交全院表决，伦理条款禁止总统等公职人员及配偶在任内发行或担保数字资产（允许投资）。该条款直接指向 TRUMP、WLFI 等政治 meme 币的供给端与合规预期，若通过将系统性压制政治 meme 板块估值，属板块级监管变量。 | [币安广场](https://www.binance.com/zh-CN/square/post/347559918659282) | 0.72 | 0.60 | 0.90 | 0.85 | 0.85 | **0.48** |

**去重与淘汰记录**：Jimothy 两条为"白宫推文拉盘"与"聪明钱链上数据"两个不同事件指纹（{Jimothy, 白宫推文, +60%} vs {Jimothy, 聪明钱浮盈, 596x}），不归簇但同主题连续出现，混排层已确认多样性可接受。淘汰项：Stable 链 Fefer memecoin（Rel 0.55 但 PROMO 体裁风险 + 与 [Odaily Ave.ai 通稿](https://www.odaily.news/newsflash) 同簇，簇内仅保留 [X 故事](https://x.com/i/trending/2080268703980208480)，Score 0.31 未进前三）；Dogecoin BBPoW 提案（[X](https://x.com/i/trending/2079310300294312007)，Rel 0.75 但 T=0.3 时效衰减，Score 0.33 列第 4 备选）；$ANSEM 上涨 20%（PRICE_NOISE 体裁，Rel 上限 0.4 硬门淘汰）；"交易者反思 DOGE 崛起"（ANALYSIS 弱主体，Rel 0.45 硬门淘汰）。

---

### 板块 2：游戏（赛道型）— 宁缺毋滥触发，仅出 1 条

| # | 标题 | 总结 | 来源链接 | Rel | T | H | A | M | Score |
| :-: | :--- | :--- | :--- | :-: | :-: | :-: | :-: | :-: | :-: |
| 1 | 加密游戏公会 GamingGridx 在链上 MMO Senkai 举办大型 Game Night | 亚洲头部 Web3 游戏公会 GamingGridx 于 7 月 23 日在低多边形链上 MMO Senkai 组织 Game Night，玩家在钓鱼、挖矿、农耕的玩家驱动经济中竞逐 200 美元奖池，参与人数可观。事件反映链游社区活跃度回暖，但涉及项目均无币安成分币，对板块价格传导有限，定位为生态动态而非交易信号。 | [X 故事 7/23](https://x.com/i/trending/2080300354936398282) | 0.62 | 0.75 | 0.50 | 0.45 | 0.30 | **0.24** |

**宁缺毋滥说明**：候选池 8 条中仅此 1 条以"游戏板块为主角"。以下全部拒绝召回——Kaito AI 预告（主角是 AI 板块成分币 KAITO，Rel_游戏=0.15，BC-1.4 视角改写铁律：不允许写成"AI 热度分流游戏注意力"硬揰进游戏板块）；Winna 赌客损失 730 万美元（赌博≠GameFi，Rel 0.3）；Sui 无 Gas 转账（一层网络新闻，Rel 0.2）；Pump.fun 营收辩论（meme/Solana 新闻，Rel 0.1）；Nova 公会小型活动（Rel 0.55 过硬门但与第 1 条同为"公会活动"，影响面 M=0.15 更低，Score 0.18，混排层多样性裁决只保留 1 条公会活动类）。线上版本此板块 3 条全是 AI/meme 新闻（相关性 1/10），v5 宁可只出 1 条。

---

### 板块 3：bStocks（平台机制型）

| # | 标题 | 总结 | 来源链接 | Rel | T | H | A | M | Score |
| :-: | :--- | :--- | :--- | :-: | :-: | :-: | :-: | :-: | :-: |
| 1 | 币安 VIP 为股票与 bStocks 交易推出限时 3 倍成交量乘数 | 币安公告为 VIP 用户的股票及 bStocks 交易提供限时 3 倍成交量乘数激励。这是 bStocks 机制本身的规则/激励变化（0 跳直接主体），直接影响板块交易量与用户参与意愿，属机制型板块最高优先级事件。 | [币安广场](https://www.binance.com/zh-CN/square/post/347760354142290) | 0.95 | 0.70 | 0.55 | 1.00 | 0.70 | **0.67** |
| 2 | Alphabet 股价盘前跌 5%，自由现金流首次转负 | 谷歌母公司 Q2 财报显示自由现金流转负、未来支出承诺升至 8110 亿美元，股价盘前跌 5%（GOOGL bStock 同步 -7.9%）。GOOGL 为 bStocks 成分正股，财报级事件经 1 跳直接传导至对应代币化股票价格，属成分标的重大基本面变化。 | [币安广场](https://www.binance.com/zh-CN/square/post/347815201789713) | 0.55* | 0.75 | 0.80 | 0.80 | 0.75 | **0.31** |
| 3 | ORTEX：SpaceX 做空者 IPO 以来累计账面利润达 155 亿美元 | SPCX 跌至 110.85 美元创 IPO 以来新低，56% 流通股被借出做空，做空者账面获利 155 亿美元。SPCX 对应 bStock 为板块热门成分，正股破发与极端空头拥挤度直接映射到代币化股票的价格与情绪，利空信号明确。 | [币安广场](https://www.binance.com/zh-CN/square/post/347817067617633) | 0.55* | 0.70 | 0.75 | 0.75 | 0.70 | **0.29** |

*注：按 BC-1.6 传导链规则，单一成分正股自身重大事件 = 1 跳，Rel 封顶 0.55。
**去重与淘汰记录**：SPCX 事件簇合并 3 条（BlockBeats 快讯、[Odaily 15:27](https://www.odaily.news/newsflash)、币安广场 ORTEX 条），归一化三元组《SpaceX 做空者，账面获利，155 亿》一致 → 无条件同簇，保留权威+完整度最高的币安广场条；Hyperliquid 巨鲸 SPCX 多单浮亏（[X/OnchainLens](https://x.com/OnchainLens/status/2080307344760811890)）为同标的不同事件，Score 0.22 未进前三。淘汰项："美股指开盘走低：科技抛售+中东紧张"（[币安广场](https://www.binance.com/zh-CN/square/post/347854236600817)，大盘情绪 ≥2 跳，Rel 封顶 0.4 硬门淘汰——对应线上"芯片股抛售过头"badcase 同款）；瑞银下调 TSLA 目标价（[币安广场](https://www.binance.com/zh-CN/square/post/347853374878049)，1 跳合法，Score 0.26 列第 4 备选）；礼来 2027 申报肥胖药（[币安广场](https://www.binance.com/zh-CN/square/post/347842375631202)，1 跳但 M=0.4，Score 0.21 备选）；SEC 24 小时交易圆桌（[SEC 官网](https://www.sec.gov/newsroom/press-releases/2026-69-sec-announces-roundtable-preparations-24-hour-trading)，利好代币化股票叙事但属 2 跳传导，Rel 0.4 硬门淘汰）；"昨夜今晨重要资讯"类 ROUNDUP 全部体裁淘汰。

---

### 板块 4：Launchpool（平台机制型）— 宁缺毋滥触发，仅出 1 条

| # | 标题 | 总结 | 来源链接 | Rel | T | H | A | M | Score |
| :-: | :--- | :--- | :--- | :-: | :-: | :-: | :-: | :-: | :-: |
| 1 | 币安理财竞技场上线限时活动，USDe 最高 35% 年化并联动 Launchpool | 币安理财竞技场活动（7/17-7/24）提供 USDe 限时最高 35% 年化，且 BNB 活期/定期持仓在有 Launchpool 项目时自动参与挖矿。该活动直接涉及 Launchpool 参与资产（BNB）的收益机制联动，属机制关联的规则/收益变化，但非新一期项目官宣，信号强度中等。 | [币安官网活动页](https://www.binance.com/zh-CN/earn) ／ [币安广场](https://www.binance.com/zh-CN/square/news/all) | 0.60 | 0.40 | 0.40 | 1.00 | 0.40 | **0.24** |

**宁缺毋滥说明**：检索币安公告、币安广场、X（关键词 Binance Launchpool / Megadrop，96h 窗口）均未发现新一期 Launchpool 项目官宣。按板块类型化边界，以下全部拒绝：SK 海力士 ADR 套利（线上 badcase 同款陷阱，与 Launchpool 零关联，Rel 0.05）；Pendle 类"收益叙事"新闻（BC-1.7：叙事相近不构成机制型板块相关性）；巨鲸 1860 万美元 ETH 从币安提出质押 Ether.fi（[X](https://x.com/i/trending/2079140480412000662)，主角是 Ether.fi 质押，Rel 0.2）。线上版本此板块靠 Pendle 路线图重复 2 条 + SK 海力士凑数，v5 输出 1 条真实机制关联新闻。

---

### 板块 5：Megadrop（平台机制型）— 宁缺毋滥触发，出 0 条

| # | 标题 | 总结 | 来源链接 | Rel | T | H | A | M | Score |
| :-: | :--- | :--- | :--- | :-: | :-: | :-: | :-: | :-: | :-: |
| — | （本周期无符合相关性硬门的内容，板块空输出） | — | — | — | — | — | — | — | — |

**宁缺毋滥说明**：近 96 小时无新一期 Megadrop 项目官宣、无规则变更、无历史成分项目（BB、LISTA 等）重大事件。候选池中最接近的 4 条全部拒绝：币安广场 CreatorPad BABY 代币券活动（CreatorPad 是内容任务平台，非 Megadrop 机制，Rel 0.25）；学习赚币 TURTLE 问答（属"最新上币"板块，Rel 0.2）；币安 Alpha O 交易竞赛（[币安广场](https://www.binance.com/zh-CN/square/post/347812014239026)，Alpha 板块事件，Rel 0.15）；理财竞技场活动（已归 Launchpool，Megadrop 不涉及 BNB 活期自动参与，Rel 0.3）。**空板块输出建议前端处理**：展示"本周期暂无 Megadrop 相关热点"占位文案或回退展示机制介绍卡，优于硬塞不相关内容。

---

### 板块 6：基础架构 Infrastructure（赛道型）

| # | 标题 | 总结 | 来源链接 | Rel | T | H | A | M | Score |
| :-: | :--- | :--- | :--- | :-: | :-: | :-: | :-: | :-: | :-: |
| 1 | Keeta 与 LayerZero 合作，将代币化银行存款带向多链 | 双方 7 月 23 日宣布合作，通过 LayerZero 跨链协议将代币化商业银行货币部署至 Ethereum、Solana、Base 等公链。ZRO 为基础架构板块成分币且是事件直接主体，银行级 RWA 用例落地扩展了跨链消息层的商业边界，对板块叙事构成实质利好。 | [X 故事 7/23](https://x.com/i/trending/2080294127233651078) | 0.85 | 0.85 | 0.60 | 0.60 | 0.60 | **0.51** |
| 2 | United Stables 接入 Chainlink 预言机与跨链工具，保障 U 稳定币扩展 | BNB Chain 上发行的 U 稳定币在安全审查后接入 Chainlink 数据预言机与 CCIP 跨链工具。LINK 为板块核心成分币且是事件直接受体，稳定币采用案例增强 Chainlink 的收入叙事。 | [X 故事 7/23](https://x.com/i/trending/2079213747173011697) | 0.80 | 0.70 | 0.45 | 0.55 | 0.50 | **0.38** |
| 3 | BNB Chain 稳定币 Balance Coin 遭预言机漏洞攻击，价格崩至 0.001 美元 | 比特币抵押型稳定币 Balance Coin 7 月 22 日因单笔交易预言机操纵漏洞从 1 美元崩至 0.001 美元，PeckShield 与慢雾均确认攻击路径。预言机安全是板块核心命题，但该币市值/TVL 仅百万美元量级，实际受影响资金有限，仅作板块级风险预警参考。 | [X 故事 7/22](https://x.com/i/trending/2079799323567739330) | 0.75 | 0.65 | 0.55 | 0.60 | 0.30† | **0.29** |

† Balance Coin 按 skill v5.1 "M 分先查市值"规则修正：市值/TVL 仅百万美元量级属微型资产，ScopeFactor 封顶 0.2，作为预言机板块级风险预警上浮至 M=0.30（原误打 0.75，即 BC-5.3 badcase），排名由第 2 降至第 3。
**去重与淘汰记录**：线上此板块曾 3 条全部为 Ondo×FINRA 重复——本次候选池两两归一化校验无同簇。淘汰项：BitMEX 关闭交易所（[币安广场](https://www.binance.com/zh-CN/square/post/347832416412050)，交易所运营事件与"基础架构=公链底层/预言机/跨链"板块定义不符，Rel 0.4 硬门淘汰）；SEC 15 万美元和解以太坊记录诉讼（[CMC](https://coinmarketcap.com/headlines/news/)，程序性诉讼 M=0.2，Score 0.19 备选）；NEAR v2.13 抗量子升级（[X](https://x.com/i/trending/2079216773497258365)，NEAR 归一层网络板块，Rel_infra 0.45 硬门淘汰）；Lightning Labs Wavelength（[X](https://x.com/i/trending/2079667031218020549)，Rel 0.55 过门但 H=0.3，Score 0.20 列第 4 备选）。

---

### 板块 7：AI（赛道型，加密 AI）— 宁缺毋滥触发，仅出 2 条

| # | 标题 | 总结 | 来源链接 | Rel | T | H | A | M | Score |
| :-: | :--- | :--- | :--- | :-: | :-: | :-: | :-: | :-: | :-: |
| 1 | Kaito AI 官方发布神秘预告，KAITO 代币应声上涨 | Kaito AI 7 月 20 日在官方账号发布预告引发海量互动，社区猜测指向 Season 2 空投、新工具或 Kaito 2.0 升级，KAITO 代币同步上涨。KAITO 为 AI 板块成分币且是事件唯一主角，官方预告+价格反应构成板块内明确的短线催化剂；需注意预告未兑现前存在"买预期卖事实"回撤风险。 | [X 故事 7/20](https://x.com/i/trending/2079232993118531590) | 0.85 | 0.35 | 0.75 | 0.75 | 0.55 | **0.46** |
| 2 | World 调整 WLD 代币经济学：7 月 24 日起日解锁量削减 43% | 据 Worldcoin 官方公告，WLD 整体日解锁量自 7 月 24 日起由约 510 万枚降至约 290 万枚（社区分配由 320 万降至 160 万）。WLD 为 AI 板块权重成分币，供给端收缩 43% 直接改善抛压结构，属代币经济学层面的实质利好，今日正式生效具备强时效性。 | [TechFlow](https://m.techflowpost.com/newsletter/119439) ／ [BlockTempo](https://www.blocktempo.com/worldcoin-wld-token-unlock-rate-to-decrease-by-43-in-july-2026/) | 0.82 | 0.85 | 0.55 | 0.80 | 0.65 | **0.52** |

**宁缺毋滥说明**：按 Score 排序 WLD 条列第 1、Kaito 列第 2。候选池 11 条中 Web2 AI 陷阱全部拦截（BC-5.1 泛科技规则）：Etched 3 亿美元融资（红杉 AI 芯片，无代币，Rel 0.1）；xAI GROK 4.5 全端推送（Rel 0.1）；OpenAI Presence 企业平台（Rel 0.05）；白宫 AI 顾问指控 Moonshot 抄袭（[币安广场](https://www.binance.com/zh-CN/square/post/347506996226017)，Rel 0.15）；谷歌 Gemini 接近 10 亿用户（Rel 0.05）；梁文锋投资人会议（DeepSeek Web2，Rel 0.1）。Franklin Templeton"区块链驱动 Agentic AI 经济"（[X](https://x.com/i/trending/2079882206407692552)）为机构观点 ANALYSIS 体裁，Rel 0.6 过门但 M=0.25，Score 0.20 列第 3 备选，混排层判定信息增量不足未出。线上版本此板块曾出现 Kaito×X 合作重复 2 条 + Coinbase 新闻误绑 KAITO ticker，v5 输出 2 条互不重复、ticker 校验通过的内容。

---

### 板块 8：Solana（公链生态型）

| # | 标题 | 总结 | 来源链接 | Rel | T | H | A | M | Score |
| :-: | :--- | :--- | :--- | :-: | :-: | :-: | :-: | :-: | :-: |
| 1 | Solana 上线链上治理机制，验证者投票门槛设为 10 万 SOL | Solana 正式启动链上治理（SGP 验证者投票），参与门槛 10 万 SOL。这是链本身的协议层升级（公链生态型板块的最高优先级主角），治理去中心化进程直接影响 SOL 的长期估值叙事与机构接受度。 | [CoinMarketCap](https://coinmarketcap.com/alexandria/article/solana-launches-on-chain-governance-sgp-validator-voting) | 0.92 | 0.60 | 0.65 | 0.75 | 0.70 | **0.60** |
| 2 | Solana 近五个月首次登顶全链收入榜，超越 Tron 与以太坊 | 依托 DeFi 协议、活跃 dApp 与 memecoin 交易量，Solana 链收入五个月来首次重回第一。链级基本面数据（收入=真实使用付费）是 SOL 估值的核心支撑指标，登顶信号对板块情绪与资金流具有直接正向影响；当前 SOL 于 74-79.4 美元区间盘整，基本面与价格背离值得关注。 | [X 故事 7/21](https://x.com/i/trending/2079163126130290851) ／ [CMC 行情分析](https://coinmarketcap.com/headlines/news/) | 0.90 | 0.55 | 0.65 | 0.55 | 0.70 | **0.54** |
| 3 | Solana 代币化资产 Q2 达 58 亿美元创纪录，代币化股票占链上交易 97% | Q2 Solana 上代币化资产规模达 58 亿美元，其中代币化股票 48 亿（为 Q1 的 4 倍以上），占全链上股票交易的 97%；链上代币化股票持有人已突破 67 万。RWA 是 Solana 当前最强的真实需求增长曲线，链级数据强化"机构级资产发行链"定位。 | [X 故事 7/22](https://x.com/i/trending/2079288663196709019) | 0.88 | 0.50 | 0.60 | 0.55 | 0.65 | **0.48** |

**去重与淘汰记录**：代币化资产 58 亿与持有人破 67 万（[X](https://x.com/i/trending/2080023218853703710)）主体和数据维度高度重叠（cosine≈0.78），归为同簇，保留信息量更大的 58 亿条并将持有人数据并入总结。淘汰项：Jimothy 白宫推文（已在 MEME 板块召回，跨板块混排去重：同一事件不在两个板块同时出主卡，Solana 侧 Rel 0.6 低于 MEME 侧 0.9，让位）；Lead Bank 品牌视频（PROMO 体裁，Rel 上限 0.3 淘汰）；Chris.sol 质疑 Superteam（社区争议 M=0.2，Score 0.15）；Pump.fun BOOST 模式（[X](https://x.com/i/trending/2079594990091817229)，Rel 0.65 过门，Score 0.35 列第 4 备选）；Forward Industries 增持 SOL 至 755 万枚（[CMC](https://coinmarketcap.com/alexandria/article/forward-industries-sol-treasury-expands-7-55-million-sol)，Score 0.33 备选）。

---

## 三、评测结论与线上对照

| 维度 | 线上版本（doc badcase） | v5 mock 结果 |
| :--- | :--- | :--- |
| 相关性 | 游戏板块 1/10、bStocks 0/10，跨板块硬揰普遍 | 全部召回条 Rel≥0.55，游戏/AI/Launchpool 宁缺毋滥不硬揰 |
| 重复率 | 6 个板块出现同事件重复，infra 3 条全重 | 0 重复；SPCX 3 源归簇、Solana 代币化数据归簇均被拦截 |
| 无效内容 | "昨夜今晨重要资讯"类汇总占位 | ROUNDUP/PROMO/PRICE_NOISE 体裁全部源头淘汰 |
| ticker 误绑 | KAITO/USDC/NVDA 误标 | 全部通过成分币白名单交叉校验 |
| 出条策略 | 每板块硬凑 3 条 | 16/24 条，Megadrop 空输出、游戏与 Launchpool 各 1 条、AI 2 条 |

**给评测同学的三个关注点**：第一，游戏板块出 1 条是否可接受，取决于产品侧对"空/少内容板块"的前端兜底设计（建议回退到板块行情卡或机制介绍卡）；第二，bStocks 板块 1 跳正股新闻 Rel 封顶 0.55 导致 Score 偏低，若线上觉得该类内容价值高，可将封顶调至 0.65 做 A/B；第三，X 故事链接为聚合页（x.com/i/trending/{id}），若需可下钻到具体推文级链接。

---

*评测由 Manus AI 基于 skill v5 于 2026-07-24 生成；所有新闻均为 2026-07-20~24 真实事件，链接可直接访问验证。*
