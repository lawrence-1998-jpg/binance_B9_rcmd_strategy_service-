"""
搜索引擎新闻召回模块 v1.0

背景：现有信源覆盖率对 6 家主流平台达 91.9%，但两类事件系统性欠召——
行情异动类报道只占 3.9%、宏观美股交叉类只占 4.7%（现有 RSS/HTML/X 源
本来就不是为了追这两类新闻设计的，媒体对"币价暴跌"这种事件的报道
散落在几十个财经站点，没法逐个开 RSS）。本模块用搜索引擎生态兜底：
"google 一搜就能搜出来的 news 我们也得有"。

技术选型实测结论（VM 上跑的，2026-07-25/26，详见交付说明）：
  1. Google News RSS —— 采用，主力渠道。免费无 key，中英文都稳定返回，
     响应快（<1s），60 连击 0.8s 间隔 0 次限流。**但默认按相关性排序，
     不加时间算子时结果中位年龄可达 900~3000+ 小时（37~130+ 天），
     完全不能直接用。加 `when:Nh`/`when:Nd` 后中位年龄骤降到个位数小时，
     且随算子单调变化（when:1h → med 0.8h；when:6h → med 3h；when:1d →
     med 7~19h），是本模块能"只要最近内容"的唯一原因，因此每条查询都
     强制带 when: 算子，绝不允许裸查询进入这个模块。
  2. Bing News RSS —— 不采用。中文查询在多个测试词、多种 mkt 参数下
     全部返回 0 条（"比特币"/"加密货币"/"以太坊 监管" 均为空），英文
     倒是有结果但时间算子形同虚设（qft=interval="1"《1小时》直接返回
     0 条，interval="4"《24小时》只给 3 条，且不加算子时中位年龄仍有
     36~3400+ 小时），召回价值和可控性都不够，不值得为它单独维护一套
     解析逻辑。
  3. ddgs 的 `.news()` 接口 —— 采用，作为英文补充（不是主力）。英文稳定
     出结果（8/8 次成功），`timelimit="d"` 下中位年龄多在 1~4 天，比
     Google 松一些但可接受，且它命中的信源和 Google News 有一部分不重叠
     （比如 AMBCrypto、TheStreet via Yahoo News 这类 Google 排序里靠后
     的站点）。**中文查询 100% 失败**（`DDGSException: No results found`，
     试了"比特币 暴跌"和"美联储 加密"两个词、加不加 region=cn-zh 结果
     一样），所以只在英文查询上启用，不做中文尝试。

成本控制（全部普通代码，不调 LLM）：
  - 域名白名单分级 + 黑名单过滤内容农场（_authority_for_domain /
    _BLOCKED_DOMAINS）
  - URL 规范化去重 + 标题指纹去重（Google News 标题固定带 " - 发布方"
    后缀，规范化时会先剥掉）
  - 48 小时硬性时间窗口（比 main.py 全局的 7 天更紧，这个模块的定位就是
    "抓刚发生的"，陈旧内容对它没有增量价值）

速率保护：
  - 单轮查询数硬上限 MAX_QUERIES_PER_RUN
  - 查询间 sleep（Google/ddgs 分别配置）
  - Google 用简单重试 + 退避应对非 200 响应；ddgs 单条查询异常直接跳过，
    不重试（DDGS 库本身对 429 会抛异常而不是返回 429 状态码，重试意义
    不大，参考 crawler/main.py fetch_binance_square 的处理方式）
"""
import logging
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import feedparser
import requests

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

# ── 可调参数 ─────────────────────────────────────────────────────────

# 只保留最近 N 小时内的内容。这个模块的价值就是"抓刚发生的"，卡得比
# main.py 全局的 7 天（MAX_CONTENT_AGE_DAYS）紧得多。
MAX_CONTENT_AGE_HOURS = 48

# 单轮查询数硬上限（Google + ddgs 合计），防止查询集被扩得太大打爆 IP。
MAX_QUERIES_PER_RUN = 60

# 查询之间的间隔。Google 实测 60 连击 0.8s 间隔 0 次限流，这里留更宽松的
# 余量；ddgs 走的是聚合抓取（背后是必应/多引擎），偏保守一点。
SLEEP_BETWEEN_GOOGLE_QUERIES = 1.2
SLEEP_BETWEEN_DDGS_QUERIES = 2.0

