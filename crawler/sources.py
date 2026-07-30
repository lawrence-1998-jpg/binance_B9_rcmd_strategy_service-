"""
数据源配置 v2.0 - 全部经过 2026-07-25 实测验证
分层：官方RSS直连 / 自建RSSHub(127.0.0.1:1200) / HTML抓取 / X API / DDG搜索
"""

RSSHUB = "http://127.0.0.1:1200"

# ── 官方 RSS 直连（英文媒体 + 中文可用源）────────────────────────────
RSS_SOURCES_P0 = [
    # 英文头部媒体
    ("https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml", "CoinDesk", "en", 5),
    ("https://www.theblock.co/rss.xml",                                "TheBlock",  "en", 5),
    ("https://cointelegraph.com/rss",                                  "Cointelegraph", "en", 4),
    ("https://decrypt.co/feed",                                        "Decrypt",   "en", 4),
    ("https://blockworks.co/feed",                                     "Blockworks","en", 4),
    # 中文可用官方 RSS
    ("https://www.wublock123.com/rss",                                 "吴说区块链", "zh", 5),
    ("https://www.techflowpost.com/rss.aspx",                          "TechFlow深潮", "zh", 4),
    # 美股/宏观
    ("https://finance.yahoo.com/news/rssindex",                        "YahooFinance","en", 3),
]

# ── 自建 RSSHub 中文源（docker rsshub @127.0.0.1:1200）───────────────
RSS_SOURCES_RSSHUB = [
    (f"{RSSHUB}/theblockbeats/newsflash",  "BlockBeats快讯", "zh", 5),
    (f"{RSSHUB}/theblockbeats/article",    "BlockBeats文章", "zh", 4),
    (f"{RSSHUB}/jinse/lives",              "金色财经",       "zh", 4),
    (f"{RSSHUB}/followin/news/zh-Hans",    "Followin快讯",   "zh", 3),
    (f"{RSSHUB}/followin/news/en",         "Followin-EN",    "en", 3),
    # 币安上币/合约公告（利好信号，非竞对；OKX/Coinbase 公告已按要求移除）
    (f"{RSSHUB}/binance/announcement/new-cryptocurrency-listing", "币安上币公告", "zh", 5),
]

# ── P1 英文补充 ─────────────────────────────────────────────────────
RSS_SOURCES_P1 = [
    ("https://thedefiant.io/feed",                                     "TheDefiant","en", 4),
    ("https://www.coindesk.com/arc/outboundfeeds/rss/category/policy-regulation/?outputType=xml", "CoinDesk-Policy", "en", 5),
    # 2026-07-30 4→5：Lawrence 定调"CNBC 信源覆盖的默认权威性=5"，四个频道拉齐
    ("https://www.cnbc.com/id/10000664/device/rss/rss.html",           "CNBC-Finance","en", 5),
]

