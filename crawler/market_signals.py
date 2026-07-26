"""
行情异动事件生成模块 v2.0

── 为什么需要这个模块 ────────────────────────────────────────────────
事件库里"行情异动"类只占 3.9%、"宏观/美股"只占 4.7%，但对照 6 家主流平台我们的
新闻覆盖率已经有 91.9%——说明欠召的根因不是信源不够，而是**信号类型缺失**。

没有任何媒体会把"BTC 24h 跌 5%""SOL 资金费率转负""某币成交额放大 8 倍"写成一篇
稿子推给我们：这类信号是连续量的变化，不是"事件"，所以不存在于任何 RSS 里。它
只能主动从行情 API 拉数、自己判定、自己生成。本模块就干这一件事。

── 2026-07-25 在生产 VM 上实测的信源可用性结论（第一优先级结论，供其他 agent 参考）──
    ✅ data-api.binance.vision   200，现货 /ticker/24hr /klines 全可用，数据与主域名一致
    ❌ api.binance.com           HTTP 451（地域封锁），body 是 dict 不是 list：
                                 {"code":0,"msg":"Service unavailable from a restricted
                                 location according to 'b. Eligibility'..."}
    ❌ fapi.binance.com          同上 451，合约数据完全拿不到
    ✅ OKX  /market/tickers                  200（现货+合约）
    ✅ OKX  /public/funding-rate?instId=..    200（需逐个 instId 查，无批量接口）
    ✅ OKX  /public/open-interest?instType=SWAP  200（一次拉全市场合约持仓量，批量）
    ✅ OKX  /public/liquidation-orders            200（需 instFamily 参数，无 instType 单独批量）
    ❌ Bybit（spot/linear/funding 全部）      HTTP 403，CloudFront body:
                                 "The Amazon CloudFront distribution is configured to
                                 block access from your country"
    ✅ Kraken /0/public/Ticker    200（单币对查询，无稳定币/主流币全市场批量，作为
                                 补充验证用，未接入主流程）
    ✅ Coinbase /v2/exchange-rates 200（只有汇率没有涨跌幅/成交额，价值有限，未接入）
    ❌ CoinCap /v2/assets         DNS 解析失败（该域名已不可达，非地域封锁问题）
    ✅ CoinGecko /coins/markets   200（已知可用，市值排名数据，本模块评估后未使用，
                                 见下方"分层"小节的理由）
    ✅ DefiLlama /v2/chains       200（已知可用，TVL 数据，与行情异动信号无关未使用）
    （另外顺手测了 Gate.io / MEXC / KuCoin / Bitget / Hyperliquid，均 200 可用，
    留作未来备用 fallback，本版本未接入以控制复杂度）

    结论：现货用 data-api.binance.vision；合约（资金费率/持仓量/爆仓）用 OKX 为主，
    Hyperliquid 为兜底。Bybit 不可用，不再尝试。

── 成本 ──────────────────────────────────────────────────────────────
边际成本 ≈ 0。全部走免费无鉴权公开接口，阈值判定/数值格式化/标题生成一律用普通
代码，**不调用任何 LLM**。每轮约 90~140 次 HTTP 请求（1 次现货全量 + ~100 次日线
+ ~45 次资金费率 + 1 次持仓量批量 + 27 次爆仓），实测耗时 20~35 秒。下游 pipeline
对生成出来的 item 做结构化时才会用到 LLM，那部分成本与普通新闻等同，不属于本模块。

── 状态存储 ──────────────────────────────────────────────────────────
跨轮抑制状态存 MySQL 表 market_signal_state（见 config/migrations/002_market_signal_
state.sql），通过 crawler.storage.get_mysql_conn() 读写。MySQL 不可用时降级为纯内存
状态（当次运行内不重复，但不做跨轮冷却）——宁可偶尔多播，也不让状态问题整个模块挂掉。

── 输出 ──────────────────────────────────────────────────────────────
run_market_signals() 返回与 crawler/main.py 其他 fetch_* 函数完全一致的 item：
    {"source","title","url","summary","published_at","lang","authority","type"}
type 固定为 "market_signal"，可直接并入 run_rss_and_scraper_crawler() 的结果。
"""
from __future__ import annotations

import logging
import math
import time
import concurrent.futures as cf
from datetime import datetime, timedelta, timezone

import requests

from crawler import storage

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# 数据源
# ══════════════════════════════════════════════════════════════════════

# 现货主机按顺序尝试。data-api.binance.vision 放第一位——生产 VM 访问
# api.binance.com 100% 返回 451，把它排第一只会让每一轮都白白浪费一次超时/失败
# 请求。保留 api.binance.com 作为兜底：万一将来换了出口 IP 到非受限地区，不用
# 改代码就能自动生效。
SPOT_HOSTS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
]

# 合约（资金费率/持仓量/爆仓）数据源。
#   OKX：实测三个接口全部可用（tickers/funding-rate/open-interest/liquidation-
#        orders），且是中心化交易所的真实合约数据，比链上 DEX 更贴近"币安式"用户
#        的心智模型，优先使用。
#   Hyperliquid：链上永续，免费无鉴权无地区限制，OKX 整体失败时兜底，覆盖
#        funding/openInterest/markPx。
#   Bybit：实测 403（CloudFront 按国家封锁），不再尝试。
OKX_HOST = "https://www.okx.com"
HYPERLIQUID_INFO = "https://api.hyperliquid.xyz/info"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}
HTTP_TIMEOUT = 20


# ══════════════════════════════════════════════════════════════════════
# 阈值常量 —— 每个都写明为什么取这个值
# ══════════════════════════════════════════════════════════════════════

# ── 标的过滤 ──────────────────────────────────────────────────────────
QUOTE_ASSET = "USDT"

# 稳定币之间的兑换对（USDCUSDT 之类）永远在 ±0.1% 内波动，一旦触发反而是脱锚
# 大事——但那属于另一类信号，本模块不处理，先排除避免噪音。
STABLE_BASES = {
    "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "USD1", "XUSD", "EURI",
    "AEUR", "EUR", "TRY", "BRL", "ARS", "JPY", "GBP", "AUD", "PLN", "RON",
    "ZAR", "CZK", "MXN", "COP", "UAH", "NGN", "BIDR", "IDRT", "RUB", "VAI",
    "RLUSD",  # Ripple 稳定币，同理排除
}

# 杠杆代币（BTCUPUSDT / ETHDOWNUSDT 等）是 3 倍杠杆产品，涨跌幅天然是标的的 3
# 倍，纳入等于把同一条行情放大成三条新闻。
LEVERAGED_SUFFIXES = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")

# 24h 成交额低于这个数的一律不看。这是**防止长尾垃圾币刷屏的第一道闸**：
# 2026-07-25 实测全市场 620 个 USDT 现货对里只有 42 个（6.8%）成交额 ≥500 万
# 美元；同一天全市场"24h 涨跌幅绝对值 Top10"里有 9 个是成交额不足 400 万美元
# 的垃圾币（PHB -69%/qv=147万、NFP -66%/qv=383万、CREAM +65%/qv=28万……），
# 这正是要过滤掉的噪音。
MIN_QUOTE_VOLUME_USD = 5_000_000

# ── 分层：按 24h 成交额给币分档 ───────────────────────────────────────
# 为什么用成交额而不是市值：
#   1) 成交额已经在 /ticker/24hr 的同一份响应里，零额外请求；
#   2) 判断"这个涨跌值不值得当新闻"，真正相关的是有多少钱在这上面交易，而不是
#      虚的 FDV。市值高但没人交易的币涨跌没有新闻价值；
#   3) 少一个外部依赖（CoinGecko 市值）就少一个故障点/速率限制风险。
#
# 分档数值经 2026-07-25 实测全市场分布校准（初版按"日成交额 ≥1亿美元=一线"设的
# 100M/20M 档位，实测当天只有 4 个币过 1 亿美元，T2/T3 几乎没有区分度）。改用
# 实测数据本身的分布切档：
#   qv ≥ 30M：约 5~8 个币（BTC/ETH 之外的第二档，如 DEXE/AERO/SOL/BANK/BNB）
#   qv ≥ 10M：约 20 个币（第三档）
#   qv ≥ 5M（MIN 线）：其余约 14~20 个币（第四档）
# 这套档位是"币安现货市场当前实际流动性分布"的校准结果，不是拍脑袋的整数；如果
# 未来市场整体流动性回升，应重新跑一次 calibration 校准。
TIER_LARGE_VOLUME_USD = 30_000_000    # T2
TIER_MID_VOLUME_USD = 10_000_000      # T3
# 低于 TIER_MID 但 ≥ MIN_QUOTE_VOLUME 的算 T4

