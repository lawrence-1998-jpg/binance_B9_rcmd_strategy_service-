"""
真实新闻验证 v1.0 —— 防谣言 / 防伪造 / 防单源误报。

背景：接入 x_search（X 全网关键词搜索，作者是随机陌生账号）与 web_search
（Google News + ddgs，域名五花八门）之后，"信源全部人工挑选"这个前提没了。
在此之前，可信度把关完全依赖 pipeline.SYSTEM_PROMPT 里 LLM 自己给的
is_rumor / credibility_score —— 那是**单条、主观、无外部证据**的判断，对
"写得像真的假新闻"天然无效。

本模块提供的是**客观信号**：谁说的、几家独立机构说的、有没有人说了反话、
时间对不对得上。全部用普通代码 + 已有数据算，**不新增任何 LLM 调用**，
embedding 直接复用 dedup 已经算好并存库的 256 维向量。单轮成本 = 0 美元。

五个信号（权重见 compute_verification）：
    V-1  多源交叉验证    几家**独立机构**报道了同一事件（最强客观证据）
    V-2  信源可信度分层  官方 > 头部媒体 > 中文头部加密媒体 > 聚合站 > 陌生账号
    V-3  单源孤证识别    只有一个低可信度来源 → 不予验证，无视 LLM 觉得它像真的
    V-4  矛盾检测        库里已有语义相似但结论相反的事件 → DISPUTED
    V-5  时间一致性      未来时间戳 / 陈年旧闻冒充快讯 / 事件日与发布日打架

输出四档 verification_status：
    VERIFIED    多家独立可信机构交叉证实，或官方一手信源
    PROBABLE    可信来源单独报道，无矛盾，时间自洽
    UNVERIFIED  孤证且来源可信度低 —— 前端应降权或加"未经证实"标
    DISPUTED    检测到相反结论的事件 —— 前端应加"存在争议"标

「独立」的口径（这是 V-1 的关键，也是最容易做错的地方）：
按**机构**去重，不是按 feed 去重。BlockBeats快讯 / BlockBeats文章 /
X/BlockBeatsAsia / theblockbeats.info 是同一个机构的四个出口，只算一个独立源。
storage.py 现有的 source_count 用 name.split("/")[0] 去重，只能挡住 "X/xxx"
前缀那一类，挡不住上面这种；本模块用显式机构别名表重算。
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import numpy as np

from .dedup import blob_to_embedding, parse_dt
from .timeutil import now_local

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# V-2  信源可信度分层
# ══════════════════════════════════════════════════════════════════════

TIER_OFFICIAL    = "official"      # 一手官方：监管机构、交易所公告、项目方官宣
TIER_TOP         = "top_media"     # 国际头部通讯社 / 头部加密媒体
TIER_ESTABLISHED = "established"   # 有编辑部的加密媒体、知名安全/链上数据机构
TIER_SECONDARY   = "secondary"     # 聚合站、转载站、UGC、二线财经站
TIER_UNKNOWN     = "unknown"       # web_search 捞回来的没见过的长尾域名
TIER_ANON        = "anonymous"     # x_search 捞回来的陌生个人账号

# 权重即"这个来源单独说一句话值多少可信度"。
# 分档依据：官方=1.0 是因为它是事件本身的当事人（SEC 的执法公告不需要第三方
# 佐证）；0.85/0.70 之间的差距对应"国际通讯社级事实核查流程" vs "加密垂直媒体
# 快讯流程"；0.45 给转载站是因为它们的内容基本是别人的，不构成独立证据；
# 0.25/0.15 是新召回源的默认档 —— 陌生账号比陌生域名更低，因为注册一个 X 账号
# 发一条假消息的成本几乎为零。
TIER_WEIGHT = {
    TIER_OFFICIAL:    1.00,
    TIER_TOP:         0.85,
    TIER_ESTABLISHED: 0.70,
    TIER_SECONDARY:   0.45,
    TIER_UNKNOWN:     0.25,
    TIER_ANON:        0.15,
}

# 能算作"独立交叉验证一票"的最低权重。低于此的来源仍会记进 source 列表，
# 但不计入 n_credible —— 两个陌生 X 账号互相"印证"不构成交叉验证。
CREDIBLE_FLOOR = 0.45

# 转载型信源：内容以搬运其它媒体为主，作为交叉验证证据要打折。
# 两家聚合站同时转载同一条 BlockBeats 快讯，不等于两家独立机构证实了它。
_REPOSTERS = {"followin", "binance_square", "coinmarketcal", "yahoo", "litefinance"}
REPOST_DISCOUNT = 0.5


# 机构表：(机构 id, 默认档位, 站内名称别名, 域名, X 账号)
#
# 名称别名取自库里真实出现过的 source_names（2026-07-25 全量 56 个），域名取自
# web_search._TIER_3/4/5 与实测样本。同一机构的多个出口必须写在同一行 —— 这正是
# V-1「独立」口径落地的地方。
_INSTITUTIONS: list[tuple[str, str, list[str], list[str], list[str]]] = [
    # ── 官方一手信源 ────────────────────────────────────────────────
    # 注意别名里**不放**裸机构名（"SEC" / "Binance"）：web_search 的 source
    # 字段是 Google News 打印的发布方名，"Binance" 可能是官方公告，也可能是
    # 一条币安广场用户帖。裸名只能定位机构，不能定档为官方，见 _NAME_TIER_OVERRIDE。
    ("sec",        TIER_OFFICIAL, [], ["sec.gov"], ["secgov"]),
    ("us_gov",     TIER_OFFICIAL, [], [
        "whitehouse.gov", "treasury.gov", "justice.gov", "federalreserve.gov",
        "cftc.gov", "congress.gov", "irs.gov", "fincen.gov"], []),
    ("intl_reg",   TIER_OFFICIAL, [], [
        "europa.eu", "esma.europa.eu", "fca.org.uk", "mas.gov.sg",
        "sfc.hk", "fsa.go.jp"], []),
    # 币安自家出口全部归一个机构：官方公告 / 主号 / 中文号 / 高管 / 研究院之间
    # 没有独立性可言。BinanceSquare 是 UGC，单列（见下）。
    ("binance",    TIER_OFFICIAL, ["币安上币公告", "Binance", "币安"], ["binance.com"],
     ["binance", "binancezh", "cz_binance", "heyibinance", "binanceresearch"]),

    # ── 国际头部 / 头部加密媒体 ─────────────────────────────────────
    ("reuters",    TIER_TOP, ["Reuters"], ["reuters.com"], ["reuters"]),
    ("bloomberg",  TIER_TOP, ["Bloomberg"], ["bloomberg.com"], ["business"]),
    ("wsj",        TIER_TOP, ["WSJ"], ["wsj.com"], []),
    ("ft",         TIER_TOP, ["FT"], ["ft.com"], []),
    ("ap",         TIER_TOP, ["AP"], ["apnews.com"], []),
    ("coindesk",   TIER_TOP, ["CoinDesk", "CoinDesk-Policy"], ["coindesk.com"], ["coindesk"]),
    ("theblock",   TIER_TOP, ["TheBlock"], ["theblock.co"], ["theblock__"]),

    # ── 有编辑部的加密媒体 ──────────────────────────────────────────
    ("cointelegraph", TIER_ESTABLISHED, ["Cointelegraph"], ["cointelegraph.com"], ["cointelegraph"]),
    ("decrypt",       TIER_ESTABLISHED, ["Decrypt"], ["decrypt.co"], ["decryptmedia"]),
    ("blockworks",    TIER_ESTABLISHED, ["Blockworks"], ["blockworks.co"], ["blockworks_"]),
    ("thedefiant",    TIER_ESTABLISHED, ["TheDefiant"], ["thedefiant.io"], ["defiantnews"]),
    ("cnbc",          TIER_ESTABLISHED, ["CNBC-Finance", "CNBC"], ["cnbc.com"], ["cnbc"]),
    ("wublockchain",  TIER_ESTABLISHED, ["吴说区块链", "吴说"], ["wublock123.com"],
     ["wublockchain", "wublockchain12"]),
    ("blockbeats",    TIER_ESTABLISHED, ["BlockBeats快讯", "BlockBeats文章", "BlockBeats", "律动"],
     ["theblockbeats.info"], ["blockbeatsasia"]),
    ("panews",        TIER_ESTABLISHED, ["PANews"], ["panewslab.com"], ["panewscn"]),
    ("chaincatcher",  TIER_ESTABLISHED, ["ChainCatcher", "链捕手"], ["chaincatcher.com"], ["chaincatcher"]),
    ("techflow",      TIER_ESTABLISHED, ["TechFlow深潮", "深潮"], ["techflowpost.com"], ["techflowpost"]),
    ("jinse",         TIER_ESTABLISHED, ["金色财经"], ["jinse.com", "jinse.com.cn"], ["jinsecaijing"]),
    ("odaily",        TIER_ESTABLISHED, ["Odaily", "星球日报"], ["odaily.news"], ["odailychina"]),
    ("foresight",     TIER_ESTABLISHED, ["ForesightNews"], ["foresightnews.pro"], ["foresight_news"]),
    ("messari",       TIER_ESTABLISHED, ["Messari"], ["messari.io"], ["messaricrypto"]),
    ("theinformation", TIER_ESTABLISHED, [], ["theinformation.com"], []),

    # ── 安全 / 链上数据机构（对各自领域是一手取证方）────────────────
    ("peckshield",  TIER_ESTABLISHED, ["PeckShield"], ["peckshield.com"], ["peckshield"]),
    ("slowmist",    TIER_ESTABLISHED, ["SlowMist", "慢雾"], ["slowmist.com"], ["slowmist_team"]),
    ("certik",      TIER_ESTABLISHED, ["CertiK"], ["certik.com"], ["certikalert", "certik"]),
    ("lookonchain", TIER_ESTABLISHED, ["Lookonchain"], ["lookonchain.com"], ["lookonchain"]),
    ("spotonchain", TIER_ESTABLISHED, [], ["spotonchain.ai"], ["spotonchain"]),
    ("glassnode",   TIER_ESTABLISHED, ["Glassnode"], ["glassnode.com"], ["glassnode"]),
    ("defillama",   TIER_ESTABLISHED, ["DefiLlama"], ["defillama.com"], ["defillama"]),
    ("whale_alert", TIER_ESTABLISHED, [], ["whale-alert.io"], ["whale_alert"]),
    ("embercn",     TIER_ESTABLISHED, [], [], ["embercn"]),
    ("ai9684",      TIER_ESTABLISHED, [], [], ["ai_9684xtpa"]),
    ("bwenews",     TIER_ESTABLISHED, ["BWEnews"], [], ["bwenews"]),
    ("tree_of_alpha", TIER_ESTABLISHED, [], [], ["tree_of_alpha"]),

    # ── 聚合站 / 转载站 / UGC / 二线财经 ────────────────────────────
    # BinanceSquare 是用户生成内容，和 binance 官方公告不是一个东西，
    # 必须单列，否则一条广场帖会被当成币安官宣。
    ("binance_square", TIER_SECONDARY, ["BinanceSquare", "币安广场"], [], []),
    ("followin",       TIER_SECONDARY, ["Followin快讯", "Followin-EN", "Followin"],
     ["followin.io"], ["followin_official"]),
    ("coinmarketcal",  TIER_SECONDARY, ["CoinMarketCal"], ["coinmarketcal.com"], []),
    ("yahoo",          TIER_SECONDARY, ["YahooFinance", "Yahoo Finance"],
     ["finance.yahoo.com", "yahoo.com"], []),
    ("watcherguru",    TIER_SECONDARY, [], ["watcher.guru"], ["watcherguru"]),
    ("solidintel",     TIER_SECONDARY, [], [], ["solidintel_x"]),
    ("kobeissi",       TIER_SECONDARY, [], [], ["kobeissiletter"]),
    ("unusual_whales", TIER_SECONDARY, [], ["unusualwhales.com"], ["unusual_whales"]),
    ("onchainlens",    TIER_SECONDARY, [], [], ["onchainlens"]),
    ("santiment",      TIER_SECONDARY, [], ["santiment.net"], ["santimentfeed"]),
    ("benzinga",       TIER_SECONDARY, [], ["benzinga.com"], []),
    ("investing",      TIER_SECONDARY, [], ["investing.com"], []),
    ("nasdaq",         TIER_SECONDARY, [], ["nasdaq.com"], []),
    ("marketwatch",    TIER_SECONDARY, [], ["marketwatch.com"], []),
    ("seekingalpha",   TIER_SECONDARY, [], ["seekingalpha.com"], []),
    ("barrons",        TIER_SECONDARY, [], ["barrons.com"], []),
    ("businessinsider", TIER_SECONDARY, [], ["businessinsider.com"], []),
    ("forbes",         TIER_SECONDARY, [], ["forbes.com"], []),
    ("techcrunch",     TIER_SECONDARY, [], ["techcrunch.com"], []),
    ("utoday",         TIER_SECONDARY, [], ["u.today"], []),
    ("dailyhodl",      TIER_SECONDARY, [], ["dailyhodl.com"], []),
    ("ambcrypto",      TIER_SECONDARY, [], ["ambcrypto.com"], []),
    ("cryptoslate",    TIER_SECONDARY, [], ["cryptoslate.com"], []),
    ("cryptorank",     TIER_SECONDARY, [], ["cryptorank.io"], []),
    ("fxstreet",       TIER_SECONDARY, [], ["fxstreet.com"], []),
    ("thestreet",      TIER_SECONDARY, [], ["thestreet.com"], []),
    ("financemagnates", TIER_SECONDARY, [], ["financemagnates.com"], []),
    ("coincu",         TIER_SECONDARY, [], ["coincu.com"], []),
    ("litefinance",    TIER_SECONDARY, ["LiteFinance"], ["litefinance.org"], []),
]

# ── 由上表编译出的查表结构（导入时构建一次）─────────────────────────
_NAME_TO_INST: dict[str, str] = {}
_DOMAIN_TO_INST: dict[str, str] = {}
_X_TO_INST: dict[str, str] = {}
_INST_TIER: dict[str, str] = {}

for _inst, _tier, _names, _domains, _xs in _INSTITUTIONS:
    _INST_TIER[_inst] = _tier
    for _n in _names:
        _NAME_TO_INST[_n.strip().lower()] = _inst
    for _d in _domains:
        _DOMAIN_TO_INST[_d.lower()] = _inst
    for _x in _xs:
        _X_TO_INST[_x.lower()] = _inst

# 名称级档位覆盖：机构归属不变（保证独立性判定正确），但档位单独给。
# 高管个人推文是可信的一手信息，却不等同于机构官方公告 —— 归 binance 机构
# （不与官方公告互相佐证），档位降到 TOP。
_NAME_TIER_OVERRIDE = {
    "x/cz_binance":     TIER_TOP,
    "x/heyibinance":    TIER_TOP,
    "x/binanceresearch": TIER_ESTABLISHED,
    # 裸 "Binance"：机构归属仍是 binance（不与官方公告互相佐证），但档位只给
    # SECONDARY。实测踩到过——一条币安广场 UGC 帖经 Google News 回来，source
    # 字段就是 "Binance"，第一版把它当成官宣直接判了 VERIFIED。
    "binance":          TIER_SECONDARY,
    "币安":              TIER_SECONDARY,
}

# 同域名下的 UGC 板块。币安广场的帖子和币安官方公告同在 binance.com，
# 靠域名区分不开，必须看路径。
_UGC_URL_RE = re.compile(r"binance\.com/[^/]*/?square", re.IGNORECASE)


def _domain_of(url: str) -> str:
    """从 URL 取主域名（去 www./端口）。解析失败返回空串。"""
    if not url:
        return ""
    match = re.match(r"^[a-z]+://([^/:?#]+)", url.strip(), re.IGNORECASE)
    if not match:
        return ""
    host = match.group(1).lower()
    return host[4:] if host.startswith("www.") else host


def _domain_institution(domain: str) -> str | None:
    """域名 → 机构。支持子域名回退（news.coindesk.com → coindesk.com）。"""
    if not domain:
        return None
    if domain in _DOMAIN_TO_INST:
        return _DOMAIN_TO_INST[domain]
    parts = domain.split(".")
    for i in range(1, len(parts) - 1):
        parent = ".".join(parts[i:])
        if parent in _DOMAIN_TO_INST:
            return _DOMAIN_TO_INST[parent]
    return None


def resolve_source(source: dict) -> tuple[str, str, float]:
    """单个信源 → (机构 id, 档位, 权重)。

    解析顺序：站内名称 → X 账号名 → URL 域名 → 按 type 兜底。
    名称优先于域名是有意的：BinanceSquare 的 URL 也在 binance.com 下，
    走域名会被误判成币安官方公告。

    >>> resolve_source({"name": "BlockBeats快讯", "type": "rss"})[0]
    'blockbeats'
    >>> resolve_source({"name": "X/somerandomguy", "type": "x"})[1]
    'anonymous'
    """
    name = (source.get("name") or "").strip()
    lower = name.lower()
    url = source.get("url") or ""
    stype = source.get("type") or "rss"

    # UGC 路径优先于一切：币安广场帖子不是币安官宣
    if _UGC_URL_RE.search(url):
        return "binance_square", TIER_SECONDARY, TIER_WEIGHT[TIER_SECONDARY]

    inst = _NAME_TO_INST.get(lower)

    if inst is None and lower.startswith("x/"):
        username = lower[2:].split("/")[0].strip()
        inst = _X_TO_INST.get(username)
        if inst is None:
            # x_search 捞回来的陌生账号：机构 id 就是账号本身（两条同账号推文
            # 不构成交叉验证），档位一律 ANON。
            return (f"x:{username}" if username else "x:unknown"), TIER_ANON, TIER_WEIGHT[TIER_ANON]

    if inst is None:
        inst = _domain_institution(_domain_of(url))

    if inst is not None:
        tier = _NAME_TIER_OVERRIDE.get(lower) or _INST_TIER.get(inst, TIER_SECONDARY)
        return inst, tier, TIER_WEIGHT[tier]

    # 完全没见过：web_search 长尾域名给 UNKNOWN，其余（rss/scraper 白名单外）
    # 给 SECONDARY —— 后者是我们自己配的源，至少经过一次人工挑选。
    domain = _domain_of(url)
    fallback_inst = f"web:{domain}" if domain else f"name:{lower or 'unknown'}"
    tier = TIER_UNKNOWN if stype in ("web_search", "search") else TIER_SECONDARY
    return fallback_inst, tier, TIER_WEIGHT[tier]


# ══════════════════════════════════════════════════════════════════════
# V-1  多源交叉验证
# ══════════════════════════════════════════════════════════════════════

# S_corr 的归一化分母。1.2 的含义：除最强源之外，再有 1.2 个权重单位的独立
# 佐证就把交叉验证项打满。即"两家头部媒体(0.85+)"或"两家中文加密媒体
# (0.70×2=1.4)"即可满分，符合行业里"双源确认即可发稿"的惯例。
CORROBORATION_SATURATION = 1.2


def event_sources(event: dict) -> list[dict]:
    """取事件的完整信源列表 = sources ∪ source_names。

    为什么要并：库里 `sources`（带 url）和 `source_names`（只有名字）会不一致。
    storage._INSERT_EVENT_SQL 的 ON DUPLICATE KEY UPDATE 里 sources 走
    `VALUES(sources)`（只有本轮的），source_names 走并集；backfill_dedup 也只
    合并了 source_names。实测 508 行里 59 行两者长度不同，只读 sources 会把
    3 家报道的事件误判成孤证。以 sources 为主（有 url 可判域名），
    source_names 里多出来的名字补进来。
    """
    sources = list(event.get("sources") or [])
    known = {(s.get("name") or "").strip() for s in sources}
    for name in event.get("source_names") or []:
        name = (name or "").strip()
        if name and name not in known:
            known.add(name)
            sources.append({"name": name, "url": "", "type": "rss"})
    return sources


def analyze_sources(sources: list[dict]) -> dict:
    """把 sources 列表压成机构级证据画像。

    返回 institutions（机构 id → 最高权重）、best_weight（最强单源权重）、
    corroboration（除最强源外的独立佐证强度，0~1）、n_credible（可信独立机构数）。
    """
    by_inst: dict[str, float] = {}
    tiers: dict[str, str] = {}
    for src in sources or []:
        inst, tier, weight = resolve_source(src)
        if weight > by_inst.get(inst, -1.0):
            by_inst[inst] = weight
            tiers[inst] = tier

    if not by_inst:
        return {"institutions": {}, "tiers": {}, "best_weight": 0.0, "best_inst": "",
                "corroboration": 0.0, "n_institutions": 0, "n_credible": 0,
                "has_official": False}

    best_inst = max(by_inst, key=lambda k: by_inst[k])
    best_weight = by_inst[best_inst]

    support = sum(
        w * (REPOST_DISCOUNT if inst in _REPOSTERS else 1.0)
        for inst, w in by_inst.items() if inst != best_inst
    )

    return {
        "institutions": by_inst,
        "tiers": tiers,
        "best_inst": best_inst,
        "best_weight": best_weight,
        "corroboration": min(1.0, support / CORROBORATION_SATURATION),
        "n_institutions": len(by_inst),
        "n_credible": sum(1 for w in by_inst.values() if w >= CREDIBLE_FLOOR),
        "has_official": any(tiers[i] == TIER_OFFICIAL for i in by_inst),
    }


# ══════════════════════════════════════════════════════════════════════
# V-5  时间一致性
# ══════════════════════════════════════════════════════════════════════

# 发布时间比"现在"还晚多少小时算异常。留 6h 余量吸收信源时区/时钟漂移；
# 日历源（CoinMarketCal）本来就登记未来事件，单独豁免。
FUTURE_TOLERANCE_HOURS = 6
STALE_DAYS = 30            # 发布时间早于今天这么多天 → 陈年旧闻
BREAKING_MAX_AGE_HOURS = 48  # 自称快讯/BREAKING 却超过这个年龄 → 冷饭重炒
DATE_MISMATCH_DAYS = 7     # LLM 抽出的事件日与发布日差这么多天 → 存疑

_BREAKING_RE = re.compile(
    r"\bbreaking\b|\bjust in\b|\bmoments ago\b|\bminutes ago\b|"
    r"快讯|突发|刚刚|最新消息|重磅",
    re.IGNORECASE,
)


def check_time_consistency(event: dict, now: datetime) -> tuple[float, list[str]]:
    """时间自洽性打分 0~1 + 异常码列表。

    这一项抓的是"内容本身的时间线说不通"，和内容真假独立 —— 一条 2024 年的
    旧闻在 2026 年被当成新料推给用户，即使当年是真的，此刻也是误导。
    """
    flags: list[str] = []
    published = parse_dt(event.get("published_at"))
    # 日历源（CoinMarketCal）整体豁免时间校验：它登记的是**未来**的既定日程
    # （硬分叉、解锁、活动结束日），published_at 是条目录入时间而非新闻时间。
    # 实测里 4 条 CoinMarketCal 被 TIME_STALE 误标，就是这个原因——一个月前
    # 录入的 7 月 29 日硬分叉日程，既不是旧闻也不是造假。
    is_calendar = any((s.get("type") == "calendar") for s in (event.get("sources") or []))
    if is_calendar:
        return 1.0, []

    if published is None:
        # 解析不出时间不等于造假，给中性偏低分，不单独定罪。
        return 0.6, ["TIME_UNPARSEABLE"]

    score = 1.0
    ahead_hours = (published - now).total_seconds() / 3600
    if ahead_hours > FUTURE_TOLERANCE_HOURS:
        # 发布时间在未来 = 时间戳被伪造或信源时钟错乱，是硬信号
        flags.append("TIME_FUTURE_PUBLISH")
        score = 0.0

    age_days = (now - published).total_seconds() / 86400
    if age_days > STALE_DAYS:
        flags.append("TIME_STALE")
        score = min(score, 0.4)

    text = f"{event.get('title_zh', '')} {event.get('title_en', '')} {event.get('description_short_zh', '')}"
    if _BREAKING_RE.search(text) and age_days * 24 > BREAKING_MAX_AGE_HOURS:
        flags.append("TIME_RECYCLED_BREAKING")
        score = min(score, 0.3)

    event_date = parse_dt((event.get("event_date") or "")[:10] or None)
    if event_date is not None:
        gap_days = abs((event_date - published).total_seconds()) / 86400
        if gap_days > DATE_MISMATCH_DAYS:
            flags.append("TIME_DATE_MISMATCH")
            score = min(score, 0.5)

    return score, flags


# ══════════════════════════════════════════════════════════════════════
# V-4  矛盾检测
# ══════════════════════════════════════════════════════════════════════

# C-1 语义层：cosine 阈值刻意低于 dedup.COSINE_THRESHOLD(0.82)。
# 0.82 以上会被去重层直接合并成同一事件，根本走不到这里；矛盾对天生落在
# "同一话题但结论不同"的区间，实测在 0.70~0.80。下限 0.70 以下开始混入
# 只是同主题的无关新闻。
CONTRADICTION_COSINE = 0.70
CONTRADICTION_WINDOW_HOURS = 96   # 辟谣通常在原始传闻后 1~3 天内出现

# 说"没这回事"的措辞。
#
# 词表经过一轮实测收紧（2026-07-26，508 条真实数据）。第一版放得宽，6 个矛盾
# 全是误报，教训有两条：
#   1. "并未""未曾""no plans" 这类否定副词在正常报道里到处都是
#      （"该消息聚焦AI监管，并未直接涉及加密资产"），必须删掉。
#   2. 光秃秃的 denied/denies 会命中"申请被驳回"这种业务动作
#      （"the OCC denied Wise's charter application"）—— 那是事件本身，
#      不是对传闻的否认。denies 类动词一律要求后面跟"报道/传闻/指控"类宾语。
# 只保留高特异度、且指向"对某个说法的否认"的表达。
_DENIAL_RE = re.compile(
    r"\b(?:denies|denied|denying|refutes?|refuted|rebuts?|debunks?|debunked|"
    r"dismisses|dismissed|disputes?|disputed)\b[^.。;；]{0,40}?\b"
    r"(?:report|reports|reporting|rumou?r|rumou?rs|claim|claims|allegation|"
    r"allegations|speculation|story|hack|breach|insolvency|bankruptcy)\b|"
    r"\bunfounded\b|\buntrue\b|\bhoax\b|\bfake news\b|\bmisinformation\b|"
    r"\bno evidence\b|\bnot true\b|\bfalse (?:claim|report|rumou?r|allegation)\b|"
    r"\bsets? the record straight\b|\bno truth to\b|"
    r"\bcalls? (?:the )?(?:report|claim|rumou?r)s? false\b|"
    r"否认|辟谣|系谣言|为谣言|纯属谣言|不属实|消息不实|报道不实|传闻不实|"
    r"传言不实|虚假消息|假消息|无稽之谈|予以否认|回应传闻|并无此事|查无此事|"
    r"(?:官方|发文|发布|回应|公告)澄清|澄清称|不存在(?:被盗|漏洞|此事|该情况)",
    re.IGNORECASE,
)

# C-2 结构层：同主体 + 相近日期，动作互为反义 → 直接判矛盾。
# 依赖 pipeline SYSTEM_PROMPT 里那套受控动作词表，纯字符串比对，零成本且极准。
_ANTONYM_ACTIONS = [
    ("net_inflow", "net_outflow"),
    ("price_surge", "price_drop"),
    ("listed", "delisted"),
    ("approved", "rejected"),
    ("approved", "banned"),
    ("launched", "shutdown"),
]
_ANTONYM_MAP: dict[str, set[str]] = {}
for _a, _b in _ANTONYM_ACTIONS:
    _ANTONYM_MAP.setdefault(_a, set()).add(_b)
    _ANTONYM_MAP.setdefault(_b, set()).add(_a)

ANTONYM_DATE_TOLERANCE_DAYS = 2


def _denial_text(event: dict) -> str:
    """辟谣措辞只在**标题**里找。

    这是第一版误报的根因修复：正常报道的正文里出现一句否定表述太常见了
    （"能源价格走高并未引发加密市场避险抛售"），而真正的辟谣事件一定把
    "否认/denies the report" 写进标题——那就是这条新闻本身。以精度换召回是
    有意的：把路透社的报道错标成"存在争议"，比漏掉一条辟谣代价大得多。
    """
    return f"{event.get('title_zh', '') or ''} {event.get('title_en', '') or ''}"


def _is_denial(event: dict) -> bool:
    return bool(_DENIAL_RE.search(_denial_text(event)))


def _embedding_matrix(events: list[dict]) -> tuple[np.ndarray, list[int]]:
    """把有向量的事件堆成归一化矩阵，返回 (矩阵, 原下标映射)。"""
    idx = [i for i, e in enumerate(events) if e.get("embedding") is not None]
    if not idx:
        return np.zeros((0, 0), dtype=np.float32), []
    matrix = np.stack([np.asarray(events[i]["embedding"], dtype=np.float32) for i in idx])
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-9), idx


def detect_contradictions(events: list[dict],
                          reference: list[dict] | None = None) -> dict[int, list[dict]]:
    """检测矛盾对，返回 {events 下标: [矛盾对手描述, ...]}。

    比对范围是 events 内部两两 + events × reference（reference 是库里近期事件，
    由 load_reference_events 提供）。向量全部复用已算好的 embedding，**不新增
    任何 embedding 调用**。

    两条检测通道：
      C-1  语义相近(cosine>=0.70) + 时间窗内 + 恰好一方带辟谣措辞
      C-2  同 event_subject + 日期相近 + event_action 互为反义

    只有"被否认的一方"会被标 DISPUTED；辟谣方本身不降级（它往往是更可信的
    那条）。且辟谣方权重必须达到 CREDIBLE_FLOOR —— 一个陌生账号喊"假的"
    不足以把路透社的报道打成争议。
    """
    reference = reference or []
    disputes: dict[int, list[dict]] = {}

    pool = list(events) + list(reference)
    origin = [("new", i) for i in range(len(events))] + \
             [("ref", i) for i in range(len(reference))]

    denial_flags = [_is_denial(e) for e in pool]
    weights = [analyze_sources(event_sources(e)).get("best_weight", 0.0) for e in pool]

    def _record(pos: int, other_pos: int, mode: str) -> None:
        kind, index = origin[pos]
        if kind != "new":
            return          # 只给本轮事件打标；库里旧行由它自己那轮负责
        other = pool[other_pos]
        disputes.setdefault(index, []).append({
            "mode": mode,
            "event_id": other.get("id", ""),
            "title": other.get("title_zh") or other.get("title_en", ""),
            "source": ", ".join(other.get("source_names", []) or [])[:120],
        })

    # ── C-1 语义 + 辟谣措辞 ─────────────────────────────────────────
    matrix, idx = _embedding_matrix(pool)
    if len(idx) > 1:
        sim = matrix @ matrix.T
        rows, cols = np.where(np.triu(sim, k=1) >= CONTRADICTION_COSINE)
        for r, c in zip(rows.tolist(), cols.tolist()):
            pa, pb = idx[r], idx[c]
            if origin[pa][0] == "ref" and origin[pb][0] == "ref":
                continue
            if denial_flags[pa] == denial_flags[pb]:
                continue    # 两条都在辟谣 / 两条都在陈述 → 不是矛盾对
            hours = _hours_apart(pool[pa].get("published_at"), pool[pb].get("published_at"))
            if hours > CONTRADICTION_WINDOW_HOURS:
                continue
            claim, denier = (pa, pb) if denial_flags[pb] else (pb, pa)
            if weights[denier] < CREDIBLE_FLOOR:
                continue
            _record(claim, denier, "DENIAL")

    # ── C-2 同主体反义动作 ──────────────────────────────────────────
    by_subject: dict[str, list[int]] = {}
    for pos, item in enumerate(pool):
        subject = (item.get("event_subject") or "").strip().lower()
        if subject:
            by_subject.setdefault(subject, []).append(pos)

    for positions in by_subject.values():
        if len(positions) < 2:
            continue
        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                pa, pb = positions[i], positions[j]
                if origin[pa][0] == "ref" and origin[pb][0] == "ref":
                    continue
                act_a = (pool[pa].get("event_action") or "").strip().lower()
                act_b = (pool[pb].get("event_action") or "").strip().lower()
                if act_b not in _ANTONYM_MAP.get(act_a, ()):
                    continue
                if _days_apart(pool[pa].get("event_date"),
                               pool[pb].get("event_date")) > ANTONYM_DATE_TOLERANCE_DAYS:
                    continue
                # 反义动作没有"谁在辟谣"之分，两边都标
                _record(pa, pb, "ANTONYM_ACTION")
                _record(pb, pa, "ANTONYM_ACTION")

    if disputes:
        logger.info(f"Verification: {len(disputes)} events flagged as contradicted")
    return disputes


def _hours_apart(a: str | None, b: str | None) -> float:
    ta, tb = parse_dt(a), parse_dt(b)
    if ta is None or tb is None:
        return 0.0      # 时间缺失不阻断矛盾检测（矛盾比时间窗更重要）
    return abs((ta - tb).total_seconds()) / 3600


def _days_apart(a: str | None, b: str | None) -> float:
    ta, tb = parse_dt((a or "")[:10] or None), parse_dt((b or "")[:10] or None)
    if ta is None or tb is None:
        return 0.0
    return abs((ta - tb).total_seconds()) / 86400


# ══════════════════════════════════════════════════════════════════════
# 合成：verification_score / verification_status
# ══════════════════════════════════════════════════════════════════════

STATUS_VERIFIED   = "VERIFIED"
STATUS_PROBABLE   = "PROBABLE"
STATUS_UNVERIFIED = "UNVERIFIED"
STATUS_DISPUTED   = "DISPUTED"

# 权重：最强单源 0.55 / 独立佐证 0.30 / 时间自洽 0.15。
# 最强源权重最高是因为 92% 的事件在库里只有一个信源（实测 944 条里 868 条
# source_count=1），交叉验证项对它们恒为 0；若把 0.55 那份给交叉验证，
# 单源事件会整体塌到同一档，这个字段对产品就没有区分度了。
W_SOURCE, W_CORROBORATION, W_TIME = 0.55, 0.30, 0.15

# LLM 的 credibility_score 只占 10% —— 它是免费的既有数据（不新增调用），
# 扔掉可惜，但绝不让它主导结论。这正是本模块存在的理由。
W_LLM_PRIOR = 0.10

RUMOR_PENALTY = 0.90       # LLM 判为传闻的轻度扣分
DISPUTED_CAP = 0.35        # 检测到矛盾时的分数上限

VERIFIED_THRESHOLD = 0.70
PROBABLE_THRESHOLD = 0.50
# 多家独立可信机构才够 VERIFIED；单源无论多权威都只能 PROBABLE，
# 唯一例外是官方一手信源（SEC 公告 / 交易所公告本身就是事件）。
VERIFIED_MIN_CREDIBLE_SOURCES = 2
# LLM 说是传闻时，需要这么多家独立可信机构才能压过它升到 VERIFIED
RUMOR_OVERRIDE_SOURCES = 3


def compute_verification(event: dict, now: datetime,
                         contradictions: list[dict] | None = None) -> dict:
    """算单条事件的验证结论。纯本地计算，无网络无 LLM。"""
    profile = analyze_sources(event_sources(event))
    time_score, time_flags = check_time_consistency(event, now)

    objective = (W_SOURCE * profile["best_weight"] +
                 W_CORROBORATION * profile["corroboration"] +
                 W_TIME * time_score)

    llm_prior = _safe_float(event.get("credibility_score"), 0.5)
    score = (1 - W_LLM_PRIOR) * objective + W_LLM_PRIOR * llm_prior

    flags = list(time_flags)
    is_rumor = bool(event.get("is_rumor"))
    if is_rumor:
        score *= RUMOR_PENALTY
        flags.append("LLM_RUMOR")

    if contradictions:
        score = min(score, DISPUTED_CAP)
        flags.append("CONTRADICTED")

    # ── 定档 ────────────────────────────────────────────────────────
    if contradictions:
        status = STATUS_DISPUTED
    elif profile["has_official"] and not time_flags:
        status = STATUS_VERIFIED          # V-2：官方一手信源自证
    elif (profile["n_credible"] >= VERIFIED_MIN_CREDIBLE_SOURCES
          and score >= VERIFIED_THRESHOLD):
        status = STATUS_VERIFIED
    elif score >= PROBABLE_THRESHOLD:
        status = STATUS_PROBABLE
    else:
        status = STATUS_UNVERIFIED

    # V-3 单源孤证硬规则：一个来源、且该来源可信度低于门槛 → 无论 LLM 怎么想
    # 都不给过。这条是为 x_search/web_search 两个新召回源专门设的闸。
    if profile["n_institutions"] <= 1 and profile["best_weight"] < CREDIBLE_FLOOR:
        status = STATUS_DISPUTED if contradictions else STATUS_UNVERIFIED
        flags.append("SINGLE_LOW_TRUST_SOURCE")

    # LLM 判为传闻时，需要 3 家以上独立可信机构（或官方源）才配得上 VERIFIED
    if (is_rumor and status == STATUS_VERIFIED and not profile["has_official"]
            and profile["n_credible"] < RUMOR_OVERRIDE_SOURCES):
        status = STATUS_PROBABLE

    return {
        "verification_status": status,
        "verification_score": round(max(0.0, min(1.0, score)), 4),
        "verification_reason": _build_reason(profile, time_flags, is_rumor,
                                             contradictions, status),
        "verification_flags": flags,
        "independent_source_count": profile["n_institutions"],
        "credible_source_count": profile["n_credible"],
        "_profile": profile,
    }


def _safe_float(value, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


_TIER_LABEL_ZH = {
    TIER_OFFICIAL: "官方一手",
    TIER_TOP: "头部媒体",
    TIER_ESTABLISHED: "主流加密媒体",
    TIER_SECONDARY: "聚合/转载站",
    TIER_UNKNOWN: "陌生站点",
    TIER_ANON: "陌生个人账号",
}

_FLAG_LABEL_ZH = {
    "TIME_FUTURE_PUBLISH": "发布时间在未来",
    "TIME_STALE": f"发布时间超过 {STALE_DAYS} 天",
    "TIME_RECYCLED_BREAKING": "自称快讯但内容陈旧",
    "TIME_DATE_MISMATCH": "事件日期与发布日期不符",
    "TIME_UNPARSEABLE": "发布时间无法解析",
}


def _build_reason(profile: dict, time_flags: list[str], is_rumor: bool,
                  contradictions: list[dict] | None, status: str) -> str:
    """拼出人类可读的判定依据。前端可直接展示，也是人工核对的抓手。"""
    parts = []

    n_inst, n_cred = profile["n_institutions"], profile["n_credible"]
    tier_zh = _TIER_LABEL_ZH.get(profile["tiers"].get(profile["best_inst"], ""), "未知")
    if n_inst == 0:
        parts.append("无可识别信源")
    elif n_inst == 1:
        parts.append(f"单一信源（{profile['best_inst']}，{tier_zh}）")
    else:
        parts.append(f"{n_inst} 家独立机构报道（其中 {n_cred} 家达可信门槛），"
                     f"最高档 {tier_zh}")

    if contradictions:
        modes = {c["mode"] for c in contradictions}
        label = "存在辟谣/否认报道" if "DENIAL" in modes else "存在结论相反的事件"
        titles = "；".join(c["title"][:40] for c in contradictions[:2])
        parts.append(f"{label}：{titles}")

    for flag in time_flags:
        parts.append(_FLAG_LABEL_ZH.get(flag, flag))

    if is_rumor:
        parts.append("LLM 标记为传闻")

    if status == STATUS_UNVERIFIED and n_inst <= 1:
        parts.append("孤证未获交叉验证")

    return "；".join(parts)


# ══════════════════════════════════════════════════════════════════════
# 对外入口
# ══════════════════════════════════════════════════════════════════════

REFERENCE_LOOKBACK_HOURS = 96   # 矛盾检测回溯窗口，覆盖"传闻→辟谣"的典型间隔


def load_reference_events(conn, hours: int = REFERENCE_LOOKBACK_HOURS) -> list[dict]:
    """拉库里近 N 小时事件作为矛盾检测的比对基准。

    只读，不改 storage.py。取的列刻意精简：矛盾检测只需要标题/摘要（辟谣措辞）、
    三元组（反义动作）、向量（语义）和时间。
    """
    since = (now_local() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, title_en, title_zh, description_short_en, description_short_zh,
                  event_subject, event_action, date, time_event, embedding,
                  source_names, sources
           FROM news_events WHERE time_get_data >= %s""",
        (since,),
    )
    rows = cursor.fetchall()
    cursor.close()
    return [_row_to_event(row) for row in rows]


