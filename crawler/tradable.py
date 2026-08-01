"""交易实体识别 —— "这条新闻对应哪个用户真能买到的标的"（ADR-002 块 B）。

## 起因

老板反馈排序结果"刺激标的物交易的感觉不足"。查下来根因不是缺加分项，而是
**占池一半的美股内容根本没有标的物这个字段**：`coins` 按设计只抓加密 ticker
（prompt 明写 bitcoin→btc），近 5 天实测覆盖率——

    us_stock   4163 条（50%）  有标的 32 条  → 0.8%
    crypto     1210 条         有标的 642 条 → 53%（币安可交易 47.9%）
    其余       2986 条         ~0%

整体只有 7.5%。而 Benzinga 编辑部**自己标注的真实 ticker** 一直躺在
`raw_items_staging.matched_symbols` 里（覆盖率 98.1%，dxFeed 95%），只被拿去
做优先级路由，从没进过 news_events——数据一直有，一直在被丢掉。

## 三级取数阶梯（先免费后付费）

    ① staging.matched_symbols 直通  零成本、零 prompt 改动，覆盖 Benzinga/dxFeed
    ② coins → binance_spot 校验     加密侧，market_cap.py 已有的现成判据
    ③ LLM 抽取                      长尾 RSS/搜索，要改 prompt（会让 enrich 缓存
                                    整体失效），单独排期，**不在本模块**

## "能买到"的判据（这是需求的硬约束，必须可验证而不是拍脑袋）

    加密    coin_metrics[].binance_spot == true   （币安现货在架）
    美股    ticker ∈ 大盘蓝筹白名单                （Lawrence 裁决：只标用户认得出的）
    指数ETF ∈ INDEX_ETF                            （SPY/QQQ/DIA/IWM…）
    日韩港  一律 tradable=false                    （币安用户买不到，标了是噪音）

白名单的意义：Benzinga 一条新闻最多挂 12 个 ticker，其中不少是边缘小盘股。
只展示用户真买得到、且认得出的标的，避免首页变成 ticker 刷屏。
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# ── 大盘/ETF（Lawrence 裁决的"能买到且认得出"第一档）────────────────
# 与 crawler/dxfeed_news.py 的 DXFEED_INDEX_SYMBOLS 同源，这里额外区分了
# "指数本身"（SPX/DJI 不可直接买）与"对应 ETF"（SPY/DIA 可买）。
INDEX_ETF = {
    "SPY": "标普500 ETF", "QQQ": "纳指100 ETF", "DIA": "道指 ETF",
    "IWM": "罗素2000 ETF", "VIX": "波动率指数",
    # 板块 ETF —— 需求原话"也可以是某个板块的指数"。这几支是实测 staging
    # 里真实出现频次靠前的（SOXX 26 次、XLK 15、USO 53）。
    "SOXX": "半导体 ETF", "XLK": "科技板块 ETF", "XLF": "金融板块 ETF",
    "XLE": "能源板块 ETF", "USO": "原油 ETF", "GLD": "黄金 ETF",
    "ARKK": "ARK 创新 ETF", "SMH": "半导体 ETF",
    "IBIT": "贝莱德比特币现货 ETF", "FBTC": "富达比特币现货 ETF",
    "ETHA": "贝莱德以太坊现货 ETF",
}
# 指数代码本身不是可交易标的（买不了 SPX，只能买 SPY），但要认出来做展示映射
INDEX_ONLY = {"SPX": "标普500", "DJI": "道琼斯", "IXIC": "纳斯达克", "RUT": "罗素2000"}

# ── 美股大盘蓝筹白名单 ───────────────────────────────────────────────
#
# 【维护提醒】这是一份手写表，而"手写副本必腐化"是本项目反复踩的坑。之所以
# 仍然手写：真正的 S&P500 成分股需要外部数据源（付费或爬），而这一版的目的是
# 先用零成本手段把美股覆盖率从 0.8% 拉起来，不是做一个完备的成分股服务。
# 升级路径写在 ADR-002 §四：改为从可更新数据源生成。在那之前，这份表**只增
# 不改**，且新增必须是"用户一眼认得出的公司"——这是它唯一的入选标准。
BLUE_CHIPS = {
    # 科技巨头
    "AAPL": "苹果", "MSFT": "微软", "NVDA": "英伟达", "GOOGL": "谷歌",
    "GOOG": "谷歌", "AMZN": "亚马逊", "META": "Meta", "TSLA": "特斯拉",
    "NFLX": "奈飞", "AMD": "AMD", "INTC": "英特尔", "AVGO": "博通",
    "ORCL": "甲骨文", "CRM": "Salesforce", "ADBE": "Adobe", "CSCO": "思科",
    "QCOM": "高通", "TXN": "德州仪器", "MU": "美光", "ARM": "ARM",
    "PLTR": "Palantir", "SMCI": "超微电脑", "DELL": "戴尔", "IBM": "IBM",
    "UBER": "优步", "ABNB": "爱彼迎", "SHOP": "Shopify", "SPOT": "Spotify",
    # 加密概念股（对币安用户尤其相关）
    "COIN": "Coinbase", "MSTR": "MicroStrategy", "MARA": "Marathon",
    "RIOT": "Riot", "GLXY": "Galaxy Digital", "HOOD": "Robinhood",
    "CLSK": "CleanSpark", "CIFR": "Cipher Mining", "BITF": "Bitfarms",
    # 金融
    "JPM": "摩根大通", "BAC": "美国银行", "GS": "高盛", "MS": "摩根士丹利",
    "WFC": "富国银行", "C": "花旗", "BLK": "贝莱德", "SCHW": "嘉信理财",
    "V": "Visa", "MA": "万事达", "PYPL": "PayPal", "AXP": "美国运通",
    # 医药消费工业
    "JNJ": "强生", "PFE": "辉瑞", "MRK": "默克", "LLY": "礼来",
    "UNH": "联合健康", "ABBV": "艾伯维", "TMO": "赛默飞",
    "WMT": "沃尔玛", "COST": "好市多", "HD": "家得宝", "NKE": "耐克",
    "MCD": "麦当劳", "SBUX": "星巴克", "KO": "可口可乐", "PEP": "百事",
    "PG": "宝洁", "DIS": "迪士尼", "BA": "波音", "CAT": "卡特彼勒",
    "GE": "通用电气", "F": "福特", "GM": "通用汽车", "XOM": "埃克森美孚",
    "CVX": "雪佛龙", "LMT": "洛克希德马丁", "RTX": "雷神",
    # ── 2026-08-02 按**实测频次**补充 ──────────────────────────────
    # 首版只手写了约 80 支，实测发现 us_stock 事件里 66% 能 join 到 ticker，
    # 但只有 17% 命中白名单——漏掉的样例里 DDOG/IONQ/DXC 这类用户明明认得出。
    # 这批是近 30 天 staging 里真实出现频次 Top200 中可识别的公司，
    # 用数据挑而不是凭空想，避免"我以为重要"和"实际在报道什么"脱节。
    "TSM": "台积电", "STX": "希捷", "SNDK": "闪迪", "LRCX": "泛林",
    "KLAC": "科天", "CDNS": "Cadence", "SNPS": "新思", "ASML": "阿斯麦",
    "FTNT": "Fortinet", "PANW": "Palo Alto", "CRWD": "CrowdStrike",
    "DDOG": "Datadog", "SNOW": "Snowflake", "NOW": "ServiceNow",
    "TENB": "Tenable", "ZS": "Zscaler", "NET": "Cloudflare",
    "RDDT": "Reddit", "RBLX": "Roblox", "PINS": "Pinterest",
    "RIVN": "Rivian", "LCID": "Lucid", "NIO": "蔚来", "XPEV": "小鹏",
    "CVNA": "Carvana", "IONQ": "IonQ", "RGTI": "Rigetti",
    "ENPH": "Enphase", "FSLR": "第一太阳能", "BE": "Bloom Energy",
    "GD": "通用动力", "NOC": "诺斯罗普", "UPS": "UPS", "FDX": "联邦快递",
    "BSX": "波士顿科学", "BMY": "百时美施贵宝", "AMGN": "安进",
    "GILD": "吉利德", "MRNA": "Moderna", "HUM": "Humana", "CVS": "CVS",
    "CMG": "Chipotle", "CAKE": "芝士蛋糕工厂", "DASH": "DoorDash",
    "SWKS": "思佳讯", "GLW": "康宁", "DXC": "DXC", "CSGP": "CoStar",
    "T": "AT&T", "VZ": "威瑞森", "TMUS": "T-Mobile", "CMCSA": "康卡斯特",
    "PLD": "安博", "SPGI": "标普全球", "ICE": "洲际交易所",
    "AMAT": "应用材料", "ADI": "亚德诺", "NXPI": "恩智浦", "ON": "安森美",
    "WDC": "西部数据", "HPQ": "惠普", "HPE": "慧与", "ANET": "Arista",
    "MRVL": "迈威尔", "TER": "泰瑞达", "ZM": "Zoom", "TWLO": "Twilio",
    "SQ": "Block", "AFRM": "Affirm", "SOFI": "SoFi", "TGT": "塔吉特",
    "LOW": "劳氏", "TJX": "TJX", "DAL": "达美航空", "UAL": "联合航空",
    "AAL": "美国航空", "LUV": "西南航空", "MAR": "万豪", "HLT": "希尔顿",
}

# Benzinga 的加密对记法：X:BTCUSD / X:ETHUSD / X:SOLUSD…
# 实测 X:BTCUSD 30 天出现 97 次、X:ETHUSD 41 次——首版正则 ^[A-Z]{1,5}$ 把它们
# 全拒了，等于把 Benzinga 的加密报道整块漏掉。这些是币安核心品类，不能漏。
_BENZINGA_CRYPTO_RE = re.compile(r"^X:([A-Z]{2,10})USD[T]?$")

# 币安现货必然在架的主流币。只列确定的，不确定的走 coin_metrics 那条路
# 实查 binance_spot——宁可少标，不能标一个用户点进去发现买不到的。
_MAJOR_CRYPTO = {
    "BTC": "比特币", "ETH": "以太坊", "BNB": "BNB", "SOL": "Solana",
    "XRP": "XRP", "ADA": "Cardano", "DOGE": "狗狗币", "AVAX": "Avalanche",
    "LINK": "Chainlink", "DOT": "Polkadot", "MATIC": "Polygon",
    "LTC": "莱特币", "BCH": "比特币现金", "UNI": "Uniswap", "ATOM": "Cosmos",
    "TRX": "波场", "TON": "TON", "NEAR": "NEAR", "APT": "Aptos",
    "ARB": "Arbitrum", "OP": "Optimism", "SUI": "Sui", "ZEC": "Zcash",
    "SHIB": "柴犬币", "PEPE": "PEPE", "USDT": "泰达币", "USDC": "USDC",
}

# 只在文本里出现、但不是可交易标的的常见大写词，防止误认成 ticker
_NOT_TICKER = {
    "CEO", "CFO", "CTO", "COO", "IPO", "ETF", "SEC", "FED", "GDP", "CPI",
    "PCE", "FOMC", "USA", "USD", "EUR", "GBP", "JPY", "CNY", "AI", "API",
    "EPS", "ATH", "ATL", "YOY", "QOQ", "EU", "UK", "US", "UN", "NYSE",
    "NASDAQ", "AMEX", "OTC", "SPAC", "REIT", "ESG", "FDA", "DOJ", "FTC",
}

_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


def _clean_symbols(raw: str) -> list[tuple]:
    """把 "DJI,IXIC,X:BTCUSD,MSFT" 拆成 [(kind, symbol)] 列表。

    kind 为 "equity" 或 "crypto"——Benzinga 用 X:BTCUSD 这种记法标加密对，
    与股票 ticker 混在同一个字段里，必须在这里就分开，否则 BTC 会被拿去
    查美股白名单（查不到，于是整块加密报道被丢掉）。
    """
    out = []
    for s in (raw or "").split(","):
        s = s.strip().upper()
        if not s:
            continue
        m = _BENZINGA_CRYPTO_RE.match(s)
        if m:
            pair = ("crypto", m.group(1))
            if pair not in out:
                out.append(pair)
            continue
        if s in _NOT_TICKER or not _TICKER_RE.match(s):
            continue
        pair = ("equity", s)
        if pair not in out:
            out.append(pair)
    return out


def from_matched_symbols(raw: str) -> list[dict]:
    """阶梯①：Benzinga/dxFeed 编辑部标注的 ticker → 交易实体。零成本。

    只保留白名单内的：一条盘前综述可能挂 12 个 ticker，其中多数是用户不认识
    的小盘股，全标出来首页会变成 ticker 刷屏（Lawrence 裁决：只标大盘蓝筹）。
    """
    entities = []
    for kind, sym in _clean_symbols(raw):
        if kind == "crypto":
            # 主流币直接认可交易（币安现货必然有）；小众的交给 coin_metrics
            # 那条路去查 binance_spot，这里不猜。
            if sym in _MAJOR_CRYPTO:
                entities.append({"symbol": sym, "name": _MAJOR_CRYPTO[sym],
                                 "market": "crypto", "venue": "binance_spot",
                                 "tradable": True, "source": "editorial_ticker"})
            continue
        if sym in BLUE_CHIPS:
            entities.append({"symbol": sym, "name": BLUE_CHIPS[sym],
                             "market": "us_stock", "venue": "US",
                             "tradable": True, "source": "editorial_ticker"})
        elif sym in INDEX_ETF:
            entities.append({"symbol": sym, "name": INDEX_ETF[sym],
                             "market": "index_etf", "venue": "US",
                             "tradable": True, "source": "editorial_ticker"})
        elif sym in INDEX_ONLY:
            # 指数本身买不了，但认出来对"这条讲的是大盘"有价值，
            # 展示时标 tradable=false，不参与"有可交易标的"的加分。
            entities.append({"symbol": sym, "name": INDEX_ONLY[sym],
                             "market": "index", "venue": "-",
                             "tradable": False, "source": "editorial_ticker"})
    return entities


# ── 阶梯②b：标题公司名匹配（零成本，无需改 prompt）──────────────────
#
# 为什么需要这一层：阶梯① 只覆盖 Benzinga/dxFeed（它们自带编辑部 ticker），
# 而首屏排在最前面的美股事件实测来自 CryptoBriefing / Google News / PANews
# ——这些源没有 ticker 字段。结果是"全库 762 条美股有标的"这个数字是真的，
# 但**用户在首页看到的恰恰是覆盖不到的那批**（实测首屏美股 0/10 有标签）。
# 聚合数字掩盖了首屏体验，这正是"人眼一看就能发现"的那类问题。
#
# 白名单的 value 本来就是中文名，反向索引一下就能用，零额外维护成本。
_NAME_TO_TICKER = {}
for _sym, _name in list(BLUE_CHIPS.items()) + list(INDEX_ETF.items()):
    # 中文名 → ticker。跳过纯英文名（那些直接靠 ticker 匹配就行，
    # 再拿英文名去扫标题容易误伤，比如 "NOW" "T" "BE" 这种词）
    if any("一" <= ch <= "鿿" for ch in _name):
        _NAME_TO_TICKER.setdefault(_name, _sym)

# 英文公司名里足够独特、不会误伤的那些（"Apple" 会撞 apple 水果，
# 但在财经标题语境里几乎不会；反倒是 "Now"/"Net"/"Be" 这种必须排除，
# 所以只列长度 ≥4 且本身就是专有名词的）。
_EN_NAME_TO_TICKER = {
    "coinbase": "COIN", "microstrategy": "MSTR", "robinhood": "HOOD",
    "nvidia": "NVDA", "tesla": "TSLA", "amazon": "AMZN", "microsoft": "MSFT",
    "google": "GOOGL", "alphabet": "GOOGL", "apple": "AAPL", "meta": "META",
    "netflix": "NFLX", "palantir": "PLTR", "datadog": "DDOG", "reddit": "RDDT",
    "roblox": "RBLX", "rivian": "RIVN", "snowflake": "SNOW", "uber": "UBER",
    "airbnb": "ABNB", "shopify": "SHOP", "spotify": "SPOT", "oracle": "ORCL",
    "salesforce": "CRM", "broadcom": "AVGO", "qualcomm": "QCOM",
    "intel": "INTC", "cloudflare": "NET", "crowdstrike": "CRWD",
    "marathon": "MARA", "galaxy digital": "GLXY", "cleanspark": "CLSK",
}


def from_title(title_zh: str = "", title_en: str = "") -> list[dict]:
    """从标题里认公司名 → 交易实体。零 LLM 成本、不改 prompt。

    只扫**标题**不扫正文：标题里出现的公司名基本就是这条新闻的主角，正文里
    出现的常常只是顺带提及（"...与亚马逊、谷歌等公司类似..."），标出来是噪音。
    """
    entities, seen = [], set()
    zh = title_zh or ""
    # 英文品牌名要在**中英文标题里都扫**：中文财经标题嵌英文品牌名是常态
    # （实测"美股收涨，Coinbase跌5.13%"——只扫 title_en 的话这条就漏了）。
    en = f"{title_zh or ''} {title_en or ''}".lower()
    for name, sym in _NAME_TO_TICKER.items():
        if name in zh and sym not in seen:
            seen.add(sym)
            entities.append({
                "symbol": sym, "name": name,
                "market": "index_etf" if sym in INDEX_ETF else "us_stock",
                "venue": "US", "tradable": True, "source": "title_match"})
    for name, sym in _EN_NAME_TO_TICKER.items():
        if name in en and sym not in seen:
            seen.add(sym)
            entities.append({
                "symbol": sym, "name": BLUE_CHIPS.get(sym, sym),
                "market": "us_stock", "venue": "US",
                "tradable": True, "source": "title_match"})
    return entities


def from_coin_metrics(coin_metrics) -> list[dict]:
    """阶梯②：加密侧。可交易 = **币安现货在架**（binance_spot）。

    对一个币安的产品来说，"能买到"最自然的定义就是"币安上有"。这个字段
    market_cap.py 早就在算了（走 data-api.binance.vision），直接复用。
    """
    if not coin_metrics:
        return []
    if isinstance(coin_metrics, str):
        try:
            coin_metrics = json.loads(coin_metrics)
        except ValueError:
            return []
    entities = []
    for c in coin_metrics or []:
        if not isinstance(c, dict) or c.get("status") != "ok":
            continue
        sym = (c.get("symbol") or "").upper()
        if not sym:
            continue
        listed = bool(c.get("binance_spot"))
        entities.append({
            "symbol": sym, "name": c.get("name") or sym, "market": "crypto",
            "venue": "binance_spot" if listed else "other_cex",
            "tradable": listed, "source": "coin_metrics",
            "market_cap_rank": c.get("market_cap_rank"),
        })
    return entities


def resolve(event: dict, matched_symbols: str = "") -> list[dict]:
    """汇总一条事件的交易实体，按"可交易优先、加密优先"排序，最多 6 个。

    排序刻意把可交易的排前面：前端只展示前 3 个，要保证用户看到的是他真能
    下单的那些，而不是被指数代码占满。
    """
    entities = from_coin_metrics(event.get("coin_metrics"))
    have = {e["symbol"] for e in entities}
    for e in from_matched_symbols(matched_symbols or event.get("matched_symbols", "")):
        if e["symbol"] not in have:
            entities.append(e)
            have.add(e["symbol"])
    # 标题匹配放最后：前两条阶梯的数据来源更硬（编辑部标注 / 实查币安在架），
    # 标题匹配是启发式的，只用来补它们够不到的那部分。
    for e in from_title(event.get("title_zh", ""), event.get("title_en", "")):
        if e["symbol"] not in have:
            entities.append(e)
            have.add(e["symbol"])

    def sort_key(e):
        return (not e["tradable"],                       # 可交易的在前
                {"crypto": 0, "us_stock": 1}.get(e["market"], 2),
                e.get("market_cap_rank") or 9999)

    return sorted(entities, key=sort_key)[:6]


def has_tradable(entities) -> bool:
    if isinstance(entities, str):
        try:
            entities = json.loads(entities)
        except ValueError:
            return False
    return any(e.get("tradable") for e in (entities or []))


def tradable_count(entities) -> int:
    if isinstance(entities, str):
        try:
            entities = json.loads(entities)
        except ValueError:
            return 0
    return sum(1 for e in (entities or []) if e.get("tradable"))
