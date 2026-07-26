"""币种市值标签 v1.0 —— 给事件里出现的每个 coin 打上市值 / 相对 BTC 倍数 / 市值档位。

需求来源：产品明确要求「所有涉及具体【币】的，都加上【市场价值】和【相对于 BTC 的
xx 倍市值】标签」。

设计原则（和 verification.py 一脉相承）：**这是查表，不是判断**。市值是客观数字，
绝不让 LLM 猜——LLM 对市值的记忆停留在训练截止日，且会把 UNI 的市值和某个同名
山寨币搞混。本模块单轮 LLM 调用 0 次，只有 CoinGecko 的几个 HTTP 请求，且带磁盘
缓存（TTL 24h，见 CACHE_TTL_SECONDS 处的说明），正常一天只真正拉 1 次。

数据源
    CoinGecko  /coins/markets            市值 / 价格 / 排名（免费无 key）
    Binance    data-api.binance.vision   现货价格，用于交叉校验 + 判断是否币安在架
    注意：api.binance.com 在生产 VM 上返回 451（美国 IP 地域封锁），只能用
    data-api.binance.vision。

── ticker 消歧策略（本模块最容易做错、也最关键的地方）────────────────────────
CoinGecko 全量有 1.7 万个币，同一个 symbol 撞车是常态（DAI 有 2 个、JPYC 有 3 个、
MEME 有 2 个）。瞎猜一个会让「Uniswap 市值 60 亿」变成「某个同名貔貅盘市值 3 万」，
这种错误比不打标签有害得多。四道闸：

  D-1 只信任市值前 N 名（默认 1500）。宇宙之外的一律 unknown，不做全量 /coins/list
      模糊匹配——排名 1500 开外的币，市值本身就已经小到没有产品意义。
  D-2 同 symbol 多候选时要求**市值碾压**：第一名市值 ≥ 第二名的 5 倍才敢认，
      否则判 ambiguous 并把候选列表原样带出，不猜。
  D-3 已知别名/迁移表（MATIC→POL 这类代币迁移）在匹配前生效。
  D-4 Binance 现货价格交叉校验：CoinGecko 解析出的价格与币安 SYMBOLUSDT 现货价
      偏离超过 50% → 说明八成认错了币，降级为 ambiguous。
  D-5 主流币 id 锁定（_PINNED_IDS）。D-2 挡不住**只有一个候选、但那个候选是李鬼**
      的情况：实测 WETH 在宇宙里唯一的候选是 "Robinhood Wrapped ETH"（rank 507，
      市值 4090 万），正牌 Wrapped Ether 根本不在榜内 —— 不加这道闸就会把
      "Aave 的 WETH 激励" 标成一个 4090 万美元的微型币。对主流 ticker 强制要求
      CoinGecko id 等于钉死的规范 id，对不上就判 unknown。

匹配不上的一律标 unknown / ambiguous / equity，**不给市值数字**。宁可少一个标签，
不可给一个错的。
"""
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# 抓取配置
# ══════════════════════════════════════════════════════════════════════

COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
BINANCE_PRICE_URL = "https://data-api.binance.vision/api/v3/ticker/price"

PER_PAGE = 250
# 6 页 = 市值前 1500 名。实测该深度覆盖库里 80 个 ticker 中的全部真币，剩下的
# 是代币化美股 ticker 和 LLM 抽错的字符串。再往下翻页边际收益接近 0，却会显著
# 提高触发 429 的概率。
UNIVERSE_PAGES = 6

# CoinGecko 免费层实测：4 页（间隔 2.5s）正常，累计到第 10 个请求时 429。
# 6s 间隔 ≈ 10 req/min，留足余量；配合 429 退避重试。
REQUEST_INTERVAL_SECONDS = 6.0
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3