# ── P2 二线英文加密媒体（2026-07-26 新增）───────────────────────────
#
# 起因：召回覆盖率交叉验证实测（31 个独立源 vs 本系统）显示事件级覆盖率仅
# 29.9%，其中 77.4% 的漏召是"任何抓取路径都没有这条内容"（信源盘子太小，
# 不是新鲜度过滤或粗去重误杀——两者实测误杀率均为 0）。
#
# 这 10 个源全部满足：①对照测试里实测 HTTP 200、标准 RSS、零改造成本；
# ②量化贡献扎实——199 个漏召事件里有 47 条的对照源就是这 10 家，仅
# Bitcoinist 一家就贡献 6 条协议治理类漏召（Frax/EigenLayer/Uniswap/Arbitrum
# 提案动态，这是现有信源体系的成片空白）。
#
# 权威分参考 crawler/pipeline.py SYSTEM_PROMPT 里的权威分级：二线独立采编
# 英文媒体给 3（介于头部媒体 4 和聚合/搜索 2~3 之间）。
RSS_SOURCES_P2 = [
    ("https://beincrypto.com/feed/",       "BeInCrypto",     "en", 3),
    ("https://cryptoslate.com/feed/",      "CryptoSlate",    "en", 3),
    ("https://news.bitcoin.com/feed/",     "Bitcoin.com",    "en", 3),
    ("https://coinjournal.net/feed/",      "CoinJournal",    "en", 3),
    # Bitcoinist 已除名（2026-07-26 裁决）：它同时出现在 web_search 的内容农场
    # 黑名单里，两个口径打架。用两份证据统一成"不收"：①库内实测 8 条事件
    # 0 条 VERIFIED、7 条 UNVERIFIED、6 条孤证，质量分 0.609 全场垫底——它的
    # 独有贡献基本都是无从佐证的孤证软文；②外部核查（Ground News 评级
    # "factuality unknown"，赞助内容与编辑内容区分不清）。当初收它是因为
    # 覆盖率测试里它贡献 6 条协议治理漏召，但那类内容 Blockworks/TheDefiant
    # 等也覆盖，不值得为此吞下软文风险。
    ("https://www.newsbtc.com/feed/",      "NewsBTC",        "en", 2),
    ("https://cryptobriefing.com/feed/",   "CryptoBriefing", "en", 3),
    ("https://ambcrypto.com/feed/",        "AMBCrypto",      "en", 3),
    ("https://u.today/rss",                "U.Today",        "en", 3),
    ("https://protos.com/feed/",           "Protos",         "en", 3),
]

# ── P3 宏观财经源（2026-07-26 新增）──────────────────────────────────
#
# 起因：同一次覆盖率测试显示宏观美股交叉类覆盖率最差（34.8%，五类里最低），
# 而这恰恰是 B9 的差异化卖点。漏召的都是"先发生在传统财经媒体、几小时后才被
# 加密媒体转述"的内容——油价、关税、芯片股、央行政策。此前只接了
# YahooFinance / CNBC-Finance 两个泛财经源，专门做宏观快讯的媒体一个没有。
#
# 路透社评估过：feeds.reuters.com 的 DNS 已注销，主站 Akamai 反爬返回 401，
# 直连不可行；Google News site: 代理测试显示其内容对加密/宏观范围的贡献很小
# （92 条里仅 2 条在范围内），故不接入，仅记录评估结论。
RSS_SOURCES_MACRO = [
    ("https://www.investing.com/rss/news_301.rss", "Investing-Crypto", "en", 3),
    ("https://www.investing.com/rss/news_14.rss",  "Investing-Econ",   "en", 3),
]