# BTC/ETH 单独成档：它们是整个市场的 beta，一动全市场跟着动。
TIER1_BASES = {"BTC", "ETH"}

# ── 信号 1：24h 大幅涨跌阈值（按档位分级）────────────────────────────
# 取值依据（2026-07-25 全市场实测，见模块末尾 calibration 说明）：
#   T1 BTC/ETH  ±5%  —— 当天 BTC/ETH 实际涨跌仅 +0.2%/+0.5%，5% 阈值意味着日常
#                        不会触发，只有真正的大波动才会响；
#   T2 二档      ±8%  —— 当天 T2 档里 DEXE +26.7%、BANK +15.2% 触发，AERO -0.65%/
#                        SOL +0.85% 不触发，区分度合理；
#   T3 三档      ±15% —— 当天 EUL +62.7%、SHIB +18.2%、SYN +17.9%、UTK +16.2%、
#                        ALLO -27.5% 触发，VANA -6.5%/AVAX +7.9%/WLD -4.9% 不
#                        触发，8 个候选里 5 个触发，密度合理；
#   T4 四档      ±25% —— 当天该档最大波动是 ACE -14.1%、RIF -16.6%，均未达标，
#                        说明该档当天没有真正的异动，符合预期（小盘币日常 10~15%
#                        波动不该播报）。
PRICE_MOVE_THRESHOLDS = {
    "T1": 5.0,
    "T2": 8.0,
    "T3": 15.0,
    "T4": 25.0,
}

# ── 信号 2：突破关键价位 ──────────────────────────────────────────────
# 整数关口的"步长"按价格量级自适应：step = 10^floor(log10(px)) / 2
#   BTC 64,000 → 步长 5,000（6.0万 / 6.5万 / 7.0万）
#   ETH  1,870 → 步长 500  （1500 / 2000）
#   SOL     74 → 步长 50   （50 / 100）
#   XRP    1.1 → 步长 0.5
# 这样每个币的关口密度大致相同（价格的 ~5%~10% 一档）。
KEY_LEVEL_DIVISOR = 2

# 穿越确认幅度：价格必须越过关口至少 0.25% 才算"有效突破"，避免在关口上下
# 反复摩擦时来回触发。
LEVEL_CONFIRM_PCT = 0.25

# 只有这些主流币做关口播报和爆仓监控。长尾币的"整数关口"没有心理意义。
MAJOR_BASES = [
    "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK",
    "TRX", "DOT", "LTC", "BCH", "TON", "SHIB", "SUI", "NEAR", "APT",
    "UNI", "PEPE", "HBAR", "ARB", "OP", "ATOM", "FIL", "ETC", "AAVE",
]

# 周期新高/新低回看窗口（天）。30 日兼顾"够久所以有意义"和"够近所以还算新闻"；
# 90 日是季度级别，触发时通常伴随趋势转折，值得单独播报。
PERIOD_HIGH_LOW_WINDOWS = (30, 90)

# ── 信号 3：成交量异动 ────────────────────────────────────────────────
# 当前 24h 成交额 / 近 7 个完整日线成交额的中位数。用中位数而非均值：如果前 7
# 天已经有一天爆量，均值会被抬高，导致真正的连续放量反而检测不出来。
VOLUME_SPIKE_RATIO = 3.0
# 2026-07-25 实测 42 个流动性达标币的 ratio 分布：中位数 1.00、p75=2.24、
# p90=8.01，3 倍处于分布右尾但不是极端（top10 里有 7 个 ≥3 倍），2 倍会混进
# p75 附近的日常波动，5 倍会把 DEXE(5.95x)/AERO(8.01x) 这类真实放量漏掉。
VOLUME_SPIKE_MIN_QUOTE_USD = 10_000_000
# 放量倍数再高，成交额本身太小也没有新闻价值；10M 与 TIER_MID 对齐。

# ── 信号 4：资金费率异常 ──────────────────────────────────────────────
# 统一折算成年化百分比。OKX 全部品种统一 8 小时结算，折算：rate * 3 * 365 * 100；
# Hyperliquid 每 1 小时结算：rate * 24 * 365 * 100。
#
# 2026-07-25 实测 OKX 头部 28 个合约的年化费率分布：中位数 +4.4%，p90 +11.0%
# （已达 OKX 费率上限，多数正费率品种卡在 +11% 封顶），最负 -54.6%（MORPHO）。
# 因为 OKX 有费率硬上限（观测到多个品种精确卡在 11.0%），正费率异常在这个数据
# 源上很难用"数值绝对偏高"判断（大家都卡在上限）；但负费率没有对称上限，
# -30%~-55% 这个量级确实罕见（观测到的 3 个负费率品种分别是 -46.5/-50.9/
# -54.6），保留有区分度。
FUNDING_POSITIVE_APR = 50.0   # OKX 费率有上限，此阈值主要靠 Hyperliquid 兜底数据触发
FUNDING_NEGATIVE_APR = -30.0  # 负费率稀有，-30% 已经是 2026-07-25 观测分布的 p10 附近

# 资金费率信号的持仓量下限：持仓不足 1000 万美元的小品种费率天然剧烈跳动。
FUNDING_MIN_OI_USD = 10_000_000

# 资金费率检查的标的范围：主流币 ∪ 现货成交额前 40，覆盖当轮真正有交易量的
# 品种，避免对着 400+ 个几乎无人问津的合约逐个发请求（OKX 无批量费率接口）。
FUNDING_UNIVERSE_TOP_N = 40

# ── 信号 5：持仓量骤变 ────────────────────────────────────────────────
# OKX /public/open-interest 是当前快照的批量接口（一次拉全市场），没有历史序列；
# 用状态表存上一轮快照，跨轮做差。2026-07-26 更正：本模块现在跟随
# scripts/stage_fetch.py 每 2 小时跑一轮（不再是写这段注释时的 4 小时主 cron），
# 快照间隔 ~2h，落在 OI_MIN_HOURS(1.5)～OI_MAX_HOURS(12) 的有效窗口内。
# 首轮没有基线，不产信号，从第二轮开始生效。
OI_CHANGE_PCT = 30.0
# 4 小时内持仓量增减三成属于明确的资金进出，通常对应插针爆仓或新资金建仓。

OI_MIN_USD = 20_000_000        # 持仓量绝对下限
OI_MIN_HOURS = 1.5             # 两次快照间隔太短没意义
OI_MAX_HOURS = 12.0            # 间隔太久（爬虫停了一天）这个差值不再是"骤变"

# ── 信号 6：爆仓 ──────────────────────────────────────────────────────
# OKX /public/liquidation-orders 只能按 instFamily 逐个查（无 instType 级别的
# 批量接口），每次最多返回 100 条最近记录。只对 MAJOR_BASES（27 个）做，控制
# 请求数。
#
# 重要限制（写进 summary，不能含糊）：这里的爆仓额**只覆盖 OKX 一家交易所**，
# 不代表全市场（含币安自己）的真实爆仓总量——币安持仓量远大于 OKX，真实全市场
# 爆仓额会明显更高。但币安数据在生产 VM 上完全拿不到（451），OKX 是目前唯一
# 验证可用的替代，所以阈值刻意保守，宁可漏报也不夸大成"全网爆仓"。
#
# 窗口用固定 1 小时（而不是"上次轮询到现在"）：爆仓记录本身就是时间戳序列，
# 1 小时是行业惯例的报道颗粒度（"过去一小时全网爆仓 XX"），换成变长窗口反而
# 会让同一波爆仓因为轮询节奏不同而算出不同的口径。
LIQUIDATION_WINDOW_HOURS = 1.0
LIQUIDATION_MIN_NOTIONAL_USD = {
    "T1": 3_000_000,   # BTC/ETH：OKX 单家 1 小时 300 万美元已经是明显的连环爆仓
    "default": 1_000_000,
}