def _row_to_event(row) -> dict:
    (event_id, title_en, title_zh, desc_en, desc_zh, subject, action,
     date_val, time_event, blob, source_names, sources) = row
    return {
        "id": event_id,
        "title_en": title_en or "",
        "title_zh": title_zh or "",
        "description_short_en": desc_en or "",
        "description_short_zh": desc_zh or "",
        "event_subject": subject or "",
        "event_action": action or "",
        "event_date": date_val.isoformat() if date_val else "",
        "published_at": time_event.replace(tzinfo=timezone.utc).isoformat() if time_event else None,
        "embedding": blob_to_embedding(blob),
        "source_names": _load_json(source_names, []),
        "sources": _load_json(sources, []),
    }


def _load_json(raw, default):
    if raw is None:
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def verify_events(events: list[dict], conn=None,
                  now: datetime | None = None,
                  reference: list[dict] | None = None) -> dict:
    """给一批事件做真实性验证，**就地**写入以下字段：

        verification_status        VERIFIED / PROBABLE / UNVERIFIED / DISPUTED
        verification_score         0~1 客观分
        verification_reason        中文可读依据
        verification_flags         异常码列表
        independent_source_count   独立机构数（按机构去重，非按 feed）
        credible_source_count      其中达可信门槛的家数

    成本：0。不调 LLM，不算 embedding，只用 events 里已有的向量和库里已存的
    向量做矩阵乘法。

    `conn` 传入时会自动拉近期事件做跨事件矛盾检测；也可直接传 `reference`
    绕过取数（测试/回填用）。
    """
    if not events:
        return {"total": 0}

    now = now or now_local()
    if reference is None:
        reference = []
        if conn is not None:
            try:
                reference = load_reference_events(conn)
            except Exception as e:
                logger.warning(f"Verification: reference load failed, "
                               f"contradiction detection degraded: {e}")

    # 避免自己和自己比：本轮事件若已在库里（跨轮归并命中），会同时出现在两边
    new_ids = {e.get("id") for e in events if e.get("id")}
    reference = [r for r in reference if r.get("id") not in new_ids]

    contradictions = detect_contradictions(events, reference)

    stats = {"total": len(events), STATUS_VERIFIED: 0, STATUS_PROBABLE: 0,
             STATUS_UNVERIFIED: 0, STATUS_DISPUTED: 0}
    for index, event in enumerate(events):
        result = compute_verification(event, now, contradictions.get(index))
        result.pop("_profile", None)
        event.update(result)
        stats[result["verification_status"]] += 1

    logger.info(
        "Verification: {total} events → VERIFIED {VERIFIED} / PROBABLE {PROBABLE} / "
        "UNVERIFIED {UNVERIFIED} / DISPUTED {DISPUTED} (0 LLM calls)".format(**stats)
    )
    return stats