# 单条 Google 查询非 200 时的重试次数与等待秒数。
GOOGLE_RETRIES = 2
GOOGLE_RETRY_WAIT = 3.0

# 每条查询最多拿多少条（Google 一页通常给 30~100 条，取太多进 LLM 成本高，
# 这里的查询本来就带了 when: 强时间约束，够新的条目本身也不会太多）。
MAX_ITEMS_PER_QUERY = 30


# ── 查询集设计 ───────────────────────────────────────────────────────
#
# 结构: (group_id, category, query_text, lang, when_op)
#   group_id  — 日志/统计用的唯一标识
#   category  — 归类统计用，不影响抓取逻辑
#   query_text— 搜索词（不含 when: 算子，算子由 when_op 拼接）
#   lang      — "zh" 用 hl=zh-CN&gl=CN&ceid=CN:zh-Hans，"en" 用 US locale
#   when_op   — Google when: 算子。行情异动/突发类要快（when:6h），
#               宏观/监管类新闻更新没那么快、且需要更大窗口才捞得到东西
#               （实测 when:1d 下这两类中位年龄仍有 15~28 小时），用 when:1d
#
# 覆盖的四个欠召方向（对照现有 91.9% 覆盖率里 3.9%/4.7% 的两个洼地，
# 以及 PM 明确点名的"突发/监管"）：
GOOGLE_NEWS_QUERIES: list[tuple[str, str, str, str, str]] = [
    # ── 行情异动的媒体报道 ───────────────────────────────────────────
    ("mkt_zh_plunge",  "market", "比特币 暴跌",        "zh", "when:6h"),
    ("mkt_zh_liq",     "market", "加密货币 爆仓",       "zh", "when:6h"),
    ("mkt_zh_eth",     "market", "以太坊 暴跌",        "zh", "when:6h"),
    ("mkt_en_plunge",  "market", "bitcoin plunges",     "en", "when:6h"),
    ("mkt_en_liq",     "market", "crypto liquidations", "en", "when:6h"),
    ("mkt_en_crash",   "market", "bitcoin crashes",     "en", "when:6h"),
    ("mkt_en_eth",     "market", "ethereum plunges",    "en", "when:6h"),

    # ── 宏观/美股与加密的交叉 ────────────────────────────────────────
    ("macro_zh_fed",   "macro", "美联储 加密货币",      "zh", "when:1d"),
    ("macro_zh_nasdaq","macro", "纳斯达克 比特币",      "zh", "when:1d"),
    ("macro_zh_cpi",   "macro", "CPI 比特币",          "zh", "when:1d"),
    ("macro_en_fed",   "macro", "Fed crypto",           "en", "when:1d"),
    ("macro_en_cpi",   "macro", "CPI bitcoin",          "en", "when:1d"),
    ("macro_en_nasdaq","macro", "Nasdaq bitcoin",       "en", "when:1d"),
    ("macro_en_selloff","macro","stock market crypto selloff", "en", "when:1d"),

    # ── 突发（交易所被黑 / 漏洞利用）──────────────────────────────────
    ("brk_zh_hack",    "breaking", "交易所 被黑",       "zh", "when:6h"),
    ("brk_zh_hacker",  "breaking", "加密货币 黑客",      "zh", "when:6h"),
    ("brk_en_hack",    "breaking", "crypto hack",        "en", "when:6h"),
    ("brk_en_exploit", "breaking", "crypto exploit",     "en", "when:6h"),
    ("brk_en_exchange","breaking", "exchange hacked",    "en", "when:6h"),
    # 2026-07-26 新增：覆盖率测试实测千万美元级安全事故会漏（$31.7M 双桥被盗、
    # $280M Drift 漏洞均不在信源盘子里），"bridge/protocol" 是这类事故的高频措辞，
    # 现有查询只覆盖了"交易所/crypto"层面，桥和协议层面完全没覆盖
    ("brk_en_bridge",  "breaking", '"bridge exploit" crypto', "en", "when:6h"),
    ("brk_en_drained", "breaking", '"protocol drained"',      "en", "when:6h"),

    # ── 监管 ─────────────────────────────────────────────────────────
    ("reg_zh_sec",     "regulation", "SEC 加密货币",    "zh", "when:1d"),
    ("reg_zh_general", "regulation", "加密货币 监管",    "zh", "when:1d"),
    ("reg_en_sec",     "regulation", "SEC crypto",       "en", "when:1d"),
    ("reg_en_general", "regulation", "crypto regulation","en", "when:1d"),
    ("reg_en_bill",    "regulation", "crypto bill congress", "en", "when:1d"),

    # ── 协议治理（2026-07-26 新增）───────────────────────────────────
    # 起因：覆盖率交叉验证实测发现这是一个成片空白——仅 Bitcoinist 一家媒体就
    # 贡献了 6 条漏召（Frax 提案、EigenLayer ELIP、Uniswap RFC、Arbitrum 安全
    # 委员会投票），现有查询集里没有任何一条覆盖"链上治理动态"这个方向。
    # 用治理场景的专有名词（ELIP/RFC/DAO vote/governance proposal）而非泛泛的
    # "governance"，避免捞回大量与加密无关的公司治理新闻。
    ("gov_en_proposal","governance", '"governance proposal" crypto', "en", "when:1d"),
    ("gov_en_dao_vote","governance", '"DAO vote"',                   "en", "when:1d"),
    ("gov_en_elip_rfc","governance", "ELIP OR RFC protocol upgrade",  "en", "when:1d"),
    ("gov_zh_proposal","governance", "DAO 治理提案",                  "zh", "when:1d"),
]