# ── 全球主流市场源（2026-07-28 新增）─────────────────────────────────
#
# 起因：Lawrence 转达老板指示——B9 只爬币圈新闻不够，美股/港股/日股/韩股/
# 世界主要经济新闻（对股市、资产、价格有直接影响、能调动情绪的）必须接，
# 依据是"用户买的是价格不是价值"，同时同时买卖股票和币的人（对标 Robinhood）
# 需要一个能同时看到两边的信息流。**明确不要 A 股**（沪深/上证/深证/创业板/
# 科创板个股动态），这类内容不在任何查询词里，且下游有关键词黑名单兜底
# （见 crawler/web_search.py 的 _A_SHARE_KEYWORDS_RE）。
#
# 全部实测 HTTP 200、标准 RSS：CNBC 三个频道覆盖美股大盘/宏观/投资，
# MarketWatch 补美股，Nikkei Asia 覆盖日股为主兼顾亚太，SCMP 覆盖港股，
# Korea Herald 覆盖韩股。都是国际公认的主流财经媒体，直接给最高权威档
# （对应 crawler/pipeline.py SYSTEM_PROMPT 里 score_authority 的"顶级媒体"
# 档位），不需要额外的媒体公信力判断。
RSS_SOURCES_GLOBAL_MARKETS = [
    ("https://www.cnbc.com/id/100003114/device/rss/rss.html", "CNBC-TopNews",   "en", 5),
    ("https://www.cnbc.com/id/20910258/device/rss/rss.html",  "CNBC-Economy",   "en", 5),
    ("https://www.cnbc.com/id/15839069/device/rss/rss.html",  "CNBC-Investing", "en", 5),
    ("https://feeds.content.dowjones.io/public/rss/mw_topstories", "MarketWatch", "en", 5),
    ("https://asia.nikkei.com/rss/feed/nar",                  "NikkeiAsia",     "en", 5),
    # 2026-07-28 当天修正：最初接的是 rss/91，看名字以为是商业频道，实际是 SCMP 的
    # **综合新闻**频道——上线后第一轮就抓回大量"香港网红去世""山东夫妻坠井获救"
    # "补习中心负责人判囚"这类社会新闻，全部要付一遍 LLM 结构化的钱才被判成 D 档
    # 丢掉。换成 rss/92（Business）+ rss/12（Global Economy）两个真正对口的频道。
    # 教训：接 RSS 时不能只看 URL 猜频道，必须打开 <title> 确认（这次实测
    # rss/91=News、92=Business、12=Global Economy、2=Hong Kong、4=China、3=Asia）。
    ("https://www.scmp.com/rss/92/feed/",                     "SCMP-Business",  "en", 4),
    ("https://www.scmp.com/rss/12/feed/",                     "SCMP-GlobalEcon", "en", 4),
    ("https://www.koreaherald.com:443/rss/020000000000.xml",  "KoreaHerald",    "en", 3),

    # 2026-07-29 补：老板点名要的两个头部权威媒体（"对CNBC、ForbesNews等头部
    # 权威媒体有的内容，直接boost"），之前压根没接——查过库里唯二的 2 条
    # Forbes/Bloomberg 记录，来源都是 web_search 搜索结果里恰好引用了这两个
    # 域名，不是真正的媒体订阅。
    #
    # Bloomberg：feeds.bloomberg.com 会 301 跳转，实测 4 个频道跳转后都是
    # 200、20 条、内容干净（markets/economics/technology/politics 全是真财经
    # 新闻，无噪音）。requests.get 默认跟随重定向，不需要额外处理。
    ("https://feeds.bloomberg.com/markets/news.rss",          "Bloomberg-Markets",    "en", 5),
    ("https://feeds.bloomberg.com/economics/news.rss",        "Bloomberg-Economics",  "en", 5),
    ("https://feeds.bloomberg.com/technology/news.rss",       "Bloomberg-Technology", "en", 5),
    ("https://feeds.bloomberg.com/politics/news.rss",         "Bloomberg-Politics",   "en", 5),

    # Forbes：吸取过 SCMP rss/91 的教训（不能只看 URL 猜频道，必须读 <title>
    # 确认），逐个试了 investing/markets/wealth/leadership/digital-assets/
    # innovation 六个看起来对口的路径——**只有 business 和 innovation 两个
    # 返回 200**，且 innovation 实测抽样全是 iOS 升级指南/电影流媒体/拼字
    # 游戏答案，零财经内容，没有加。business 抽样 8 条里 2 条是真市场新闻
    # （Lucid Motors 涨 20%、消费品牌注意力经济），其余是体育/娱乐/犯罪新闻
    # 挂着"Business"分类——如实说：这是 Forbes 免费 RSS 能拿到的最干净选项，
    # 噪音比例明显高于上面几家，但仍然值得接：噪音走的是已有的 D 档过滤路径
    # （不会露出到首页），真正的市场新闻不会被漏掉。
    ("https://www.forbes.com/business/feed/",                 "Forbes-Business",      "en", 4),

    # 同一轮里顺带验证过的另外两家：WSJ 与 FT，都是实测 200、内容干净对口
    # （WSJT Markets 首条"Stocks Sink in Broad AI Rout"；FT 首条"Chip stocks
    # tumble as AI sell-off deepens"，均为真实大盘新闻）。注意 FT 这个 feed
    # 是压缩成单行的 XML，`grep -c "<item>"` 这种按行计数的探测方法会误判成
    # "只有 1 条"——本次是拿 `grep -o | wc -l` 重新量了一遍才发现之前测错，
    # 记录下来避免同样的测量方法坑到下一次信源评估。
    # WSJ World News / FT 只接了各自最对口的一个频道，没有照单全收——两家的
    # 其他频道（WSJ World、地缘政治类）已经被 Bloomberg-Politics/CNBC-TopNews/
    # macro_policy 覆盖，再接会增加 LLM 成本却不增加净召回。
    # 2026-07-29 当天修正：接的时候 feeds.a.dj.com/rss/RSSMarketsMain.xml 返回
    # 200、标题看着也是真新闻（"Stocks Sink in Broad AI Rout Sparked by China's
    # DeepSeek"），当时只验证了"能不能打开、内容像不像新闻"，没查 <lastBuildDate>——
    # 结果这个 feed 从 2025-01-27 起就没更新过（channel 级时间戳也冻结在那天），
    # 里面的"DeepSeek 引发抛售"是真实存在过的旧新闻，不是抓错，是**这个 feed 本身
    # 已经停更 18 个月**，每次抓都会被事件时间闸正确拦掉，召回率恒为 0。
    # 换成 feeds.content.dowjones.io（道琼斯官方内容平台的真实域名——MarketWatch
    # 那条本来就是这个域名下的），实测最新条目是几小时前，内容也对得上当前市场。
    # 教训和 SCMP rss/91 那次一样：光看返回内容"像不像新闻"不够，必须验证
    # lastBuildDate/首条 pubDate 是不是真的在更新。
    ("https://feeds.content.dowjones.io/public/rss/RSSMarketsMain", "WSJ-Markets", "en", 5),
    ("https://www.ft.com/rss/home",                           "FT-Home",              "en", 5),
]