# ── 抑制（去重）参数 ──────────────────────────────────────────────────
# 同一个 (信号类型, 币, 方向) 在冷却期内只播一次。爬虫 4 小时一轮，如果不抑制，
# 一个持续下跌的行情会让"BTC 24 小时下跌"这条重复生成 6 次/天。
COOLDOWN_HOURS = {
    "price_move": 12.0,      # 半天。同一个币同方向的大波动，半天播一次足够
    "level_break": 24.0,     # 关口突破按 (币,关口,方向) 计，一天内不重复
    "period_extreme": 24.0,  # 周期新高新低同理
    "volume_spike": 12.0,
    "funding_extreme": 12.0,
    "oi_jump": 8.0,
    "liquidation": 4.0,      # 爆仓是急性事件，冷却期最短，一轮（4h）即可再播
}

# 冷却期内的"升级"豁免：行情继续恶化时不应该被冷却期憋着不播。跌幅从 -6% 扩大
# 到 -14% 是一条新新闻，所以只要比上次已播报的幅度又多走了 ESCALATION_STEP_PCT
# 个百分点，就允许提前再播一次。
ESCALATION_STEP_PCT = 8.0

# 每轮总量上限。防止市场普跌时一次性灌进来上百条同质事件把 pipeline 和版面淹掉。
MAX_SIGNALS_PER_RUN = 25

# 单个币每轮最多几条。一个币同时满足"大跌+破关口+放量"时只留最显著的两条。
MAX_SIGNALS_PER_SYMBOL = 2

# MySQL 状态表里超过这个天数没更新的行直接清掉，避免表无限膨胀。
STATE_TTL_DAYS = 30


# ══════════════════════════════════════════════════════════════════════
# 币种中文名（只覆盖主流币；表里没有的直接用符号，不猜）
# ══════════════════════════════════════════════════════════════════════
COIN_NAMES_ZH = {
    "BTC": "比特币", "ETH": "以太坊", "BNB": "BNB", "SOL": "Solana",
    "XRP": "瑞波币", "DOGE": "狗狗币", "ADA": "艾达币", "AVAX": "Avalanche",
    "LINK": "Chainlink", "TRX": "波场", "DOT": "波卡", "LTC": "莱特币",
    "BCH": "比特币现金", "TON": "TON", "SHIB": "柴犬币", "SUI": "Sui",
    "NEAR": "NEAR", "APT": "Aptos", "UNI": "Uniswap", "PEPE": "PEPE",
    "HBAR": "Hedera", "ARB": "Arbitrum", "OP": "Optimism", "ATOM": "Cosmos",
    "FIL": "Filecoin", "ETC": "以太坊经典", "AAVE": "Aave", "XLM": "恒星币",
    "ICP": "ICP", "WLD": "Worldcoin", "SEI": "Sei", "TIA": "Celestia",
    "INJ": "Injective", "RUNE": "THORChain", "LDO": "Lido", "CRV": "Curve",
    "MKR": "Maker", "ENA": "Ethena", "JUP": "Jupiter", "PENDLE": "Pendle",
    "BONK": "BONK", "WIF": "dogwifhat", "FLOKI": "FLOKI",
}


def coin_label(base: str) -> str:
    """返回用于标题的币种名称。有中文名的用『中文名（SYMBOL）』，没有的只用符号。
    不给长尾币硬凑中文名——猜错了比不写更糟。
    """
    name = COIN_NAMES_ZH.get(base)
    if not name or name == base:
        return base
    return f"{name}（{base}）"


# ══════════════════════════════════════════════════════════════════════
# HTTP
# ══════════════════════════════════════════════════════════════════════

_session = requests.Session()
_session.headers.update(HEADERS)

# 记住哪个现货主机是通的，避免每轮都在 451 上浪费一次往返
_spot_host_cache: dict[str, str] = {}