# 市值一天内的变化对「档位」和「相对 BTC 倍数」这两个标签没有实质影响：档位边界
# 是 1e11/1e10/1e9/1e8 的 10 倍量级台阶，BTC 一天波动 2%，隔夜数据不会让任何一个
# 币跨档；btc_ratio 是两个市值的比值，同涨同跌还会互相抵消一部分。
#
# 2026-07-26 把 TTL 从 6h 调到 24h。原值 6h 是按「cron 每 4 小时一轮」定的，那时
# 确实多数轮次直接命中缓存；但主 pipeline 早已改成 **12 小时一轮**（UTC 0/12），
# 6h TTL 意味着每一轮开跑时缓存必然已经过期，等于每轮都要重拉 6 页 CoinGecko
# ——按 REQUEST_INTERVAL_SECONDS=6s 的节流算白白多花 30~40 秒，还平白多冒一次
# 429 的风险（免费层实测第 10 个请求就会被限）。
# 调到 24h 之后：UTC 0 点那轮真拉一次，UTC 12 点那轮缓存 age=12h 命中，一天只
# 拉 1 次，请求量减半。代价是标签最多滞后 24 小时，对上面两个标签可以忽略；
# 需要即时刷新时调用方可以传 load_snapshot(force_refresh=True) 绕过。
CACHE_TTL_SECONDS = 24 * 3600
CACHE_PATH = Path(__file__).parent.parent / "config" / "cache" / "market_cap.json"

_HEADERS = {"User-Agent": "binance-b9-news/1.0", "Accept": "application/json"}


# ══════════════════════════════════════════════════════════════════════
# 市值档位
# ══════════════════════════════════════════════════════════════════════
#
# 阈值取十进制量级边界（1e11 / 1e10 / 1e9 / 1e8），依据有三条：
#   1. 加密市值分布近似对数均匀，按量级切分才能得到规模可用的桶；按线性切会
#      出现「一个桶装 90% 的币」。
#   2. 这几条线和行业口语一致：「百亿美金项目」「十亿美金项目」是现成的说法，
#      PM 和运营不需要额外记忆换算。
#   3. 1e8（1 亿美金）以下的币深度极薄，市值本身容易被操纵，单独归一档提示风险。
#
# 2026-07-26 实测该表在 CoinGecko 前 1500 名上的分布（BTC 市值 $1.29T）：
#   超大盘 ≥$100B     3 个   (btc_ratio ≥ 0.0775)
#   大盘   ≥$10B      9 个   (btc_ratio ≥ 0.00775)
#   中盘   ≥$1B      53 个   (btc_ratio ≥ 0.00078)
#   小盘   ≥$100M   210 个   (btc_ratio ≥ 0.000078)
#   微型   <$100M  1225 个
CAP_TIERS = [
    (1e11, "mega",  "超大盘"),
    (1e10, "large", "大盘"),
    (1e9,  "mid",   "中盘"),
    (1e8,  "small", "小盘"),
    (0.0,  "micro", "微型"),
]


def classify_cap_tier(market_cap: float | None) -> tuple[str, str]:
    """市值 → (档位 code, 中文档位)。无市值返回 ("unknown", "未知")。"""
    if not market_cap or market_cap <= 0:
        return "unknown", "未知"
    for floor, code, label in CAP_TIERS:
        if market_cap >= floor:
            return code, label
    return "micro", "微型"


# ══════════════════════════════════════════════════════════════════════
# 消歧用的静态表
# ══════════════════════════════════════════════════════════════════════

# D-3 代币迁移 / 别名。左边是新闻里仍在用的旧 ticker，右边是当前生效的 symbol。
_SYMBOL_ALIASES = {
    "MATIC": "POL",     # Polygon 2023 年代币迁移，新闻里旧称仍高频出现
    "XBT":   "BTC",     # 部分传统金融口径用 XBT
    "BTCB":  "BTC",
    "WBTC":  "WBTC",    # 保留自身：wBTC 有独立市值，不能顶替 BTC
}

# 非加密资产 ticker：bStocks 代币化美股的**标的股票代码**、以及新闻里出现的
# 普通股票代码。它们在加密宇宙里查不到（或会撞上同名山寨币），必须显式拦下来，
# 判成 equity 而不是 unknown —— 「查不到」和「它压根不是币」是两回事，前者
# 提示我们数据源不够，后者是正确结论。
#
# 注意区分：SKHYB / TSLAB 这类**带 B 后缀的代币化股票代币**在 CoinGecko 上有
# 独立条目（市值 = 代币化流通市值，不是公司市值），走正常匹配并标 tokenized_equity。
_EQUITY_TICKERS = {
    "COIN", "GS", "AAL", "TSLA", "TSLL", "TSLLT", "AAPL", "MSFT", "NVDA", "AMZN",
    "GOOG", "GOOGL", "META", "NFLX", "MSTR", "HOOD", "CRCL", "SQ", "PYPL", "BLK",
    "JPM", "BAC", "C", "WFC", "SPY", "QQQ", "POPMART", "CXMT", "SKHY",
}