_UPDATE_SQL = """
UPDATE news_events
   SET verification_status = %s,
       verification_score  = %s,
       verification_reason = %s,
       verification_flags  = %s,
       independent_source_count = %s
 WHERE id = %s
"""


def persist_verification(events: list[dict], conn) -> int:
    """把验证结果写回 news_events。必须在 storage.write_events 之后调用
    （行要先存在）。返回成功更新的条数。"""
    if not events:
        return 0
    cursor = conn.cursor()
    written = 0
    for event in events:
        if not event.get("verification_status"):
            continue
        try:
            cursor.execute(_UPDATE_SQL, (
                event["verification_status"],
                float(event.get("verification_score", 0.0)),
                (event.get("verification_reason") or "")[:1000],
                json.dumps(event.get("verification_flags", []), ensure_ascii=False),
                int(event.get("independent_source_count", 1) or 1),
                event["id"],
            ))
            written += cursor.rowcount
        except Exception as e:
            logger.warning(f"verification write failed [{event.get('id')}]: {e}")
    conn.commit()
    cursor.close()
    logger.info(f"MySQL: verification written for {written}/{len(events)} events")
    return written


# 供 scoring.py 接入用的建议乘数（本模块不改 scoring.py，由调用方决定是否使用）。
# DISPUTED 打 5 折比现有 is_rumor 的 7 折更狠，因为"有人明确否认"比"措辞像传闻"
# 是强得多的负面证据。
AUTHORITY_MULTIPLIER = {
    STATUS_VERIFIED:   1.00,
    STATUS_PROBABLE:   0.95,
    STATUS_UNVERIFIED: 0.75,
    STATUS_DISPUTED:   0.50,
}