# ── ddgs 补充查询（仅英文，见模块头部选型说明）──────────────────────
DDGS_NEWS_QUERIES: list[tuple[str, str, str]] = [
    ("ddgs_mkt",   "market",     "bitcoin plunges"),
    ("ddgs_brk",   "breaking",   "crypto hack"),
    ("ddgs_macro", "macro",      "Fed crypto"),
    ("ddgs_reg",   "regulation", "SEC crypto"),
]


# ── 域名分级 / 黑名单（成本控制第一道闸：普通代码，不调 LLM）─────────
#
# 分级只影响 authority 字段（后续交给 scoring.py 的 LLM 提示词参考，本模块
# 不做终审）。黑名单是硬过滤——命中即整条丢弃，不进 LLM。
#
# 名单基于本轮实测（Google News + ddgs 样本）里实际出现的域名归类，不是
# 凭空拍的；default 分（AUTHORITY_DEFAULT）覆盖没见过的长尾域名。
_TIER_5 = {
    "coindesk.com", "theblock.co", "reuters.com", "bloomberg.com",
    "wsj.com", "ft.com", "apnews.com",
}
_TIER_4 = {
    "cointelegraph.com", "decrypt.co", "blockworks.co", "cnbc.com",
    "forbes.com", "finance.yahoo.com", "yahoo.com", "businessinsider.com",
    "marketwatch.com", "techcrunch.com", "thedefiant.io",
    "panewslab.com", "chaincatcher.com", "wublock123.com",
    "techflowpost.com", "theblockbeats.info", "jinse.com", "followin.io",
    "foresightnews.pro", "coincu.com",
}
_TIER_3 = {
    "benzinga.com", "u.today", "dailyhodl.com", "cryptoglobe.com",
    "ambcrypto.com", "financemagnates.com", "investing.com",
    "seekingalpha.com", "barrons.com", "nasdaq.com", "cryptorank.io",
    "fxstreet.com", "thestreet.com", "cryptoslate.com", "watcher.guru",
}
AUTHORITY_DEFAULT = 2  # 没见过的长尾域名，保守给分

# 内容农场/纯 SEO 站点：标题党、洗稿转载为主，人工核实过质量差，直接拦截。
_BLOCKED_DOMAINS = {
    "coinpedia.org", "insidebitcoins.com", "99bitcoins.com",
    # newsbtc.com 已移出黑名单（2026-07-26 裁决）：库内实测 11 条事件 7 条
    # VERIFIED、质量分 0.761、零谣言，表现是正经二线媒体的水平，与"内容农场"
    # 判定不符；对应地它在 sources.py 保留 RSS 席位但权威降为 2（编辑质量
    # 尚可、独立采编深度有限）。bitcoinist.com 维持拦截，证据见 sources.py。
    "zycrypto.com", "cryptopolitan.com",
    "coingape.com", "cryptonewsz.com", "livebitcoinnews.com",
    "bitcoinist.com", "cryptodaily.co.uk",
}

_GOOGLE_TITLE_SUFFIX_RE = re.compile(r"\s+-\s+[^-]{2,40}$")
_WS_RE = re.compile(r"\s+")