# 稳定币：市值 = 流通量，btc_ratio 对它们没有「涨跌」含义，只表示体量。
# 前端不应把「USDC 市值 = BTC 的 4%」当成利多信号，故单独标 asset_class。
_STABLECOIN_SYMBOLS = {
    "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDP", "USDD", "PYUSD", "RLUSD",
    "USDE", "SUSDE", "GUSD", "LUSD", "FRAX", "USD1", "EURC", "EURS",
}

# 代币化商品（黄金/白银等）。和稳定币一样是锚定资产，但锚的不是法币，
# 对应 B9 的 tCommodities 板块。实测 XAUT 被第一版当成稳定币，不对。
_COMMODITY_SYMBOLS = {"XAUT", "PAXG", "XAGT", "KAU", "KAG"}

# D-5 主流币 id 锁定：symbol → CoinGecko 规范 id。
#
# 只对「一旦认错影响极大」的主流 ticker 设锁。命中规则：
#   * 候选里存在这个 id  → 强制选它（哪怕它市值不是最大的那个）
#   * 候选里不存在       → 判 unknown，**绝不退而求其次选个同名的**
# 第二条是本表存在的全部理由。实测 WETH 在宇宙里只有 "Robinhood Wrapped ETH"
# 一个候选，D-2 的多候选碾压比根本不触发，只有 id 锁能挡住。
_PINNED_IDS = {
    "BTC": "bitcoin",         "ETH": "ethereum",        "USDT": "tether",
    "USDC": "usd-coin",       "BNB": "binancecoin",     "XRP": "ripple",
    "SOL": "solana",          "ADA": "cardano",         "DOGE": "dogecoin",
    "TRX": "tron",            "LINK": "chainlink",      "AVAX": "avalanche-2",
    "DOT": "polkadot",        "POL": "polygon-ecosystem-token",
    "LTC": "litecoin",        "BCH": "bitcoin-cash",    "UNI": "uniswap",
    "AAVE": "aave",           "ATOM": "cosmos",         "NEAR": "near",
    "APT": "aptos",           "SUI": "sui",             "TON": "the-open-network",
    "SHIB": "shiba-inu",      "PEPE": "pepe",           "WBTC": "wrapped-bitcoin",
    "WETH": "weth",           "STETH": "staked-ether",  "DAI": "dai",
    "ARB": "arbitrum",        "OP": "optimism",         "FIL": "filecoin",
    "ETC": "ethereum-classic", "XLM": "stellar",        "HBAR": "hedera-hashgraph",
    "XMR": "monero",          "ZEC": "zcash",           "ICP": "internet-computer",
    "ALGO": "algorand",       "VET": "vechain",         "CRO": "crypto-com-chain",
}

# 币安现货的计价资产：它自己不会有 XXXUSDT 交易对，但显然在币安可交易。
# 不特判的话 USDT 会被标成 binance_spot=False，看着像个 bug。
_BINANCE_QUOTE_ASSETS = {"USDT"}

# 代币化股票 / RWA：CoinGecko 名称里带这些字样时，market_cap 是**代币化流通市值**，
# 不是标的公司市值。必须分开标，否则「SK 海力士市值 1220 万美元」会闹笑话。
_TOKENIZED_EQUITY_RE = re.compile(
    r"tokenized\s+stock|bstocks|xstock|tokenized\s+share|tokenized\s+equity",
    re.IGNORECASE,
)

# D-2 碾压比：第一候选市值 ≥ 第二候选的这么多倍才敢认。
# 5 倍的依据：同 symbol 撞车里真正有产品意义的那个通常和山寨币差 2~4 个数量级
# （实测 DAI 63 倍、MEME 也在数量级差距上），5 倍是个宽松但足以挡住
# 「两个都半死不活分不清谁是谁」的下限。
AMBIGUITY_DOMINANCE_RATIO = 5.0

