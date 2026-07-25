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

# 板块标签枚举（币安 B9 真实标签）
SECTOR_LABELS = [
    "New Listing", "bStocks", "Seed", "tCommodities", "BSC", "DeFi",
    "Gaming", "NFT", "Layer1/Layer2", "Launchpad", "Payments", "Monitoring",
    "RWA", "Solana", "Fan Token", "Infrastructure", "AI", "Launchpool",
    "Megadrop", "MEME",
]