# 主题相关性关键词（第二道成本控制闸）：实测跑一轮后发现，宽泛查询词
# （尤其 "美联储 加密货币" / "Fed crypto" 这类宏观交叉词）会捞回完全不
# 相关的内容——尼日利亚股市涨跌、OpenAI 宕机、ETF 名词解释文这类长尾站点
# 的水文。真正靠谱的加密媒体（_TIER_3/4/5 里的域名）本身发的都是加密相关
# 内容，即使标题写得抽象也不该被误杀，所以这道过滤**只对默认档
# （AUTHORITY_DEFAULT，没进任何白名单的长尾域名）生效**——白名单域名的内容
# 直接放行，不做二次判断。
_CRYPTO_KEYWORDS_RE = re.compile(
    r"bitcoin|btc|ethereum|\beth\b|crypto|defi|blockchain|web3|token|"
    r"stablecoin|binance|coinbase|altcoin|nft|"
    r"比特币|以太坊|加密货币|加密资产|数字货币|数字资产|区块链|币安|"
    r"稳定币|链上|代币|交易所|矿工|挖矿|狗狗币|瑞波币|马斯克币",
    re.IGNORECASE,
)


def _domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _authority_for_domain(domain: str) -> int:
    if domain in _TIER_5:
        return 5
    if domain in _TIER_4:
        return 4
    if domain in _TIER_3:
        return 3
    return AUTHORITY_DEFAULT


def _is_blocked(domain: str) -> bool:
    return domain in _BLOCKED_DOMAINS


def _clean_google_title(title: str, source_title: str) -> str:
    """Google News 标题固定带 " - 发布方" 后缀，剥掉让标题和其它信源风格一致。"""
    title = title.strip()
    if source_title and title.endswith(source_title):
        stripped = title[: -len(source_title)].rstrip()
        if stripped.endswith("-"):
            stripped = stripped[:-1].rstrip()
        if len(stripped) >= 8:
            return stripped
    return _GOOGLE_TITLE_SUFFIX_RE.sub("", title).strip()


def _normalize_url_key(url: str) -> str:
    """URL 规范化去重键：去协议/query/fragment/末尾斜杠，host 小写。
    Google News 的 link 是一次性重定向 token，天然唯一，规范化对它没有
    合并作用，但对 ddgs 返回的真实文章 URL（可能带追踪参数）有效。"""
    try:
        p = urlparse(url)
        host = p.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        path = p.path.rstrip("/")
        return f"{host}{path}"
    except Exception:
        return url


def _title_fingerprint(title: str) -> str:
    """标题指纹去重键：小写、去空白、去常见标点。"""
    t = title.lower()
    t = re.sub(r"[^\w一-鿿]+", "", t)
    return t[:100]


def _within_window(published_at: str, now: datetime, max_age_hours: int) -> bool:
    if not published_at:
        return False
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_hours = (now - dt).total_seconds() / 3600
    return -1 <= age_hours <= max_age_hours  # 容忍 1 小时内的未来时间戳（时区误差）


# ── Google News RSS ──────────────────────────────────────────────────

def _google_news_url(query: str, when_op: str, lang: str) -> str:
    q = f"{query} {when_op}".strip()
    locale = ("hl=zh-CN&gl=CN&ceid=CN:zh-Hans" if lang == "zh"
              else "hl=en-US&gl=US&ceid=US:en")
    return f"{GOOGLE_NEWS_RSS}?q={urllib.parse.quote(q)}&{locale}"