# D-4 币安现货交叉校验：价格偏离超过这个倍数 → 认错币的概率远大于行情差异。
# 币安现货和 CoinGecko 加权均价在正常情况下偏差 <2%，50% 是极宽松的红线。
PRICE_MISMATCH_RATIO = 1.5


def normalize_symbol(raw: str) -> str:
    """ticker 归一化：去空白、去 $ 前缀、大写、套用别名表。"""
    symbol = (raw or "").strip().upper().lstrip("$").strip()
    return _SYMBOL_ALIASES.get(symbol, symbol)


# ══════════════════════════════════════════════════════════════════════
# 行情宇宙（抓取 + 缓存）
# ══════════════════════════════════════════════════════════════════════

def _get(url: str, params: dict | None = None) -> list | dict | None:
    """带 429 退避的 GET。失败返回 None，由调用方决定降级策略。"""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, headers=_HEADERS,
                                timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                wait = REQUEST_INTERVAL_SECONDS * (2 ** attempt)
                logger.warning(f"CoinGecko 429, backing off {wait:.0f}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"GET {url} failed (attempt {attempt + 1}): {e}")
            time.sleep(2 ** attempt)
    return None


def fetch_coingecko_universe(pages: int = UNIVERSE_PAGES) -> list[dict]:
    """拉市值前 pages*250 名。返回精简后的行（只留用得上的字段）。

    任何一页失败都不致命：返回已经拿到的部分，宇宙变小意味着更多 ticker 被判
    unknown —— 那是安全的降级方向（少打标签，不打错标签）。
    """
    rows: list[dict] = []
    for page in range(1, pages + 1):
        data = _get(COINGECKO_MARKETS_URL, {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": PER_PAGE,
            "page": page,
        })
        if not isinstance(data, list) or not data:
            logger.warning(f"CoinGecko page {page} empty/failed, universe truncated")
            break
        for row in data:
            rows.append({
                "id": row.get("id"),
                "symbol": (row.get("symbol") or "").upper(),
                "name": row.get("name") or "",
                "market_cap": row.get("market_cap"),
                "market_cap_rank": row.get("market_cap_rank"),
                "price": row.get("current_price"),
            })
        if page < pages:
            time.sleep(REQUEST_INTERVAL_SECONDS)

    logger.info(f"CoinGecko universe: {len(rows)} coins")
    return rows


def fetch_binance_spot_prices() -> dict[str, float]:
    """币安现货全量价格 → {SYMBOL: usdt_price}，只取 USDT 交易对。

    两个用途：D-4 价格交叉校验；判断该币是否在币安现货在架（binance_spot 标签，
    对币安自己的新闻产品是有产品意义的一维）。
    """
    data = _get(BINANCE_PRICE_URL)
    if not isinstance(data, list):
        logger.warning("Binance spot prices unavailable, cross-check disabled")
        return {}
    prices: dict[str, float] = {}
    for row in data:
        symbol = (row.get("symbol") or "").upper()
        if not symbol.endswith("USDT"):
            continue
        base = symbol[:-4]
        try:
            prices[base] = float(row["price"])
        except (KeyError, TypeError, ValueError):
            continue
    logger.info(f"Binance spot: {len(prices)} USDT pairs")
    return prices


def _read_cache() -> dict | None:
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return None


def _write_cache(payload: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"market cap cache write failed: {e}")


_snapshot_memo: dict | None = None


def load_snapshot(force_refresh: bool = False) -> dict:
    """取行情快照 {coins, binance, fetched_at}。进程内 memo + 磁盘缓存双层。

    降级顺序：内存 → 未过期磁盘缓存 → 拉网 → **过期的磁盘缓存**。
    最后一步是有意的：过期一两天的市值数字也远好过没有标签，行情源挂了不该拖垮
    整条 pipeline。
    """
    global _snapshot_memo
    now = time.time()

    if not force_refresh and _snapshot_memo:
        if now - _snapshot_memo.get("fetched_at", 0) < CACHE_TTL_SECONDS:
            return _snapshot_memo

    cached = _read_cache()
    if not force_refresh and cached and now - cached.get("fetched_at", 0) < CACHE_TTL_SECONDS:
        _snapshot_memo = cached
        logger.info("market cap: using disk cache "
                    f"(age {int(now - cached['fetched_at'])}s, {len(cached.get('coins', []))} coins)")
        return cached

    coins = fetch_coingecko_universe()
    if not coins:
        if cached:
            logger.warning("market cap: fetch failed, falling back to STALE cache "
                           f"(age {int(now - cached.get('fetched_at', 0))}s)")
            _snapshot_memo = cached
            return cached
        logger.error("market cap: fetch failed and no cache available")
        return {"coins": [], "binance": {}, "fetched_at": now}

    snapshot = {
        "coins": coins,
        "binance": fetch_binance_spot_prices(),
        "fetched_at": now,
        "fetched_at_iso": datetime.now(timezone.utc).isoformat(),
    }
    _write_cache(snapshot)
    _snapshot_memo = snapshot
    return snapshot


# ══════════════════════════════════════════════════════════════════════
# 消歧 + 打标
# ══════════════════════════════════════════════════════════════════════

STATUS_OK        = "ok"          # 成功匹配，市值可用
STATUS_AMBIGUOUS = "ambiguous"   # 同 symbol 多候选且无碾压者 —— 不猜
STATUS_EQUITY    = "equity"      # 股票代码，不是币
STATUS_UNKNOWN   = "unknown"     # 市值前 N 名之外 / 查无此 symbol

CLASS_COIN = "coin"
CLASS_STABLE = "stablecoin"
CLASS_COMMODITY = "tokenized_commodity"
CLASS_TOKENIZED_EQUITY = "tokenized_equity"
CLASS_EQUITY = "equity"
CLASS_UNKNOWN = "unknown"


class MarketCapIndex:
    """行情快照的查询索引。一次构建，多次查询。"""

    def __init__(self, snapshot: dict | None = None):
        snapshot = snapshot if snapshot is not None else load_snapshot()
        self.fetched_at = snapshot.get("fetched_at", 0)
        self.binance = snapshot.get("binance") or {}

        self.by_symbol: dict[str, list[dict]] = {}
        for row in snapshot.get("coins") or []:
            if row.get("market_cap"):
                self.by_symbol.setdefault(row["symbol"], []).append(row)
        for rows in self.by_symbol.values():
            rows.sort(key=lambda r: -(r.get("market_cap") or 0))

        self.universe_size = sum(len(v) for v in self.by_symbol.values())
        btc = self.by_symbol.get("BTC")
        self.btc_market_cap = (btc[0]["market_cap"] if btc else 0.0) or 0.0
        if not self.btc_market_cap:
            logger.error("market cap: BTC not found in universe, btc_ratio unavailable")

    # ── 单个 ticker ────────────────────────────────────────────────
    def resolve(self, raw_symbol: str) -> dict:
        """ticker → 市值标签 dict。永远返回 dict，不抛异常。"""
        symbol = normalize_symbol(raw_symbol)
        base = {
            "symbol": symbol,
            "symbol_raw": (raw_symbol or "").strip(),
            "status": STATUS_UNKNOWN,
            "asset_class": CLASS_UNKNOWN,
            "flags": [],
        }
        if not symbol:
            return base

        if symbol in _EQUITY_TICKERS:
            base.update({"status": STATUS_EQUITY, "asset_class": CLASS_EQUITY,
                         "note": "股票代码，非加密资产，无加密市值"})
            return base

        candidates = self.by_symbol.get(symbol) or []
        if not candidates:
            base["note"] = f"不在 CoinGecko 市值前 {self.universe_size} 名内"
            return base

        # D-5 主流币 id 锁定
        pinned_id = _PINNED_IDS.get(symbol)
        if pinned_id:
            exact = next((c for c in candidates if c["id"] == pinned_id), None)
            if exact is None:
                base["flags"].append("PINNED_ID_MISSING")
                base["note"] = (f"主流 ticker，但规范币 {pinned_id} 不在行情宇宙内；"
                                f"拒绝匹配同名的 "
                                f"{'/'.join(c['id'] for c in candidates[:3])}")
                return base
            return self._build(base, exact, candidates)

        best = candidates[0]
        if len(candidates) > 1:
            # D-2 碾压比
            second_cap = candidates[1].get("market_cap") or 0.0
            best_cap = best.get("market_cap") or 0.0
            if second_cap > 0 and best_cap < AMBIGUITY_DOMINANCE_RATIO * second_cap:
                base.update({
                    "status": STATUS_AMBIGUOUS,
                    "candidates": [
                        {"id": c["id"], "name": c["name"],
                         "market_cap_rank": c.get("market_cap_rank"),
                         "market_cap_usd": c.get("market_cap")}
                        for c in candidates[:4]
                    ],
                    "note": f"{len(candidates)} 个同名币且市值未拉开差距，不做猜测",
                })
                return base
            base["flags"].append("AMBIGUOUS_RESOLVED_BY_DOMINANCE")

        return self._build(base, best, candidates)

    def _build(self, base: dict, row: dict, candidates: list[dict]) -> dict:
        market_cap = float(row.get("market_cap") or 0.0)
        price = row.get("price")
        tier_code, tier_zh = classify_cap_tier(market_cap)
        btc_ratio = (market_cap / self.btc_market_cap) if self.btc_market_cap else None

        binance_price = self.binance.get(base["symbol"])
        flags = base["flags"]
        if binance_price and price:
            ratio = max(binance_price / price, price / binance_price)
            if ratio > PRICE_MISMATCH_RATIO:
                # D-4：价格对不上，多半是认错了币。降级，不给市值。
                flags.append("PRICE_MISMATCH")
                base.update({
                    "status": STATUS_AMBIGUOUS,
                    "coin_id": row["id"],
                    "name": row["name"],
                    "price_usd": price,
                    "binance_price_usd": binance_price,
                    "note": (f"CoinGecko 价 {price} 与币安现货 {binance_price} "
                             f"相差 {ratio:.1f} 倍，疑似匹配到同名的另一个币"),
                })
                return base

        base.update({
            "status": STATUS_OK,
            "coin_id": row["id"],
            "name": row["name"],
            "asset_class": self._asset_class(base["symbol"], row),
            "market_cap_usd": round(market_cap, 2),
            "market_cap_rank": row.get("market_cap_rank"),
            "price_usd": price,
            "btc_ratio": round(btc_ratio, 8) if btc_ratio is not None else None,
            "btc_ratio_label": format_btc_ratio(btc_ratio),
            "cap_tier": tier_code,
            "cap_tier_zh": tier_zh,
            "market_cap_label": format_market_cap(market_cap),
            "binance_spot": (base["symbol"] in self.binance
                             or base["symbol"] in _BINANCE_QUOTE_ASSETS),
            "n_candidates": len(candidates),
        })
        if binance_price:
            base["binance_price_usd"] = binance_price
        return base

    @staticmethod
    def _asset_class(symbol: str, row: dict) -> str:
        if _TOKENIZED_EQUITY_RE.search(row.get("name") or "") or \
           _TOKENIZED_EQUITY_RE.search(row.get("id") or ""):
            return CLASS_TOKENIZED_EQUITY
        if symbol in _COMMODITY_SYMBOLS:
            return CLASS_COMMODITY
        if symbol in _STABLECOIN_SYMBOLS:
            return CLASS_STABLE
        return CLASS_COIN


# ── 展示格式化 ────────────────────────────────────────────────────────

def format_market_cap(market_cap: float | None) -> str:
    """市值 → 人类可读（$1.29T / $12.3B / $456M / $7.8M）。"""
    if not market_cap or market_cap <= 0:
        return "—"
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if market_cap >= div:
            return f"${market_cap / div:.2f}{unit}"
    return f"${market_cap:.0f}"


def format_btc_ratio(ratio: float | None) -> str:
    """相对 BTC 市值倍数 → 人类可读。

    产品原话是「相对于 BTC 的 xx 倍市值」。绝大多数币的倍数远小于 1，直接写
    "0.0100 倍" 可读性差，所以 <1 时同时给出百分比表述。
    """
    if ratio is None:
        return "—"
    if ratio >= 1:
        return f"BTC 市值的 {ratio:.2f} 倍"
    if ratio >= 0.0001:
        return f"BTC 市值的 {ratio * 100:.2f}%（{ratio:.4f} 倍）"
    return f"BTC 市值的 {ratio * 100:.4f}%（{ratio:.6f} 倍）"


# ══════════════════════════════════════════════════════════════════════
# 事件级入口
# ══════════════════════════════════════════════════════════════════════

def annotate_events(events: list[dict], index: "MarketCapIndex | None" = None) -> dict:
    """给一批事件就地写入市值标签字段：

        coin_metrics             每个 coin 的完整标签列表（JSON）
        primary_coin             市值最大的那个已匹配币（事件的「主角币」）
        primary_coin_market_cap  主角币市值 USD
        primary_coin_btc_ratio   主角币相对 BTC 的市值倍数
        coin_cap_tier            主角币的市值档位 code

    后四个是从 coin_metrics 里抽出来的标量，纯粹为了让 SQL 能直接排序/过滤 ——
    JSON 列没法建索引。

    成本：0 次 LLM 调用；行情快照命中缓存时 0 次 HTTP 请求。
    """
    if not events:
        return {"events": 0}

    index = index or MarketCapIndex()
    stats = {"events": 0, "coins": 0, STATUS_OK: 0, STATUS_AMBIGUOUS: 0,
             STATUS_EQUITY: 0, STATUS_UNKNOWN: 0}

    for event in events:
        coins = [c for c in (event.get("coins") or []) if isinstance(c, str) and c.strip()]
        if not coins:
            event["coin_metrics"] = []
            continue

        # 同一事件里 LLM 偶尔会重复吐同一个 ticker，去重并保序
        seen, ordered = set(), []
        for coin in coins:
            key = normalize_symbol(coin)
            if key and key not in seen:
                seen.add(key)
                ordered.append(coin)

        metrics = [index.resolve(coin) for coin in ordered]
        event["coin_metrics"] = metrics
        stats["events"] += 1
        stats["coins"] += len(metrics)
        for m in metrics:
            stats[m["status"]] = stats.get(m["status"], 0) + 1

        matched = [m for m in metrics if m["status"] == STATUS_OK and m.get("market_cap_usd")]
        if matched:
            primary = max(matched, key=lambda m: m["market_cap_usd"])
            event["primary_coin"] = primary["symbol"]
            event["primary_coin_market_cap"] = primary["market_cap_usd"]
            event["primary_coin_btc_ratio"] = primary["btc_ratio"]
            event["coin_cap_tier"] = primary["cap_tier"]

    matched_total = stats[STATUS_OK]
    total = stats["coins"] or 1
    logger.info(
        f"Market cap: {stats['events']} events / {stats['coins']} coin mentions → "
        f"ok {stats[STATUS_OK]} ({matched_total / total * 100:.1f}%), "
        f"ambiguous {stats[STATUS_AMBIGUOUS]}, equity {stats[STATUS_EQUITY]}, "
        f"unknown {stats[STATUS_UNKNOWN]} (0 LLM calls)"
    )
    return stats


_UPDATE_SQL = """
UPDATE news_events
   SET coin_metrics            = %s,
       primary_coin            = %s,
       primary_coin_market_cap = %s,
       primary_coin_btc_ratio  = %s,
       coin_cap_tier           = %s
 WHERE id = %s
"""


def persist_coin_metrics(events: list[dict], conn) -> int:
    """把市值标签写回 news_events。必须在 storage.write_events 之后调用（行要先存在）。

    单独走 UPDATE 而不是改 storage._INSERT_EVENT_SQL，理由和 verification.py 一样：
    storage.py 是多方共用的热点文件，新增字段各自用 UPDATE 收口，互不打架。
    """
    if not events:
        return 0
    cursor = conn.cursor()
    written = 0
    for event in events:
        if "coin_metrics" not in event:
            continue
        try:
            cursor.execute(_UPDATE_SQL, (
                json.dumps(event.get("coin_metrics") or [], ensure_ascii=False),
                (event.get("primary_coin") or None),
                event.get("primary_coin_market_cap"),
                event.get("primary_coin_btc_ratio"),
                (event.get("coin_cap_tier") or None),
                event["id"],
            ))
            written += cursor.rowcount
        except Exception as e:
            logger.warning(f"coin metrics write failed [{event.get('id')}]: {e}")
    conn.commit()
    cursor.close()
    logger.info(f"MySQL: coin metrics written for {written}/{len(events)} events")
    return written


# ══════════════════════════════════════════════════════════════════════
# 全库跑批 / 抽样核对
#   python -m crawler.market_cap [--persist] [--sample 15] [--refresh]
# ══════════════════════════════════════════════════════════════════════

def _load_events(conn, limit: int | None = None) -> list[dict]:
    cursor = conn.cursor()
    sql = ("SELECT id, title_zh, title_en, coins FROM news_events "
           "WHERE coins IS NOT NULL AND JSON_LENGTH(coins) > 0 "
           "ORDER BY time_get_data DESC")
    if limit:
        sql += f" LIMIT {int(limit)}"
    cursor.execute(sql)
    rows = cursor.fetchall()
    cursor.close()
    events = []
    for event_id, title_zh, title_en, coins in rows:
        try:
            parsed = json.loads(coins) if isinstance(coins, str) else (coins or [])
        except (json.JSONDecodeError, TypeError):
            parsed = []
        events.append({"id": event_id, "title_zh": title_zh or "",
                       "title_en": title_en or "", "coins": parsed})
    return events


def _main() -> None:
    import argparse
    import collections
    import sys

    from . import storage

    parser = argparse.ArgumentParser(description="币种市值标签跑批 / 抽样核对")
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--sample", type=int, default=15)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--refresh", action="store_true", help="强制刷新行情缓存")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    index = MarketCapIndex(load_snapshot(force_refresh=args.refresh))
    print(f"\n行情宇宙 {index.universe_size} 个币，BTC 市值 "
          f"{format_market_cap(index.btc_market_cap)}，币安 USDT 交易对 {len(index.binance)}\n")

    conn = storage.get_mysql_conn()
    try:
        events = _load_events(conn, args.limit)
        print(f"载入 {len(events)} 条带 coins 的事件")
        stats = annotate_events(events, index)

        total = stats["coins"] or 1
        print(f"\n{'=' * 78}\n匹配结果（{stats['coins']} 个 coin 提及，去重后按事件计）\n{'=' * 78}")
        for status in (STATUS_OK, STATUS_AMBIGUOUS, STATUS_EQUITY, STATUS_UNKNOWN):
            n = stats.get(status, 0)
            print(f"  {status:<12} {n:>5}  {n / total * 100:>5.1f}%")

        # 未匹配明细：判断是不是真冷门币
        unmatched = collections.Counter()
        for e in events:
            for m in e.get("coin_metrics") or []:
                if m["status"] != STATUS_OK:
                    unmatched[(m["symbol"], m["status"], m.get("note", ""))] += 1
        print(f"\n未匹配 ticker 明细（{len(unmatched)} 个）：")
        for (sym, status, note), n in unmatched.most_common():
            print(f"  {sym:<12} {status:<10} ×{n}  {note}")

        tier_counter = collections.Counter()
        for e in events:
            for m in e.get("coin_metrics") or []:
                if m["status"] == STATUS_OK:
                    tier_counter[(m["cap_tier"], m["cap_tier_zh"])] += 1
        print("\n市值档位分布：")
        for (code, zh), n in sorted(tier_counter.items(), key=lambda kv: -kv[1]):
            print(f"  {zh:<6} ({code:<5}) {n:>5}")

        print(f"\n{'=' * 78}\n抽样 {args.sample} 条人工核对 btc_ratio\n{'=' * 78}")
        shown = 0
        for e in events:
            metrics = [m for m in (e.get("coin_metrics") or []) if m["status"] == STATUS_OK]
            if not metrics:
                continue
            print(f"\n[{e['id'][:12]}] {(e['title_zh'] or e['title_en'])[:60]}")
            for m in metrics:
                print(f"    {m['symbol']:<8} {m['name'][:22]:<24} "
                      f"mcap={m['market_cap_label']:<9} rank={str(m['market_cap_rank']):<5} "
                      f"btc_ratio={m['btc_ratio']}")
                print(f"             {m['btc_ratio_label']}  档位={m['cap_tier_zh']}"
                      f"  类别={m['asset_class']}  币安现货={m['binance_spot']}"
                      + (f"  flags={m['flags']}" if m["flags"] else ""))
            shown += 1
            if shown >= args.sample:
                break

        if args.persist:
            persist_coin_metrics(events, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    _main()