def authority_multiplier(event: dict) -> float:
    """给 scoring.compute_authority 用的可信度乘数。未验证过的事件返回 1.0
    （不惩罚没跑过本模块的历史数据）。"""
    return AUTHORITY_MULTIPLIER.get(event.get("verification_status", ""), 1.0)


# ══════════════════════════════════════════════════════════════════════
# 全库跑批 / 抽样核对（python -m crawler.verification [--persist] [--sample N]）
# ══════════════════════════════════════════════════════════════════════

def _load_all_events(conn, limit: int | None = None) -> list[dict]:
    cursor = conn.cursor()
    sql = """SELECT id, title_en, title_zh, description_short_en, description_short_zh,
                    event_subject, event_action, date, time_event, embedding,
                    source_names, sources, credibility_score, is_rumor, rumor_reason,
                    source_count, importance_score
             FROM news_events ORDER BY time_get_data DESC"""
    if limit:
        sql += f" LIMIT {int(limit)}"
    cursor.execute(sql)
    rows = cursor.fetchall()
    cursor.close()

    events = []
    for row in rows:
        event = _row_to_event(row[:12])
        event.update({
            "credibility_score": row[12],
            "is_rumor": bool(row[13]),
            "rumor_reason": row[14] or "",
            "legacy_source_count": row[15],
            "importance_score": row[16],
        })
        events.append(event)
    return events


