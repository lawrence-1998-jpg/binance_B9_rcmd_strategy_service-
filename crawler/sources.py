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
    ("https://finance.yahoo.com/news/rssindex",                        "YahooFinance","en", 4),
]

# ── 自建 RSSHub 中文源（docker rsshub @127.0.0.1:1200）───────────────
RSS_SOURCES_RSSHUB = [
    (f"{RSSHUB}/theblockbeats/newsflash",  "BlockBeats快讯", "zh", 5),
    (f"{RSSHUB}/theblockbeats/article",    "BlockBeats文章", "zh", 4),
    (f"{RSSHUB}/jinse/lives",              "金色财经",       "zh", 4),
    (f"{RSSHUB}/followin/news/zh-Hans",    "Followin快讯",   "zh", 4),
    (f"{RSSHUB}/followin/news/en",         "Followin-EN",    "en", 3),
    # 币安上币/合约公告（利好信号，非竞对；OKX/Coinbase 公告已按要求移除）
    (f"{RSSHUB}/binance/announcement/new-cryptocurrency-listing", "币安上币公告", "zh", 5),
]

# ── P1 英文补充 ─────────────────────────────────────────────────────
RSS_SOURCES_P1 = [
    ("https://thedefiant.io/feed",                                     "TheDefiant","en", 4),
    ("https://www.coindesk.com/arc/outboundfeeds/rss/category/policy-regulation/?outputType=xml", "CoinDesk-Policy", "en", 5),
    ("https://www.cnbc.com/id/10000664/device/rss/rss.html",           "CNBC-Finance","en", 4),
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
    ("WuBlockchain",   5, "media"),      # 吴说英文，币圈热点风向标
    ("wublockchain12", 4, "media"),      # 吴说中文
    ("BlockBeatsAsia", 4, "media"),
    ("PANewsCN",       4, "media"),
    # 交易所/官方
    ("binance",        5, "exchange"),
    ("binancezh",      5, "exchange"),   # 币安中文，广场热点补充
    ("cz_binance",     5, "kol"),
    ("heyibinance",    5, "kol"),
    # 链上数据/聪明钱
    ("lookonchain",    5, "onchain"),    # 聪明钱动向核心源
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
    ("bwenews",        5, "media"),      # 方程式新闻 BWEnews，91k粉，最快中文快讯之一
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