# ── HTML 抓取源（无 RSS，直接解析页面）───────────────────────────────
HTML_SOURCES = [
    {
        "name": "ChainCatcher",
        "url": "https://www.chaincatcher.com/news",
        "lang": "zh",
        "authority": 4,
        "parser": "chaincatcher",   # a[href^=/article/]，标题去尾部时间戳
        "base_url": "https://www.chaincatcher.com",
    },
    {
        "name": "PANews",
        "url": "https://www.panewslab.com/zh/newsflash",
        "lang": "zh",
        "authority": 4,
        "parser": "panews",         # Nuxt SSR，提取 /zh/articles/ 链接
        "base_url": "https://www.panewslab.com",
    },
]

# ── 币安广场搜索（ddgs 包）───────────────────────────────────────────
BINANCE_SQUARE_QUERIES = [
    "site:binance.com/en/square meme coin trending",
    "site:binance.com/en/square smart money whale",
    "site:binance.com/en/square listing launchpool",
    "site:binance.com/en/square hack exploit security",
    "site:binance.com/zh-CN/square 热点",
    "binance square crypto news today",
]

# ── X API KOL 列表（每轮拉取，注意配额；核心热点 KOL 优先）─────────────
# 结构: (username, 权威分, 分类)
CRYPTO_KOLS = [
    # 中文/热点核心（召回画风关键）
    ("WuBlockchain",   4, "media"),      # 吴说英文，币圈热点风向标
    ("wublockchain12", 4, "media"),      # 吴说中文
    ("BlockBeatsAsia", 4, "media"),
    ("PANewsCN",       4, "media"),
    # 交易所/官方
    ("binance",        5, "exchange"),
    ("binancezh",      5, "exchange"),   # 币安中文，广场热点补充
    ("cz_binance",     4, "kol"),
    ("heyibinance",    4, "kol"),
    # 链上数据/聪明钱
    ("lookonchain",    4, "onchain"),    # 聪明钱动向核心源
    ("spotonchain",    4, "onchain"),
    ("EmberCN",        4, "onchain"),    # 中文链上侦探
    ("glassnode",      4, "onchain"),
    # 安全预警
    ("peckshield",     5, "security"),
    ("SlowMist_Team",  5, "security"),
    ("CertiKAlert",    4, "security"),
    # 研究/宏观
    ("MessariCrypto",  4, "research"),
    ("santimentfeed",  3, "research"),
    # 监管
    ("SECGov",         5, "regulator"),
    # ── v2.1 扩充（2026-07-26，全部经 X API 验证存在且活跃）──────────
    # 快讯速报（分钟级抢先源）
    ("bwenews",        4, "media"),      # 方程式新闻 BWEnews，91k粉，最快中文快讯之一
    ("Tree_of_Alpha",  4, "media"),      # 247k粉，交易员快讯（推文少但条条重磅）
    ("WatcherGuru",    4, "media"),      # 4.5M粉，全球加密+宏观突发
    ("solidintel_x",   4, "media"),      # 93k粉，快讯速报
    # 中文媒体补位（补 Odaily/Foresight RSS 失效缺口）
    ("OdailyChina",    4, "media"),      # 73k粉，Odaily星球日报官方
    ("Foresight_News", 4, "media"),      # 63k粉，Foresight News 官方（注意大小写）
    # 英文头部媒体（RSS 已有，X 版时效更快，聚合去重兜底）
    ("CoinDesk",       4, "media"),      # 3.9M粉
    # 链上/聪明钱补充
    ("whale_alert",    4, "onchain"),    # 2.9M粉，大额转账警报
    ("ai_9684xtpa",    4, "onchain"),    # Ai姨 134k粉，中文链上侦探
    ("OnchainLens",    3, "onchain"),    # 44k粉，鲸鱼动向
    ("DefiLlama",      4, "onchain"),    # 369k粉，DeFi TVL/代币解锁数据
    # 币安系补充（注：BinanceNews/binance_news/BinanceUpdates 均已被X封禁，
    # 不存在可用的币安官方 news 账号；官方新闻由 binance/binancezh 主号覆盖）
    ("BinanceResearch",4, "exchange"),   # 453k粉，币安研究院
    # 宏观市场
    ("KobeissiLetter", 4, "macro"),      # 2.3M粉，宏观+美股+加密交叉
    ("unusual_whales", 3, "macro"),      # 4.8M粉，美股期权异动+宏观
]