def _main() -> None:
    import argparse
    import collections
    import os
    import sys

    from . import storage

    parser = argparse.ArgumentParser(description="全库真实性验证跑批 / 抽样核对")
    parser.add_argument("--persist", action="store_true", help="把结果写回 news_events")
    parser.add_argument("--sample", type=int, default=20, help="每档抽样条数")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    conn = storage.get_mysql_conn()
    try:
        events = _load_all_events(conn, args.limit)
        print(f"\n载入 {len(events)} 条事件\n")

        start = now_local()
        stats = verify_events(events, reference=[])   # 全库互比，无需再取 reference
        elapsed = (now_local() - start).total_seconds()

        total = stats["total"]
        print(f"\n{'='*78}\n各档分布（耗时 {elapsed:.2f}s，LLM 调用 0 次，成本 $0）\n{'='*78}")
        for status in (STATUS_VERIFIED, STATUS_PROBABLE, STATUS_UNVERIFIED, STATUS_DISPUTED):
            n = stats[status]
            print(f"  {status:<12} {n:>5}  {n/total*100:>5.1f}%")

        flag_counter = collections.Counter(
            f for e in events for f in e.get("verification_flags", []))
        print(f"\n异常码分布：")
        for flag, n in flag_counter.most_common():
            print(f"  {flag:<26} {n:>5}")

        inst_counter = collections.Counter(e["independent_source_count"] for e in events)
        print(f"\n独立机构数分布（对比库里旧 source_count）：")
        for k in sorted(inst_counter):
            print(f"  {k} 家: {inst_counter[k]}")
        differing = sum(1 for e in events
                        if e["independent_source_count"] != (e.get("legacy_source_count") or 1))
        print(f"  与旧 source_count 不一致: {differing}")

        if args.persist:
            # 先落库再打样本：抽样打印只是人工核对用，不该挡住写入
            persist_verification(events, conn)

        def _dump(status: str, n: int) -> None:
            if n <= 0:
                return
            rows = [e for e in events if e["verification_status"] == status]
            rows.sort(key=lambda e: e["verification_score"])
            print(f"\n{'='*78}\n{status} 抽样 {min(n, len(rows))}/{len(rows)}\n{'='*78}")
            step = max(1, len(rows) // n) if len(rows) > n else 1
            for e in rows[::step][:n]:
                print(f"\n[{e['verification_score']:.3f}] {e.get('title_zh') or e.get('title_en')}")
                print(f"    信源: {e.get('source_names')}  独立机构数={e['independent_source_count']}")
                print(f"    依据: {e['verification_reason']}")
                if e.get("is_rumor"):
                    print(f"    LLM: is_rumor=1 cred={e.get('credibility_score')} {e.get('rumor_reason','')[:70]}")

        for status in (STATUS_DISPUTED, STATUS_UNVERIFIED, STATUS_PROBABLE, STATUS_VERIFIED):
            _dump(status, args.sample)
    finally:
        conn.close()


if __name__ == "__main__":
    _main()