def _fetch_google_query(group_id: str, category: str, query: str, lang: str,
                        when_op: str) -> list[dict]:
    url = _google_news_url(query, when_op, lang)
    last_exc = None
    for attempt in range(GOOGLE_RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                last_exc = f"HTTP {resp.status_code}"
                time.sleep(GOOGLE_RETRY_WAIT)
                continue
            feed = feedparser.parse(resp.content)
            break
        except Exception as e:
            last_exc = e
            time.sleep(GOOGLE_RETRY_WAIT)
    else:
        logger.warning(f"GoogleNews [{group_id}] '{query}' failed after retries: {last_exc}")
        return []

    items = []
    for entry in feed.entries[:MAX_ITEMS_PER_QUERY]:
        title_raw = entry.get("title", "").strip()
        if not title_raw:
            continue
        link = entry.get("link", "")

        source = entry.get("source")
        source_title = ""
        source_href = ""
        if isinstance(source, dict):
            source_title = source.get("title", "") or ""
            source_href = source.get("href", "") or ""
        else:
            source_title = getattr(source, "title", "") or ""
            source_href = getattr(source, "href", "") or ""

        title = _clean_google_title(title_raw, source_title)
        domain = _domain_of(source_href) if source_href else ""
        if not domain:
            # 极少数条目没带 source.href，退化用发布方展示名当来源标签，
            # authority 走默认档。
            domain = source_title.lower().replace(" ", "")

        if _is_blocked(domain):
            continue

        published = ""
        if getattr(entry, "published_parsed", None):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()

        summary_raw = entry.get("summary", "") or ""
        # summary 是一段 <a href=...>标题</a> 的 HTML，剥掉标签只留标题文本，
        # 没有独立摘要正文，用清洗后的标题回填，保持字段非空。
        summary = re.sub(r"<[^>]+>", "", summary_raw).strip() or title

        items.append({
            "source": source_title or "GoogleNews",
            "title": title,
            "url": link,
            "summary": summary[:500],
            "published_at": published,
            "lang": lang,
            "authority": _authority_for_domain(domain),
            "type": "web_search",
            "_domain": domain,       # 内部字段，去重/统计用，返回前会剥掉
            "_group": group_id,
            "_category": category,
        })
    return items


def fetch_google_news(queries: list[tuple[str, str, str, str, str]] | None = None,
                      collect_stats: dict | None = None) -> list[dict]:
    """Google News RSS 召回。每条查询强制带 when: 算子（见模块头部说明）。"""
    queries = queries if queries is not None else GOOGLE_NEWS_QUERIES
    stats = collect_stats if collect_stats is not None else {}
    stats.setdefault("google_requests", 0)
    stats.setdefault("google_raw", 0)
    stats.setdefault("by_group", {})

    all_items = []
    for group_id, category, query, lang, when_op in queries:
        if stats["google_requests"] >= MAX_QUERIES_PER_RUN:
            logger.warning(f"GoogleNews: MAX_QUERIES_PER_RUN={MAX_QUERIES_PER_RUN} reached, "
                           f"stopping at {group_id}")
            break
        assert when_op.startswith("when:"), (
            f"GoogleNews query '{group_id}' missing when: operator — 会退化成按相关性排序，"
            f"中位年龄可达数十天，禁止裸查询"
        )
        stats["google_requests"] += 1
        items = _fetch_google_query(group_id, category, query, lang, when_op)
        stats["google_raw"] += len(items)
        stats["by_group"][group_id] = len(items)
        all_items.extend(items)
        time.sleep(SLEEP_BETWEEN_GOOGLE_QUERIES)

    logger.info(f"GoogleNews: {stats['google_requests']} requests / {len(queries)} queries, "
               f"{stats['google_raw']} raw items")
    return all_items


# ── ddgs .news() 英文补充 ─────────────────────────────────────────────

def fetch_ddgs_news(queries: list[tuple[str, str, str]] | None = None,
                    collect_stats: dict | None = None) -> list[dict]:
    """ddgs news 接口，仅英文（中文 100% 失败，见模块头部选型说明）。"""
    queries = queries if queries is not None else DDGS_NEWS_QUERIES
    stats = collect_stats if collect_stats is not None else {}
    stats.setdefault("ddgs_requests", 0)
    stats.setdefault("ddgs_raw", 0)
    stats.setdefault("by_group", {})

    all_items = []
    try:
        from ddgs import DDGS
    except Exception as e:
        logger.warning(f"ddgs import failed, skip: {e}")
        return []

    with DDGS() as ddgs:
        for group_id, category, query in queries:
            if stats["ddgs_requests"] >= MAX_QUERIES_PER_RUN - stats.get("google_requests", 0):
                logger.warning(f"ddgs: query budget exhausted, stopping at {group_id}")
                break
            stats["ddgs_requests"] += 1
            try:
                results = ddgs.news(query, max_results=MAX_ITEMS_PER_QUERY, timelimit="d") or []
            except Exception as e:
                logger.warning(f"ddgs.news [{group_id}] '{query}' failed: {e}")
                time.sleep(SLEEP_BETWEEN_DDGS_QUERIES)
                continue

            group_items = []
            for r in results:
                title = (r.get("title") or "").strip()
                url = r.get("url") or ""
                if not title or not url:
                    continue
                domain = _domain_of(url)
                if _is_blocked(domain):
                    continue
                group_items.append({
                    "source": r.get("source") or domain or "ddgs",
                    "title": title,
                    "url": url,
                    "summary": (r.get("body") or title)[:500],
                    "published_at": r.get("date") or "",
                    "lang": "en",
                    "authority": _authority_for_domain(domain),
                    "type": "web_search",
                    "_domain": domain,
                    "_group": group_id,
                    "_category": category,
                })
            stats["ddgs_raw"] += len(group_items)
            stats["by_group"][group_id] = len(group_items)
            all_items.extend(group_items)
            time.sleep(SLEEP_BETWEEN_DDGS_QUERIES)

    logger.info(f"ddgs.news: {stats['ddgs_requests']} requests, {stats['ddgs_raw']} raw items")
    return all_items


# ── 去重 + 时间过滤（普通代码，不调 LLM）─────────────────────────────

def _dedup_and_filter(items: list[dict], now: datetime | None = None,
                      collect_stats: dict | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    stats = collect_stats if collect_stats is not None else {}
    stats.setdefault("drop_stale", 0)
    stats.setdefault("drop_dup_url", 0)
    stats.setdefault("drop_dup_title", 0)
    stats.setdefault("drop_no_title", 0)
    stats.setdefault("drop_offtopic", 0)

    seen_urls, seen_titles = set(), set()
    kept = []
    for item in items:
        title = item.get("title", "").strip()
        if len(title) < 6:
            stats["drop_no_title"] += 1
            continue

        # 主题相关性：只筛长尾默认档域名，白名单域名直接放行（理由见常量定义处）
        if item.get("authority") == AUTHORITY_DEFAULT:
            blob = f"{title} {item.get('summary', '')}"
            if not _CRYPTO_KEYWORDS_RE.search(blob):
                stats["drop_offtopic"] += 1
                continue

        if not _within_window(item.get("published_at", ""), now, MAX_CONTENT_AGE_HOURS):
            stats["drop_stale"] += 1
            continue

        url_key = _normalize_url_key(item.get("url", ""))
        if url_key and url_key in seen_urls:
            stats["drop_dup_url"] += 1
            continue

        title_key = _title_fingerprint(title)
        if title_key in seen_titles:
            stats["drop_dup_title"] += 1
            continue

        seen_urls.add(url_key)
        seen_titles.add(title_key)
        # 内部字段用完即扔，保持和其它信源一致的对外 schema
        item.pop("_domain", None)
        item.pop("_group", None)
        item.pop("_category", None)
        kept.append(item)

    return kept


# ── 主入口 ───────────────────────────────────────────────────────────

def fetch_web_search(collect_stats: dict | None = None) -> list[dict]:
    """搜索引擎新闻召回主入口。返回 news_events 兼容的 item 列表。

    调用方（接入总入口）用法同其它 fetch_* 函数：
        items = fetch_web_search()
        all_items.extend(items)
    """
    stats = collect_stats if collect_stats is not None else {}
    now = datetime.now(timezone.utc)

    raw_items = []
    raw_items.extend(fetch_google_news(collect_stats=stats))
    raw_items.extend(fetch_ddgs_news(collect_stats=stats))

    stats["raw_total"] = len(raw_items)
    kept = _dedup_and_filter(raw_items, now=now, collect_stats=stats)
    stats["kept_total"] = len(kept)

    total_requests = stats.get("google_requests", 0) + stats.get("ddgs_requests", 0)
    dropped = stats["raw_total"] - stats["kept_total"]
    logger.info(
        f"WebSearch: {total_requests} requests total, {stats['raw_total']} raw -> "
        f"{stats['kept_total']} kept (filtered {dropped}) | "
        f"stale={stats.get('drop_stale', 0)} dup_url={stats.get('drop_dup_url', 0)} "
        f"dup_title={stats.get('drop_dup_title', 0)} no_title={stats.get('drop_no_title', 0)} "
        f"offtopic={stats.get('drop_offtopic', 0)}"
    )
    return kept


# ── dry-run：单独跑这个文件看效果，不碰 DB 也不碰 LLM ─────────────────
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        stream=sys.stdout)
    st: dict = {}
    result = fetch_web_search(collect_stats=st)
    print("\n--- per-group raw counts ---")
    for gid, n in st.get("by_group", {}).items():
        print(f"  {gid:18s} raw={n:3d}")
    print(f"\n--- {len(result)} kept items ---")
    for it in result[:40]:
        print(f"  [{it['authority']}] {it['source']:20s} {it['title'][:100]}")