def _expect_list(payload, ctx: str) -> list:
    """列表型接口的返回值守卫。

    币安在被地区封锁 / 限频 / 参数错误时，会用 **dict** 形式返回错误体：
        {"code": 0, "msg": "Service unavailable from a restricted location..."}
    如果不校验直接 payload[0] 或者 for x in payload: x["symbol"]，就会抛出
    `string indices must be integers` 或 KeyError(0)——两个报错都完全看不出真实
    原因是地区封锁。这里统一拦下来并把真实的 code/msg 打进日志。
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        raise RuntimeError(
            f"{ctx}: expected list, got error dict "
            f"code={payload.get('code')} msg={str(payload.get('msg'))[:160]}"
        )
    raise RuntimeError(f"{ctx}: expected list, got {type(payload).__name__}")


def _spot_get(path: str, params: dict | None = None) -> list:
    """请求现货接口，按 SPOT_HOSTS 顺序做主机故障转移。"""
    cached = _spot_host_cache.get("spot")
    hosts = ([cached] + [h for h in SPOT_HOSTS if h != cached]) if cached else list(SPOT_HOSTS)

    last_error: Exception | None = None
    for host in hosts:
        try:
            resp = _session.get(host + path, params=params, timeout=HTTP_TIMEOUT)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:120]}")
            data = _expect_list(resp.json(), f"{host}{path}")
            if _spot_host_cache.get("spot") != host:
                logger.info(f"market_signals: using spot host {host}")
                _spot_host_cache["spot"] = host
            return data
        except Exception as e:
            last_error = e
            logger.debug(f"market_signals: spot host {host} failed on {path}: {e}")
    raise RuntimeError(f"all spot hosts failed for {path}: {last_error}")


def _okx_get(path: str, params: dict | None = None) -> dict:
    resp = _session.get(OKX_HOST + path, params=params, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if str(payload.get("code")) != "0":
        raise RuntimeError(f"OKX {path}: code={payload.get('code')} msg={payload.get('msg')}")
    return payload


# ══════════════════════════════════════════════════════════════════════
# 数值格式化（纯本地，无 LLM）
# ══════════════════════════════════════════════════════════════════════

def fmt_price(px: float) -> str:
    """价格 → 人读得懂的中文串。
    10000 以上用"万美元"（BTC 64335 → 6.43 万美元），符合中文读者习惯；
    小数币保留足够有效位，不然 PEPE 会被格成 0.00 美元。
    """
    if px >= 10000:
        return f"{px / 10000:.2f} 万美元".replace(".00 万", " 万")
    if px >= 100:
        return f"{px:,.2f} 美元"
    if px >= 1:
        return f"{px:.3f} 美元"
    if px >= 0.01:
        return f"{px:.5f} 美元"
    return f"{px:.8f}".rstrip("0") + " 美元"


def fmt_level(px: float) -> str:
    """关口价位 → 中文串。关口是整数，不需要保留小数尾巴。"""
    if px >= 10000:
        v = px / 10000
        return (f"{v:.1f}" if v != int(v) else f"{int(v)}") + " 万美元"
    if px >= 1:
        return (f"{px:,.0f}" if px == int(px) else f"{px:,.2f}") + " 美元"
    return f"{px:g} 美元"


def fmt_usd(v: float) -> str:
    """金额 → 亿/万美元。成交额、持仓量、爆仓额都用它。"""
    if v >= 1e8:
        return f"{v / 1e8:.2f} 亿美元"
    if v >= 1e4:
        return f"{v / 1e4:.0f} 万美元"
    return f"{v:,.0f} 美元"


def _now() -> datetime:
    """tz-aware UTC，用于 item 的 published_at（下游/其他 fetch_* 都是这个格式）。"""
    return datetime.now(timezone.utc)


def _now_naive() -> datetime:
    """naive UTC，用于和 MySQL DATETIME 列比较——项目里 storage.to_mysql_datetime()
    也是把 tz 信息去掉存 naive 时间，这里保持同一约定，避免 aware/naive 混用报错。"""
    return datetime.utcnow()


# ══════════════════════════════════════════════════════════════════════
# 抑制机制：跨轮状态（MySQL 表 market_signal_state）
# ══════════════════════════════════════════════════════════════════════

class SignalState:
    """跨轮状态，负责三件事：

    1. **冷却**：记录每个 signal_key 上次播报的时间与幅度，冷却期内不重复播报，
       除非幅度又扩大了 ESCALATION_STEP_PCT（行情继续恶化算新新闻）。
    2. **穿越判定的基线**：存上一轮每个币的收盘价，关口突破只在"这一轮真的从
       关口一侧走到另一侧"时触发。
    3. **持仓量差分的基线**：存上一轮持仓量快照，免费接口拿不到历史序列，只能
       靠自己攒。

    状态存 MySQL 表 market_signal_state（见 config/migrations/002_market_signal_
    state.sql）。数据库不可用时降级为纯内存（当次运行内一致，但不做跨轮冷却）——
    宁可多播一轮，也不要因为状态问题整个模块挂掉。
    """

    def __init__(self):
        self.data: dict = {"emitted": {}, "prices": {}, "oi": {}}
        self._dirty: dict = {"emitted": set(), "prices": set(), "oi": set()}
        self._conn = None
        self._db_ok = False
        try:
            self._conn = storage.get_mysql_conn()
            self._load()
            self._db_ok = True
        except Exception as e:
            logger.warning(f"market_signals: MySQL state unavailable ({e}); "
                           f"falling back to in-memory-only state for this run "
                           f"(no cross-run cooldown until DB recovers)")

    def _load(self) -> None:
        cur = self._conn.cursor()
        cur.execute("SELECT state_kind, state_key, numeric_value, updated_at "
                    "FROM market_signal_state")
        n = 0
        for kind, key, value, updated_at in cur.fetchall():
            if kind == "emitted":
                self.data["emitted"][key] = {"ts": updated_at, "magnitude": value}
            elif kind == "price":
                self.data["prices"][key] = {"ts": updated_at, "price": value}
            elif kind == "oi":
                self.data["oi"][key] = {"ts": updated_at, "oi_usd": value}
            n += 1
        cur.close()
        logger.info(f"market_signals: loaded {n} state rows from MySQL")

    def save(self) -> None:
        if not self._db_ok or not self._conn:
            return
        rows = []
        for key in self._dirty["emitted"]:
            rec = self.data["emitted"].get(key)
            if rec:
                rows.append((key, "emitted", rec["magnitude"]))
        for key in self._dirty["prices"]:
            rec = self.data["prices"].get(key)
            if rec:
                rows.append((key, "price", rec["price"]))
        for key in self._dirty["oi"]:
            rec = self.data["oi"].get(key)
            if rec:
                rows.append((key, "oi", rec["oi_usd"]))
        try:
            cur = self._conn.cursor()
            if rows:
                cur.executemany(
                    "INSERT INTO market_signal_state "
                    "(state_key, state_kind, numeric_value, updated_at) "
                    "VALUES (%s, %s, %s, NOW()) "
                    "ON DUPLICATE KEY UPDATE numeric_value=VALUES(numeric_value), "
                    "updated_at=NOW()",
                    [(key, kind, value) for key, kind, value in rows],
                )
            cutoff = _now_naive() - timedelta(days=STATE_TTL_DAYS)
            cur.execute("DELETE FROM market_signal_state WHERE updated_at < %s",
                       (cutoff,))
            self._conn.commit()
            cur.close()
            logger.info(f"market_signals: persisted {len(rows)} state rows to MySQL")
        except Exception as e:
            logger.warning(f"market_signals: failed to persist state: {e}")
        finally:
            try:
                self._conn.close()
            except Exception:
                pass

    # ── 冷却 / 升级 ──────────────────────────────────────────────────
    def allows(self, key: str, magnitude: float, kind: str) -> bool:
        record = self.data["emitted"].get(key)
        if not record:
            return True
        ts = record.get("ts")
        if ts is None:
            return True
        hours = (_now_naive() - ts).total_seconds() / 3600
        if hours >= COOLDOWN_HOURS.get(kind, 12.0):
            return True
        previous = abs(float(record.get("magnitude", 0.0)))
        return abs(magnitude) >= previous + ESCALATION_STEP_PCT

    def mark_magnitude(self, key: str, magnitude: float) -> None:
        self.data["emitted"][key] = {"ts": _now_naive(), "magnitude": round(float(magnitude), 4)}
        self._dirty["emitted"].add(key)

    # ── 价格基线 ─────────────────────────────────────────────────────
    def prev_price(self, symbol: str) -> float | None:
        record = self.data["prices"].get(symbol)
        if not record:
            return None
        ts = record.get("ts")
        # 基线太旧（比如爬虫停了两天）就不用了，退回 24h 开盘价
        if ts and (_now_naive() - ts).total_seconds() / 3600 > 24:
            return None
        try:
            return float(record["price"])
        except (KeyError, TypeError, ValueError):
            return None

    def record_price(self, symbol: str, price: float) -> None:
        self.data["prices"][symbol] = {"ts": _now_naive(), "price": price}
        self._dirty["prices"].add(symbol)

    # ── 持仓量基线 ───────────────────────────────────────────────────
    def prev_oi(self, name: str) -> tuple[float, float] | None:
        """返回 (上一轮持仓量USD, 距今小时数)，无可用基线时 None。"""
        record = self.data["oi"].get(name)
        if not record:
            return None
        ts = record.get("ts")
        if ts is None:
            return None
        hours = (_now_naive() - ts).total_seconds() / 3600
        try:
            return float(record["oi_usd"]), hours
        except (KeyError, TypeError, ValueError):
            return None

    def record_oi(self, name: str, oi_usd: float) -> None:
        self.data["oi"][name] = {"ts": _now_naive(), "oi_usd": oi_usd}
        self._dirty["oi"].add(name)


# ══════════════════════════════════════════════════════════════════════
# 抓取：现货
# ══════════════════════════════════════════════════════════════════════

def fetch_spot_tickers() -> list[dict]:
    """拉全市场 24h 行情并清洗成内部结构。

    /api/v3/ticker/24hr 不带 symbol 参数时返回全部交易对的 list（2026-07-25 实测
    620 个 USDT 现货对，1.9MB，约 1~3 秒）。一次请求覆盖涨跌幅 + 成交额 + 最高
    最低价，是本模块最主要的数据来源。
    """
    raw = _spot_get("/api/v3/ticker/24hr")
    rows: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        symbol = entry.get("symbol", "")
        if not symbol.endswith(QUOTE_ASSET) or symbol.endswith(LEVERAGED_SUFFIXES):
            continue
        base = symbol[: -len(QUOTE_ASSET)]
        if not base or base in STABLE_BASES:
            continue
        try:
            last = float(entry["lastPrice"])
            change_pct = float(entry["priceChangePercent"])
            quote_volume = float(entry["quoteVolume"])
            high = float(entry["highPrice"])
            low = float(entry["lowPrice"])
            open_price = float(entry["openPrice"])
        except (KeyError, TypeError, ValueError):
            continue
        if last <= 0 or quote_volume < MIN_QUOTE_VOLUME_USD:
            continue
        rows.append({
            "symbol": symbol, "base": base, "last": last, "open": open_price,
            "change_pct": change_pct, "quote_volume": quote_volume,
            "high": high, "low": low,
            "trades": int(entry.get("count") or 0),
        })
    rows.sort(key=lambda r: -r["quote_volume"])
    logger.info(f"market_signals: {len(rows)} liquid {QUOTE_ASSET} pairs "
                f"(from {len(raw)} raw symbols)")
    return rows


def fetch_daily_klines(symbols: list[str], workers: int = 8) -> dict[str, list]:
    """并发拉日线。limit=91 → 90 个完整日 + 今天这根未完成的。

    一次调用同时服务两类信号：周期新高新低（用完整日线的 high/low）和成交量异动
    （用完整日线的 quoteAssetVolume 中位数）。
    """
    result: dict[str, list] = {}

    def one(symbol: str):
        try:
            return symbol, _spot_get("/api/v3/klines", {
                "symbol": symbol, "interval": "1d", "limit": max(PERIOD_HIGH_LOW_WINDOWS) + 1,
            })
        except Exception as e:
            logger.debug(f"market_signals: klines {symbol} failed: {e}")
            return symbol, None

    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for symbol, data in pool.map(one, symbols):
            if data:
                result[symbol] = data
    logger.info(f"market_signals: klines fetched for {len(result)}/{len(symbols)} symbols")
    return result


# ══════════════════════════════════════════════════════════════════════
# 抓取：合约（资金费率 / 持仓量 / 爆仓）
# ══════════════════════════════════════════════════════════════════════

def fetch_okx_open_interest() -> dict[str, float]:
    """一次性拉 OKX 全市场 SWAP 持仓量（USD），按 base 聚合。

    同一个 base 可能有 -USDT-SWAP 和 -USD-SWAP（币本位）两个合约，优先取
    USDT 本位，量级和现货一致，两边都没有再取较大者。
    """
    payload = _okx_get("/api/v5/public/open-interest", {"instType": "SWAP"})
    out: dict[str, float] = {}
    have_usdt: set[str] = set()
    for row in payload.get("data", []):
        inst_id = row.get("instId", "")
        try:
            oi_usd = float(row.get("oiUsd", 0))
        except (TypeError, ValueError):
            continue
        if inst_id.endswith("-USDT-SWAP"):
            base = inst_id[: -len("-USDT-SWAP")]
            out[base] = oi_usd
            have_usdt.add(base)
        elif inst_id.endswith("-USD-SWAP"):
            base = inst_id[: -len("-USD-SWAP")]
            if base not in have_usdt:
                out[base] = max(out.get(base, 0.0), oi_usd)
    return out


def fetch_okx_funding_rates(bases: list[str], workers: int = 10) -> dict[str, float]:
    """逐个 instId 查资金费率并折算成年化百分比。OKX 全品种统一 8 小时结算。

    OKX 没有批量费率接口，只能并发单查；bases 限定在"主流币 ∪ 现货成交额前
    FUNDING_UNIVERSE_TOP_N"，把请求数控制在 ~50 个以内。
    """
    out: dict[str, float] = {}

    def one(base: str):
        try:
            payload = _okx_get("/api/v5/public/funding-rate",
                               {"instId": f"{base}-USDT-SWAP"})
            rate = float(payload["data"][0]["fundingRate"])
            return base, rate * 3 * 365 * 100   # 8h 结算 → 一年 3*365 次
        except Exception as e:
            logger.debug(f"market_signals: OKX funding-rate {base} failed: {e}")
            return base, None

    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for base, apr in pool.map(one, bases):
            if apr is not None:
                out[base] = apr
    return out


def fetch_okx_liquidations(bases: list[str], workers: int = 10) -> dict[str, dict]:
    """逐个 instFamily 查最近爆仓记录，汇总 LIQUIDATION_WINDOW_HOURS 窗口内的
    多空爆仓额（USD）。只对 MAJOR_BASES 做，控制请求数。

    ctVal（合约面值）来自 /public/instruments，先批量拉一次缓存，避免每个 base
    再多打一次请求。
    """
    try:
        inst_payload = _okx_get("/api/v5/public/instruments", {"instType": "SWAP"})
        ctval = {
            row["instId"]: float(row["ctVal"])
            for row in inst_payload.get("data", [])
            if row.get("instId", "").endswith("-USDT-SWAP")
        }
    except Exception as e:
        logger.warning(f"market_signals: OKX instruments (ctVal) failed: {e}")
        return {}

    cutoff_ms = (time.time() - LIQUIDATION_WINDOW_HOURS * 3600) * 1000

    def one(base: str):
        inst_id = f"{base}-USDT-SWAP"
        cv = ctval.get(inst_id)
        if not cv:
            return base, None
        try:
            payload = _okx_get("/api/v5/public/liquidation-orders", {
                "instType": "SWAP", "state": "filled",
                "instFamily": f"{base}-USDT", "limit": 100,
            })
        except Exception as e:
            logger.debug(f"market_signals: OKX liquidation-orders {base} failed: {e}")
            return base, None
        long_usd = short_usd = 0.0
        n = 0
        for blk in payload.get("data", []):
            if blk.get("instId") != inst_id:
                continue
            for det in blk.get("details", []):
                try:
                    ts = float(det["ts"])
                    if ts < cutoff_ms:
                        continue
                    notional = float(det["sz"]) * cv * float(det["bkPx"])
                except (KeyError, TypeError, ValueError):
                    continue
                n += 1
                if det.get("posSide") == "long":
                    long_usd += notional
                else:
                    short_usd += notional
        return base, {"long_usd": long_usd, "short_usd": short_usd,
                      "total_usd": long_usd + short_usd, "count": n}

    out: dict[str, dict] = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for base, info in pool.map(one, bases):
            if info is not None:
                out[base] = info
    return out


def fetch_hyperliquid_context() -> dict[str, dict]:
    """Hyperliquid 兜底：仅在 OKX 整体不可用时使用。返回 {base: {funding_apr, oi_usd}}."""
    try:
        resp = _session.post(HYPERLIQUID_INFO, json={"type": "metaAndAssetCtxs"},
                             timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        universe = payload[0]["universe"]
        contexts = payload[1]
        out = {}
        for meta, ctx in zip(universe, contexts):
            base = meta.get("name", "")
            if not base:
                continue
            try:
                rate = float(ctx["funding"])
                mark = float(ctx["markPx"])
                oi = float(ctx["openInterest"])
            except (KeyError, TypeError, ValueError):
                continue
            out[base] = {
                "funding_apr": rate * 24 * 365 * 100,   # 每 1 小时结算 → 一年 8760 次
                "oi_usd": oi * mark,
            }
        logger.info(f"market_signals: Hyperliquid fallback context ({len(out)} bases)")
        return out
    except Exception as e:
        logger.warning(f"market_signals: Hyperliquid fallback also failed ({e}); "
                       f"funding/OI/liquidation signals skipped this round")
        return {}


# ══════════════════════════════════════════════════════════════════════
# 分层与工具
# ══════════════════════════════════════════════════════════════════════

def tier_of(row: dict) -> str:
    if row["base"] in TIER1_BASES:
        return "T1"
    if row["quote_volume"] >= TIER_LARGE_VOLUME_USD:
        return "T2"
    if row["quote_volume"] >= TIER_MID_VOLUME_USD:
        return "T3"
    return "T4"


def authority_of(tier: str) -> int:
    """权威分。数据本身来自交易所官方接口，事实性可靠；但长尾币适度降一档。"""
    return {"T1": 5, "T2": 5, "T3": 4, "T4": 3}.get(tier, 3)


def key_levels_between(low: float, high: float, price: float) -> list[float]:
    """返回 (low, high] 区间内的所有整数关口。"""
    if price <= 0 or high <= low:
        return []
    step = (10 ** math.floor(math.log10(price))) / KEY_LEVEL_DIVISOR
    if step <= 0:
        return []
    levels, n = [], math.floor(low / step) + 1
    while n * step <= high and len(levels) < 12:
        levels.append(round(n * step, 10))
        n += 1
    return levels


def _trade_url(symbol: str, base: str, anchor: str) -> str:
    """行情页深链。带 anchor 是为了让 pipeline 的 URL 粗去重把不同信号视为不同
    条目（prefilter_duplicates 用 url 完全相等来判重），同时 anchor 对页面本身
    无副作用。"""
    return f"https://www.binance.com/zh-CN/trade/{base}_{QUOTE_ASSET}?type=spot#{anchor}"


def _item(source: str, title: str, url: str, summary: str, authority: int,
          signal_type: str, signal_key: str) -> dict:
    """组装成与 crawler/main.py 其他 fetch_* 完全一致的 item 结构。"""
    # URL 追加触发时间成分（2026-07-26 review 修复，HIGH）：行情页锚点原本是
    # 静态的（#move-up 等），而 staging 表按 url_hash 永久去重、consumed_at 一去
    # 不回——同一 (币, 信号类型, 方向) 第二次合法触发起，条目会在存档层被静默
    # 吞掉，且 llm_enrich_cache 还会把首次播报的旧数字喂给未来的重报。加上
    # 小时级时间戳后每次 SignalState 放行的播报都是独立 URL；重发频率本就由
    # 冷却闸门控制，不会爆量。对行情页本身，fragment 无副作用。
    return {
        "source": source,
        "title": title,
        "url": f"{url}-{_now().strftime('%Y%m%dT%H')}",
        "summary": summary,
        "published_at": _now().isoformat(),
        "lang": "zh",
        "authority": authority,
        "type": "market_signal",
        # 以下两个键 pipeline 不消费，仅用于本模块日志与验证脚本
        "signal_type": signal_type,
        "signal_key": signal_key,
    }


# ══════════════════════════════════════════════════════════════════════
# 信号检测
# ══════════════════════════════════════════════════════════════════════

def detect_price_moves(rows: list[dict], state: SignalState) -> list[dict]:
    """信号 1：24h 大幅涨跌（按流动性分层设阈值）。"""
    signals = []
    ranked = sorted(rows, key=lambda r: -abs(r["change_pct"]))
    rank_of = {r["symbol"]: i + 1 for i, r in enumerate(ranked)}

    for row in rows:
        tier = tier_of(row)
        threshold = PRICE_MOVE_THRESHOLDS[tier]
        pct = row["change_pct"]
        if abs(pct) < threshold:
            continue

        direction = "up" if pct > 0 else "down"
        key = f"price_move:{row['symbol']}:{direction}"
        if not state.allows(key, abs(pct), "price_move"):
            continue

        base, label = row["base"], coin_label(row["base"])
        verb = "上涨" if pct > 0 else "下跌"
        title = (f"{label} 24 小时{verb} {abs(pct):.1f}%，"
                 f"现报 {fmt_price(row['last'])}，"
                 f"24 小时成交额 {fmt_usd(row['quote_volume'])}")
        summary = (
            f"[行情异动] {label} 过去 24 小时{verb} {abs(pct):.2f}%，"
            f"最新成交价 {fmt_price(row['last'])}"
            f"（24 小时最高 {fmt_price(row['high'])}，最低 {fmt_price(row['low'])}）。"
            f"同期 24 小时成交额 {fmt_usd(row['quote_volume'])}，"
            f"涨跌幅在全市场 USDT 现货交易对中排名第 {rank_of[row['symbol']]}。"
            f"该币按 24 小时成交额划入 {tier} 档，触发阈值为 ±{threshold:.0f}%。"
            f"数据来源：币安现货公开行情接口（data-api.binance.vision）。"
        )
        signals.append({
            "item": _item("MarketSignal/Binance", title,
                          _trade_url(row["symbol"], base, f"move-{direction}"),
                          summary, authority_of(tier), "price_move", key),
            "key": key, "magnitude": abs(pct), "kind": "price_move",
            "symbol": row["symbol"], "tier": tier,
            "salience": abs(pct) / threshold,
        })
    return signals


def detect_level_breaks(rows: list[dict], klines: dict[str, list],
                        state: SignalState) -> list[dict]:
    """信号 2：突破/跌破整数关口 + 周期新高新低。只对主流币做。"""
    signals = []
    majors = {r["base"]: r for r in rows if r["base"] in MAJOR_BASES}

    for base, row in majors.items():
        symbol, last, tier = row["symbol"], row["last"], tier_of(row)

        # ── 2a. 整数关口穿越 ──
        prev = state.prev_price(symbol)
        baseline = prev if prev is not None else row["open"]
        if baseline > 0:
            low, high = min(baseline, last), max(baseline, last)
            for level in key_levels_between(low, high, last):
                if abs(last - level) / level * 100 < LEVEL_CONFIRM_PCT:
                    continue
                direction = "up" if last > level else "down"
                key = f"level_break:{symbol}:{level:g}:{direction}"
                if not state.allows(key, abs(row["change_pct"]), "level_break"):
                    continue
                verb = "突破" if direction == "up" else "跌破"
                label = coin_label(base)
                title = (f"{label}{verb} {fmt_level(level)}关口，"
                         f"24 小时{'涨幅' if row['change_pct'] >= 0 else '跌幅'} "
                         f"{abs(row['change_pct']):.1f}%")
                summary = (
                    f"[关键价位] {label} 价格{verb} {fmt_level(level)}整数关口，"
                    f"最新成交价 {fmt_price(last)}，"
                    f"较上一次观测价 {fmt_price(baseline)} "
                    f"{'上行' if direction == 'up' else '下行'}。"
                    f"过去 24 小时{'上涨' if row['change_pct'] >= 0 else '下跌'} "
                    f"{abs(row['change_pct']):.2f}%，区间 "
                    f"{fmt_price(row['low'])} - {fmt_price(row['high'])}，"
                    f"成交额 {fmt_usd(row['quote_volume'])}。"
                    f"仅在价格实际穿越关口且越过幅度超过 {LEVEL_CONFIRM_PCT}% 时播报。"
                    f"数据来源：币安现货公开行情接口。"
                )
                signals.append({
                    "item": _item("MarketSignal/Binance", title,
                                  _trade_url(symbol, base, f"level-{level:g}-{direction}"),
                                  summary, authority_of(tier), "level_break", key),
                    "key": key, "magnitude": abs(row["change_pct"]),
                    "kind": "level_break", "symbol": symbol, "tier": tier,
                    "salience": 2.0 + (1.0 if tier == "T1" else 0.0),
                })

        # ── 2b. 周期新高 / 新低 ──
        candles = klines.get(symbol)
        if not candles or len(candles) < 10:
            continue
        closed = candles[:-1]        # 去掉今天这根未完成的日线
        for window in PERIOD_HIGH_LOW_WINDOWS:
            recent = closed[-window:]
            if len(recent) < window * 0.8:   # 上市不足一个窗口的新币跳过
                continue
            try:
                window_high = max(float(c[2]) for c in recent)
                window_low = min(float(c[3]) for c in recent)
            except (TypeError, ValueError, IndexError):
                continue

            hit = None
            if row["high"] > window_high:
                hit = ("high", window_high, row["high"])
            elif row["low"] < window_low:
                hit = ("low", window_low, row["low"])
            if not hit:
                continue

            kind_, ref, extreme = hit
            key = f"period_extreme:{symbol}:{window}:{kind_}"
            if not state.allows(key, abs(row["change_pct"]), "period_extreme"):
                continue
            label = coin_label(base)
            word = "新高" if kind_ == "high" else "新低"
            title = (f"{label}创 {window} 日{word}，"
                     f"{'最高触及' if kind_ == 'high' else '最低下探'} {fmt_price(extreme)}")
            summary = (
                f"[周期极值] {label} 24 小时内{'最高价' if kind_ == 'high' else '最低价'} "
                f"{fmt_price(extreme)}，{'上破' if kind_ == 'high' else '下破'}此前 "
                f"{window} 个完整交易日的{'最高点' if kind_ == 'high' else '最低点'} "
                f"{fmt_price(ref)}，创 {window} 日{word}。"
                f"当前报 {fmt_price(last)}，24 小时"
                f"{'涨' if row['change_pct'] >= 0 else '跌'} "
                f"{abs(row['change_pct']):.2f}%，成交额 {fmt_usd(row['quote_volume'])}。"
                f"数据来源：币安现货日线数据。"
            )
            signals.append({
                "item": _item("MarketSignal/Binance", title,
                              _trade_url(symbol, base, f"extreme-{window}d-{kind_}"),
                              summary, authority_of(tier), "period_extreme", key),
                "key": key, "magnitude": abs(row["change_pct"]),
                "kind": "period_extreme", "symbol": symbol, "tier": tier,
                "salience": 1.5 + window / 90.0 + (1.0 if tier == "T1" else 0.0),
            })
    return signals


def detect_volume_spikes(rows: list[dict], klines: dict[str, list],
                         state: SignalState) -> list[dict]:
    """信号 3：成交额相对近 7 个完整交易日的中位数放大数倍。"""
    signals = []
    by_symbol = {r["symbol"]: r for r in rows}

    for symbol, candles in klines.items():
        row = by_symbol.get(symbol)
        if not row or row["quote_volume"] < VOLUME_SPIKE_MIN_QUOTE_USD:
            continue
        closed = candles[:-1]
        if len(closed) < 7:
            continue
        try:
            history = sorted(float(c[7]) for c in closed[-7:])   # index 7 = quoteAssetVolume
        except (TypeError, ValueError, IndexError):
            continue
        median = history[len(history) // 2]
        if median <= 0:
            continue
        ratio = row["quote_volume"] / median
        if ratio < VOLUME_SPIKE_RATIO:
            continue

        tier = tier_of(row)
        key = f"volume_spike:{symbol}"
        magnitude = ratio * 100   # 换算成"百分点"参与升级判断，与 ESCALATION_STEP_PCT 同量纲
        if not state.allows(key, magnitude, "volume_spike"):
            continue

        base, label = row["base"], coin_label(row["base"])
        pct = row["change_pct"]
        title = (f"{label}成交额放大至近 7 日均值的 {ratio:.1f} 倍，"
                 f"24 小时成交 {fmt_usd(row['quote_volume'])}，"
                 f"价格同期{'上涨' if pct >= 0 else '下跌'} {abs(pct):.1f}%")
        summary = (
            f"[成交量异动] {label} 过去 24 小时成交额 {fmt_usd(row['quote_volume'])}，"
            f"是此前 7 个完整交易日成交额中位数（{fmt_usd(median)}）的 {ratio:.2f} 倍，"
            f"触发放量阈值 {VOLUME_SPIKE_RATIO:.0f} 倍。"
            f"同期价格{'上涨' if pct >= 0 else '下跌'} {abs(pct):.2f}%，"
            f"现报 {fmt_price(row['last'])}，24 小时成交笔数 {row['trades']:,}。"
            f"用中位数而非均值做基线，以避免前期单日爆量抬高基准。"
            f"数据来源：币安现货 24 小时行情与日线数据。"
        )
        signals.append({
            "item": _item("MarketSignal/Binance", title,
                          _trade_url(symbol, base, "volume-spike"),
                          summary, authority_of(tier), "volume_spike", key),
            "key": key, "magnitude": magnitude, "kind": "volume_spike",
            "symbol": symbol, "tier": tier,
            "salience": min(3.0, ratio / VOLUME_SPIKE_RATIO),
        })
    return signals


def detect_funding_extremes(funding: dict[str, float], provider: str,
                            oi: dict[str, float], spot: dict[str, dict],
                            state: SignalState) -> list[dict]:
    """信号 4：永续合约资金费率极端值（多空失衡）。"""
    signals = []
    for base, apr in funding.items():
        oi_usd = oi.get(base, 0.0)
        if oi_usd and oi_usd < FUNDING_MIN_OI_USD:
            continue
        if apr >= FUNDING_POSITIVE_APR:
            direction, threshold = "pos", FUNDING_POSITIVE_APR
        elif apr <= FUNDING_NEGATIVE_APR:
            direction, threshold = "neg", FUNDING_NEGATIVE_APR
        else:
            continue

        key = f"funding_extreme:{base}:{direction}"
        if not state.allows(key, abs(apr), "funding_extreme"):
            continue

        label = coin_label(base)
        row = spot.get(base + QUOTE_ASSET)
        tier = tier_of(row) if row else "T3"
        spot_clause = ""
        if row:
            spot_clause = (f"现货同期{'上涨' if row['change_pct'] >= 0 else '下跌'} "
                           f"{abs(row['change_pct']):.2f}%，现报 {fmt_price(row['last'])}。")

        if direction == "neg":
            title = (f"{label}永续合约资金费率转负至年化 {apr:.0f}%，"
                     f"空头正在向多头支付费用")
            reading = ("资金费率为负意味着空头需要向多头支付费用，通常反映空头持仓"
                       "拥挤或现货抛压较重；负费率在多数时间里都是少数状态，持续转负"
                       "往往伴随情绪极端与潜在的轧空风险。")
        else:
            title = (f"{label}永续合约资金费率升至年化 {apr:.0f}%，多头杠杆明显过热")
            reading = ("资金费率大幅为正意味着多头需要持续向空头支付费用，反映做多"
                       "杠杆拥挤；该状态难以长期维持，通常对应阶段性情绪高点。")

        summary = (
            f"[衍生品信号] {label} 永续合约当前资金费率折合年化 {apr:+.2f}%，"
            f"触发{'负费率' if direction == 'neg' else '正费率'}阈值 "
            f"（年化 {threshold:+.0f}%）。"
            + (f"当前该合约未平仓持仓量约 {fmt_usd(oi_usd)}。" if oi_usd else "")
            + spot_clause + reading
            + f"数据来源：{provider} 永续合约公开接口。"
        )
        signals.append({
            "item": _item(f"MarketSignal/{provider}", title,
                          f"https://www.binance.com/zh-CN/futures/{base}USDT"
                          f"#funding-{direction}",
                          summary, authority_of(tier), "funding_extreme", key),
            "key": key, "magnitude": abs(apr), "kind": "funding_extreme",
            "symbol": base + QUOTE_ASSET, "tier": tier,
            "salience": min(3.0, abs(apr) / abs(threshold)),
        })
    return signals


def detect_oi_jumps(oi: dict[str, float], provider: str, spot: dict[str, dict],
                    state: SignalState) -> list[dict]:
    """信号 5：持仓量跨轮骤变。"""
    signals = []
    for base, oi_usd in oi.items():
        if oi_usd < OI_MIN_USD:
            if oi_usd > 0:
                state.record_oi(base, oi_usd)
            continue

        previous = state.prev_oi(base)
        state.record_oi(base, oi_usd)
        if not previous:
            continue
        prev_oi, hours = previous
        if prev_oi <= 0 or hours < OI_MIN_HOURS or hours > OI_MAX_HOURS:
            continue

        change = (oi_usd - prev_oi) / prev_oi * 100
        if abs(change) < OI_CHANGE_PCT:
            continue

        direction = "up" if change > 0 else "down"
        key = f"oi_jump:{base}:{direction}"
        if not state.allows(key, abs(change), "oi_jump"):
            continue

        label = coin_label(base)
        row = spot.get(base + QUOTE_ASSET)
        tier = tier_of(row) if row else "T3"
        verb = "增加" if change > 0 else "减少"
        title = (f"{label}永续合约持仓量 {hours:.1f} 小时内{verb} {abs(change):.0f}%，"
                 f"当前约 {fmt_usd(oi_usd)}")
        reading = ("持仓量快速上升通常意味着新增杠杆资金入场；"
                   if change > 0 else
                   "持仓量快速下降通常对应集中平仓或强制清算。")
        spot_clause = ""
        if row:
            spot_clause = (f"同期现货价格{'上涨' if row['change_pct'] >= 0 else '下跌'} "
                           f"{abs(row['change_pct']):.2f}%，现报 {fmt_price(row['last'])}。")
        summary = (
            f"[衍生品信号] {label} 永续合约未平仓持仓量在过去 {hours:.1f} 小时内由 "
            f"{fmt_usd(prev_oi)} {verb}至 {fmt_usd(oi_usd)}，变动 {change:+.2f}%，"
            f"触发阈值 ±{OI_CHANGE_PCT:.0f}%。" + reading + spot_clause
            + f"数据来源：{provider} 永续合约公开接口（跨轮快照差分）。"
        )
        signals.append({
            "item": _item(f"MarketSignal/{provider}", title,
                          f"https://www.binance.com/zh-CN/futures/{base}USDT#oi-{direction}",
                          summary, authority_of(tier), "oi_jump", key),
            "key": key, "magnitude": abs(change), "kind": "oi_jump",
            "symbol": base + QUOTE_ASSET, "tier": tier,
            "salience": min(3.0, abs(change) / OI_CHANGE_PCT),
        })
    return signals


def detect_liquidations(liq: dict[str, dict], spot: dict[str, dict],
                        state: SignalState) -> list[dict]:
    """信号 6：爆仓。仅覆盖 OKX 一家交易所的合约爆仓数据（币安在 VM 上不可达），
    summary 里明确标注这一限制，不夸大成"全网爆仓"。"""
    signals = []
    for base, info in liq.items():
        total = info["total_usd"]
        row = spot.get(base + QUOTE_ASSET)
        tier = tier_of(row) if row else ("T1" if base in TIER1_BASES else "T3")
        threshold = LIQUIDATION_MIN_NOTIONAL_USD.get(tier, LIQUIDATION_MIN_NOTIONAL_USD["default"])
        if total < threshold or info["count"] == 0:
            continue

        long_usd, short_usd = info["long_usd"], info["short_usd"]
        direction = "long" if long_usd >= short_usd else "short"
        key = f"liquidation:{base}:{direction}"
        if not state.allows(key, total, "liquidation"):
            continue

        label = coin_label(base)
        dominant_pct = (max(long_usd, short_usd) / total * 100) if total > 0 else 0
        side_word = "多头" if direction == "long" else "空头"
        title = (f"{label}合约 {LIQUIDATION_WINDOW_HOURS:.0f} 小时内爆仓 "
                 f"{fmt_usd(total)}（OKX），以{side_word}爆仓为主")
        spot_clause = ""
        if row:
            spot_clause = (f"同期现货价格{'上涨' if row['change_pct'] >= 0 else '下跌'} "
                           f"{abs(row['change_pct']):.2f}%，现报 {fmt_price(row['last'])}。")
        summary = (
            f"[爆仓信号] {label} 永续合约过去 {LIQUIDATION_WINDOW_HOURS:.0f} 小时内"
            f"（OKX 交易所口径）合计爆仓 {fmt_usd(total)}，其中{side_word}爆仓 "
            f"{fmt_usd(max(long_usd, short_usd))}，占比 {dominant_pct:.0f}%，"
            f"触发阈值 {fmt_usd(threshold)}。"
            f"注意：此数据仅覆盖 OKX 一家交易所，不代表全市场（含币安自身）真实"
            f"爆仓总量——币安相关数据在生产环境所在地区不可访问，OKX 是目前验证"
            f"可用的替代数据源，实际全市场爆仓规模通常更高。"
            + spot_clause
            + "数据来源：OKX 永续合约公开爆仓接口。"
        )
        signals.append({
            "item": _item("MarketSignal/OKX", title,
                          f"https://www.binance.com/zh-CN/futures/{base}USDT#liq-{direction}",
                          summary, authority_of(tier), "liquidation", key),
            "key": key, "magnitude": total, "kind": "liquidation",
            "symbol": base + QUOTE_ASSET, "tier": tier,
            "salience": min(3.0, total / threshold),
        })
    return signals


# ══════════════════════════════════════════════════════════════════════
# 编排
# ══════════════════════════════════════════════════════════════════════

KIND_PRIORITY = {
    "level_break": 5, "period_extreme": 4, "liquidation": 4, "price_move": 3,
    "oi_jump": 2, "funding_extreme": 2, "volume_spike": 1,
}
TIER_WEIGHT = {"T1": 3.0, "T2": 2.0, "T3": 1.2, "T4": 1.0}


def _rank(signal: dict) -> float:
    return (KIND_PRIORITY.get(signal["kind"], 1)
            * TIER_WEIGHT.get(signal["tier"], 1.0)
            * (1.0 + signal.get("salience", 1.0)))


def run_market_signals(persist: bool = True) -> list[dict]:
    """跑一轮行情异动扫描，返回可直接进 pipeline 的 item 列表。

    persist=False 时不写状态（干跑/调参用），这样可以反复执行看到相同结果。
    """
    started = time.time()
    state = SignalState()

    try:
        rows = fetch_spot_tickers()
    except Exception as e:
        logger.error(f"market_signals: spot tickers unavailable, aborting round: {e}")
        return []

    spot_by_symbol = {r["symbol"]: r for r in rows}

    # 需要日线的标的：主流币（周期极值）∪ 成交额前 80（放量）∪ 已触发大幅涨跌的
    # 币。去重后一般 90~110 个左右。
    wanted = {r["symbol"] for r in rows if r["base"] in MAJOR_BASES}
    wanted |= {r["symbol"] for r in rows[:80]}
    wanted |= {r["symbol"] for r in rows
               if abs(r["change_pct"]) >= PRICE_MOVE_THRESHOLDS[tier_of(r)]}
    klines = fetch_daily_klines(sorted(wanted))

    # 合约上下文：优先 OKX（funding + OI 分开拉，liquidation 只对主流币拉），
    # 三者若都失败再整体退到 Hyperliquid。
    funding: dict[str, float] = {}
    oi: dict[str, float] = {}
    liq: dict[str, dict] = {}
    provider = "OKX"
    try:
        oi = fetch_okx_open_interest()
        funding_universe = sorted(set(MAJOR_BASES) |
                                  {r["base"] for r in rows[:FUNDING_UNIVERSE_TOP_N]})
        funding = fetch_okx_funding_rates(funding_universe)
        liq = fetch_okx_liquidations(MAJOR_BASES)
        if not oi and not funding:
            raise RuntimeError("OKX returned empty for both funding and OI")
        logger.info(f"market_signals: OKX perp context — funding {len(funding)}, "
                    f"OI {len(oi)}, liquidation checked {len(liq)} majors")
    except Exception as e:
        logger.warning(f"market_signals: OKX perp context failed ({e}), "
                       f"falling back to Hyperliquid (no liquidation data available there)")
        hl = fetch_hyperliquid_context()
        funding = {b: v["funding_apr"] for b, v in hl.items()}
        oi = {b: v["oi_usd"] for b, v in hl.items()}
        liq = {}
        provider = "Hyperliquid"

    signals: list[dict] = []
    signals += detect_price_moves(rows, state)
    signals += detect_level_breaks(rows, klines, state)
    signals += detect_volume_spikes(rows, klines, state)
    if funding:
        signals += detect_funding_extremes(funding, provider, oi, spot_by_symbol, state)
    if oi:
        signals += detect_oi_jumps(oi, provider, spot_by_symbol, state)
    if liq:
        signals += detect_liquidations(liq, spot_by_symbol, state)

    raw_count = len(signals)
    by_kind_raw: dict[str, int] = {}
    for s in signals:
        by_kind_raw[s["kind"]] = by_kind_raw.get(s["kind"], 0) + 1

    # ── 限流 1：同一个币最多 MAX_SIGNALS_PER_SYMBOL 条 ──
    signals.sort(key=_rank, reverse=True)
    per_symbol: dict[str, int] = {}
    kept = []
    for s in signals:
        n = per_symbol.get(s["symbol"], 0)
        if n >= MAX_SIGNALS_PER_SYMBOL:
            continue
        per_symbol[s["symbol"]] = n + 1
        kept.append(s)

    # ── 限流 2：全轮总量上限 ──
    dropped_by_cap = max(0, len(kept) - MAX_SIGNALS_PER_RUN)
    kept = kept[:MAX_SIGNALS_PER_RUN]

    # 只有真正发出去的信号才记进冷却表；被限流砍掉的不记，否则它们会白白占用
    # 一个冷却期却从没出现在结果里。
    for s in kept:
        state.mark_magnitude(s["key"], s["magnitude"])
    for symbol, row in spot_by_symbol.items():
        state.record_price(symbol, row["last"])
    if persist:
        state.save()

    by_kind = {}
    for s in kept:
        by_kind[s["kind"]] = by_kind.get(s["kind"], 0) + 1
    logger.info(
        f"market_signals: {len(kept)} signals emitted in "
        f"{time.time() - started:.1f}s "
        f"(detected {raw_count} {by_kind_raw}, kept {by_kind}, "
        f"{dropped_by_cap} dropped by run cap)"
    )
    return [s["item"] for s in kept]


# ══════════════════════════════════════════════════════════════════════
# CLI：python -m crawler.market_signals [--dry-run]
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    dry = "--dry-run" in sys.argv
    items = run_market_signals(persist=not dry)
    print(f"\n=== {len(items)} market signal items "
          f"({'dry-run, state NOT persisted' if dry else 'state persisted'}) ===\n")
    for i, it in enumerate(items, 1):
        print(f"{i:>2}. [{it['signal_type']:<15}] auth={it['authority']} {it['title']}")
    if "--json" in sys.argv:
        print("\n" + json.dumps(items, ensure_ascii=False, indent=2))