# 每个 KOL 每轮拉取的推文数（控制 X API 配额）
X_TWEETS_PER_KOL = 5

# ── X 全网关键词搜索查询集（crawler/x_search.py 使用）─────────────────
#
# 为什么需要：KOL 时间线只能召回 32 个账号发的内容，全网搜索补的是"新闻发生了但
# 名单里没人第一时间发"的缺口——小交易所被盗、二线项目上币、区域性监管动作等。
#
# 结构: (group_id, category, query)
#   group_id  — 日志/统计用的唯一标识
#   category  — 决定客户端互动量阈值，见 x_search.MIN_ENGAGEMENT_BY_CATEGORY
#   query     — X recent search 查询串，须 < 512 字符
#
# 查询编写约定（踩过的坑）：
#   1. 每条查询是 "(同义词 OR 组) AND (限定词 OR 组)" 的两段式。只写第一段会捞回
#      大量非加密语境的噪音（hack 会命中生活妙招，approved 会命中药监审批）。
#   2. 多词短语必须加引号。X 的解析器把 (crypto ETF OR bitcoin ETF) 拆成
#      crypto AND (ETF OR bitcoin) AND ETF，不加引号语义会静默跑偏。
#   3. 一律带 -is:retweet -is:reply。转推是纯重复，回复几乎全是口水。
#   4. 不要用 min_faves/min_retweets——那是 Pro 层算子，Basic 层会整条查询报错。
#      互动量过滤在客户端做（x_search._passes_quality）。
#   5. 中英文分开查询而不是混在一条里：lang: 算子只能取单值，且中英文的同义词
#      表和噪音特征完全不同，分开才能各自调阈值。
X_SEARCH_QUERIES = [
    # ── 突发安全（最高价值，KOL 名单最容易漏的一类）──────────────────
    ("sec_en_hack", "security",
     '(hack OR hacked OR exploit OR exploited OR "security breach" OR drained) '
     '(crypto OR DeFi OR protocol OR bridge OR wallet OR exchange OR token) '
     '-is:retweet -is:reply lang:en'),
    ("sec_en_rug", "security",
     '("rug pull" OR rugged OR "stolen funds" OR "funds stolen" OR "exit scam" '
     'OR "private key" OR compromised) '
     '(crypto OR DeFi OR protocol OR project OR wallet OR token) '
     '-is:retweet -is:reply lang:en'),
    ("sec_zh", "security",
     '(被盗 OR 黑客 OR 攻击 OR 漏洞 OR 跑路 OR 卷款 OR 私钥泄露) '
     '(加密 OR 链上 OR 协议 OR 项目 OR 交易所 OR 钱包) '
     '-is:retweet -is:reply lang:zh'),

    # ── 上币 / 下架 ──────────────────────────────────────────────────
    ("list_en", "listing",
     '(listing OR "will list" OR delisting OR "will delist" OR "spot trading" '
     'OR "perpetual contract") '
     '(Binance OR Coinbase OR Upbit OR OKX OR Bybit OR Kraken) '
     '-is:retweet -is:reply lang:en'),
    ("list_zh", "listing",
     '(上线 OR 上币 OR 下架 OR 现货 OR 永续 OR 合约) '
     '(币安 OR 欧易 OR 火币 OR Upbit OR Coinbase OR 交易所) '
     '-is:retweet -is:reply lang:zh'),

    # ── 行情异动 ─────────────────────────────────────────────────────
    ("mkt_en_liq", "market",
     '(liquidated OR liquidations OR "short squeeze" OR "long squeeze" OR deleveraging) '
     '(BTC OR ETH OR bitcoin OR ethereum OR crypto) '
     '-is:retweet -is:reply lang:en'),
    ("mkt_en_move", "market",
     '(BTC OR ETH OR bitcoin OR ethereum OR solana) '
     '(plunged OR plunges OR surged OR surges OR crashed OR "all-time high" '
     'OR "breaks above" OR "falls below") '
     '-is:retweet -is:reply lang:en'),
    ("mkt_zh", "market",
     '(爆仓 OR 清算 OR 暴跌 OR 暴涨 OR 突破 OR 跌破 OR 插针) '
     '(BTC OR ETH OR 比特币 OR 以太坊 OR 大盘) '
     '-is:retweet -is:reply lang:zh'),

    # ── 监管 / 法律 ──────────────────────────────────────────────────
    ("reg_en_enforce", "regulation",
     '(SEC OR CFTC OR DOJ OR lawsuit OR sues OR subpoena OR "enforcement action" OR settlement) '
     '(crypto OR bitcoin OR ethereum OR stablecoin OR exchange) '
     '-is:retweet -is:reply lang:en'),
    ("reg_en_policy", "regulation",
     '(approved OR approval OR "executive order" OR bill OR legislation OR regulation OR ban) '
     '("crypto ETF" OR "bitcoin ETF" OR stablecoin OR "digital asset" OR CBDC OR crypto) '
     '-is:retweet -is:reply lang:en'),
    ("reg_zh", "regulation",
     '(监管 OR 立法 OR 法案 OR 批准 OR 起诉 OR 诉讼 OR 合规 OR 牌照) '
     '(加密 OR 比特币 OR 稳定币 OR 数字资产 OR 交易所) '
     '-is:retweet -is:reply lang:zh'),

    # ── 大额资金 / 巨鲸 ──────────────────────────────────────────────
    ("whale_en", "whale",
     '(whale OR whales OR "smart money" OR "whale alert") '
     '(bought OR sold OR transferred OR withdrew OR deposited OR accumulated OR dumped) '
     '-is:retweet -is:reply lang:en'),
    ("whale_zh", "whale",
     '(巨鲸 OR 鲸鱼 OR 聪明钱 OR 大户) '
     '(转入 OR 转出 OR 增持 OR 减持 OR 抛售 OR 买入 OR 提币 OR 充值) '
     '-is:retweet -is:reply lang:zh'),

    # ── 宏观传导 ─────────────────────────────────────────────────────
    ("macro_en", "macro",
     '(Fed OR FOMC OR CPI OR "rate cut" OR "interest rate" OR Powell OR inflation) '
     '(crypto OR bitcoin OR BTC OR "risk assets") '
     '-is:retweet -is:reply lang:en'),
    ("macro_zh", "macro",
     '(美联储 OR 降息 OR 加息 OR CPI OR 非农 OR 通胀 OR 鲍威尔) '
     '(比特币 OR 加密 OR 币圈 OR 风险资产) '
     '-is:retweet -is:reply lang:zh'),

    # ── 突发快讯（跨类别兜底，抓"BREAKING/快讯"这类新闻体裁标记）──────
    ("brk_en", "breaking",
     '("BREAKING" OR "JUST IN" OR "BREAKING NEWS") '
     '(crypto OR bitcoin OR ethereum OR SEC OR exchange OR token OR blockchain) '
     '-is:retweet -is:reply lang:en'),
    ("brk_zh", "breaking",
     '(快讯 OR 突发 OR 刚刚) '
     '(加密 OR 比特币 OR 以太坊 OR 币安 OR 链上) '
     '-is:retweet -is:reply lang:zh'),

    # ── 融资 / 并购 ──────────────────────────────────────────────────
    ("fund_en", "funding",
     '(raises OR raised OR "funding round" OR "Series A" OR "Series B" '
     'OR acquires OR acquisition OR IPO) '
     '(crypto OR blockchain OR Web3 OR "digital asset") '
     '-is:retweet -is:reply lang:en'),

    # ── 脱锚 / 挤兑 / 破产（尾部风险，出现即高价值）──────────────────
    ("risk_en", "risk",
     '(depeg OR depegged OR insolvent OR insolvency OR bankruptcy '
     'OR "halted withdrawals" OR "paused withdrawals") '
     '(crypto OR stablecoin OR exchange OR protocol OR USDT OR USDC) '
     '-is:retweet -is:reply lang:en'),

    # ── ETF 资金流 ───────────────────────────────────────────────────
    ("etf_en", "etf",
     '("ETF inflows" OR "ETF outflows" OR "net inflow" OR "net outflow" OR "spot ETF") '
     '(bitcoin OR ethereum OR BTC OR ETH OR solana) '
     '-is:retweet -is:reply lang:en'),

    # ── 代币经济事件（解锁/回购/销毁）────────────────────────────────
    ("unlock_en", "unlock",
     '("token unlock" OR "cliff unlock" OR vesting OR buyback OR "token burn") '
     '(crypto OR token OR protocol OR supply) '
     '-is:retweet -is:reply lang:en'),
]

# 板块标签枚举（币安 B9 真实标签）
SECTOR_LABELS = [
    "New Listing", "bStocks", "Seed", "tCommodities", "BSC", "DeFi",
    "Gaming", "NFT", "Layer1/Layer2", "Launchpad", "Payments", "Monitoring",
    "RWA", "Solana", "Fan Token", "Infrastructure", "AI", "Launchpool",
    "Megadrop", "MEME",
]
