"""
爬虫主模块 v2.0 - RSS(官方+RSSHub) + HTML抓取 + 币安广场搜索 + X KOL
"""
import os
import re
import time
import logging
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timezone

from .sources import (
    RSS_SOURCES_P0, RSS_SOURCES_P1, RSS_SOURCES_P2, RSS_SOURCES_MACRO,
    RSS_SOURCES_GLOBAL_MARKETS, RSS_SOURCES_RSSHUB,
    HTML_SOURCES, BINANCE_SQUARE_QUERIES, CRYPTO_KOLS, X_TWEETS_PER_KOL,
)
from .x_search import fetch_x_search
from .web_search import fetch_web_search
from .market_signals import run_market_signals
from .dxfeed_news import fetch_dxfeed_news
from .timeutil import now_local

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}

# 内容最大年龄。超过这个天数的条目直接丢弃，不进 LLM 也不入库。
#
# 起因：部分 RSS 会在最新条目里混入常青/存档内容——YahooFinance 吐出过 2024 年的
# 个人理财文章（"self-employed business banking"），Blockworks 吐出过 55 条 2025-12
# 的存档。这些条目日期错误会污染时效因子 T（算成接近 0），内容本身也是纯噪音。
#
# 7 天是很宽松的界：Macro Insight 的 T 因子半衰期只有 24h，96h 后 T≈0.06 已经基本
# 排不进榜了，卡 7 天不会误伤任何有价值的内容。
MAX_CONTENT_AGE_DAYS = 7

# 允许的未来时间容差。时区标注错误常导致时间戳略超前，几小时内视为正常。
MAX_FUTURE_HOURS = 24

# 单个 RSS 源每轮最多取多少条。
#
# 必须 >= 一轮周期内该源的发文量，否则直接丢召回。cron 从每 4 小时改成每 12 小时
# 后（2026-07-26，为降本），高频源单轮发文量翻了三倍——吴说 4 小时就有 30 条，
# 12 小时约 90 条，旧的 30 条上限会把三分之二的内容截掉。
# 取 100 是因为绝大多数 RSS 源本身也就返回 20-100 条，取满即可；多要不会报错。
MAX_RSS_ENTRIES_PER_SOURCE = 100


# ── RSS 抓取（官方 + RSSHub 通用）────────────────────────────────────

def fetch_rss(url: str, source_name: str, lang: str, authority: int) -> list[dict]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        feed = feedparser.parse(resp.content)
        items = []
        for entry in feed.entries[:MAX_RSS_ENTRIES_PER_SOURCE]:
            published = ""
            if getattr(entry, "published_parsed", None):
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
            elif getattr(entry, "updated_parsed", None):
                published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc).isoformat()

            summary = ""
            raw_sum = entry.get("summary") or entry.get("description") or ""
            if raw_sum:
                summary = BeautifulSoup(raw_sum, "lxml").get_text()[:500]

            title = entry.get("title", "").strip()
            if not title:
                continue
            items.append({
                "source": source_name,
                "title": title,
                "url": entry.get("link", ""),
                "summary": summary.strip(),
                "published_at": published,
                "lang": lang,
                "authority": authority,
                "type": "rss",
            })
        logger.info(f"RSS {source_name}: {len(items)} items")
        return items
    except Exception as e:
        logger.warning(f"RSS {source_name} failed: {e}")
        return []


# ── HTML 抓取源 ──────────────────────────────────────────────────────

def _parse_chaincatcher(html: str, source: dict) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items, seen = [], set()
    for a in soup.select('a[href^="/article/"]'):
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if not title or len(title) < 10 or href in seen:
            continue
        seen.add(href)
        # 去掉尾部拼接的时间戳和"微信扫码"等噪音: "...07-25 23:17微信扫码"
        title = re.sub(r"\d{2}-\d{2}\s*\d{2}:\d{2}.*$", "", title).strip()
        if len(title) < 10:
            continue
        items.append({
            "source": source["name"],
            "title": title,
            "url": source["base_url"] + href,
            "summary": title,
            "published_at": now_local().isoformat(),
            "lang": source["lang"],
            "authority": source["authority"],
            "type": "scraper",
        })
    return items[:25]


def _parse_panews(html: str, source: dict) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        title = a.get_text(strip=True)
        if "/zh/articles/" not in href or not title or len(title) < 12 or href in seen:
            continue
        seen.add(href)
        full = href if href.startswith("http") else source["base_url"] + href
        items.append({
            "source": source["name"],
            "title": title[:200],
            "url": full,
            "summary": title[:200],
            "published_at": now_local().isoformat(),
            "lang": source["lang"],
            "authority": source["authority"],
            "type": "scraper",
        })
    return items[:25]

_HTML_PARSERS = {"chaincatcher": _parse_chaincatcher, "panews": _parse_panews}


def fetch_html_source(source: dict) -> list[dict]:
    try:
        resp = requests.get(source["url"], headers=HEADERS, timeout=30)
        parser = _HTML_PARSERS[source["parser"]]
        items = parser(resp.text, source)
        logger.info(f"HTML {source['name']}: {len(items)} items")
        return items
    except Exception as e:
        logger.warning(f"HTML {source['name']} failed: {e}")
        return []


# ── 币安广场（ddgs 搜索）─────────────────────────────────────────────

def fetch_binance_square(queries: list[str]) -> list[dict]:
    items = []
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            for query in queries:
                try:
                    results = ddgs.text(query, max_results=5)
                    for r in (results or []):
                        href = r.get("href", "")
                        if "binance." in href and "square" in href:
                            items.append({
                                "source": "BinanceSquare",
                                "title": r.get("title", "").strip(),
                                "url": href,
                                "summary": r.get("body", "")[:500],
                                "published_at": "",
                                "lang": "en",
                                "authority": 4,
                                "type": "social",
                            })
                    time.sleep(1.5)
                except Exception as e:
                    logger.warning(f"BinanceSquare '{query}' failed: {e}")
    except Exception as e:
        logger.warning(f"ddgs init failed: {e}")
    logger.info(f"BinanceSquare: {len(items)} items")
    return items


# ── X API KOL 拉取 ───────────────────────────────────────────────────

X_API = "https://api.twitter.com/2"
_user_id_cache: dict[str, dict] = {}


def _x_get(path: str, params: dict, bearer: str) -> dict | None:
    try:
        resp = requests.get(
            f"{X_API}{path}", params=params,
            headers={"Authorization": f"Bearer {bearer}"}, timeout=20,
        )
        if resp.status_code == 429:
            logger.warning(f"X API rate limited: {path}")
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"X API {path} failed: {e}")
        return None


def fetch_x_kols() -> tuple[list[dict], list[dict]]:
    """拉取 KOL 推文。返回 (news_items, x_raw_posts)"""
    bearer = os.environ.get("X_BEARER_TOKEN", "")
    if not bearer:
        logger.warning("X_BEARER_TOKEN not set, skip X KOL")
        return [], []

    news_items, raw_posts = [], []
    for username, authority, category in CRYPTO_KOLS:
        # 1) 用户信息（带缓存）
        user = _user_id_cache.get(username)
        if not user:
            data = _x_get(f"/users/by/username/{username}",
                          {"user.fields": "public_metrics,verified,name"}, bearer)
            if not data or "data" not in data:
                continue
            user = data["data"]
            _user_id_cache[username] = user
        uid = user["id"]
        followers = (user.get("public_metrics") or {}).get("followers_count", 0)

        # 2) 最近推文
        data = _x_get(f"/users/{uid}/tweets", {
            "max_results": max(5, X_TWEETS_PER_KOL),
            "exclude": "retweets,replies",
            "tweet.fields": "created_at,public_metrics,lang",
        }, bearer)
        if not data or "data" not in data:
            continue

        for tw in data["data"][:X_TWEETS_PER_KOL]:
            text = tw.get("text", "").strip()
            if len(text) < 30:  # 过滤纯链接/口水推
                continue
            metrics = tw.get("public_metrics") or {}
            tweet_url = f"https://x.com/{username}/status/{tw['id']}"
            title = re.sub(r"https?://\S+", "", text).strip().replace("\n", " ")[:180]

            news_items.append({
                "source": f"X/{username}",
                "title": title,
                "url": tweet_url,
                "summary": text[:500],
                "published_at": tw.get("created_at", ""),
                "lang": tw.get("lang", "en"),
                "authority": authority,
                "type": "x",
                "tweet_id": tw["id"],
            })
            raw_posts.append({
                "tweet_id": tw["id"],
                "kol_username": username,
                "kol_display_name": user.get("name", username),
                "kol_followers_count": followers,
                "kol_verified": bool(user.get("verified", False)),
                "kol_profile_url": f"https://x.com/{username}",
                "tweet_title": title,
                "tweet_body": text,
                "tweet_url": tweet_url,
                "tweet_lang": tw.get("lang", "en"),
                "like_count": metrics.get("like_count", 0),
                "retweet_count": metrics.get("retweet_count", 0),
                "reply_count": metrics.get("reply_count", 0),
                "quote_count": metrics.get("quote_count", 0),
                "impression_count": metrics.get("impression_count", 0),
                "published_at": tw.get("created_at", ""),
            })
        time.sleep(1.0)

    logger.info(f"X KOL: {len(news_items)} tweets from {len(_user_id_cache)} KOLs")
    return news_items, raw_posts


# ── 主入口 ───────────────────────────────────────────────────────────

def normalize_published_at(value: str, now: datetime | None = None) -> str | None:
    """校验并规范化发布时间。返回 None 表示该条目应被丢弃。

    三种情况：
      - 缺失或无法解析 → 回落到当前时间（多数 HTML 抓取源本就没有可靠时间戳）
      - 早于 now - MAX_CONTENT_AGE_DAYS → 返回 None，调用方丢弃
      - 晚于 now + MAX_FUTURE_HOURS → 视为时区标注错误，回落到当前时间
    """
    now = now or now_local()
    if not value:
        return now.isoformat()
    try:
        published = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return now.isoformat()
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)

    age_days = (now - published).total_seconds() / 86400
    if age_days > MAX_CONTENT_AGE_DAYS:
        return None
    if age_days < -MAX_FUTURE_HOURS / 24:
        return now.isoformat()
    return published.isoformat()


# 2026-07-28：接入美股/港股/日股/韩股/世界宏观媒体后新增的 A 股排除闸。
# 老板明确要求"A股不要"——查询词本身没有一条是冲着 A 股去的，但国际财经媒体
# （CNBC/Nikkei/SCMP 这类覆盖面广的源）报道亚洲大盘时偶尔会捎带一句"沪指/
# 深成指/上证综指"，这道闸就是防止这类内容漏进来。只挡"以 A 股大盘/个股为
# 报道主体"的标题——中国的货币政策、GDP、关税这类宏观信息不会被误伤，因为
# 它们不会在标题里出现"沪指/A股"这类措辞（这类内容本身就该进"重大经济政策"
# 分类，是要收的，不是要挡的）。
_A_SHARE_TITLE_RE = re.compile(
    r"A股|沪指|深成指|上证综指|上证指数|深证成指|沪深300|创业板指|科创50|"
    r"shanghai composite|shenzhen component|csi ?300|star ?50",
    re.IGNORECASE,
)


def filter_a_share(items: list[dict]) -> list[dict]:
    """丢弃以 A 股大盘/个股为报道主体的条目。只查标题——用摘要判断容易把"提到

    中国经济但主体是别的市场"的内容也误杀（比如"中国关税政策对美股科技股影响"
    这种恰恰是要收的宏观政策交叉新闻）。
    """
    kept, dropped = [], 0
    for item in items:
        if _A_SHARE_TITLE_RE.search(item.get("title", "")):
            dropped += 1
            continue
        kept.append(item)
    if dropped:
        logger.info(f"A股排除闸：丢弃 {dropped} 条")
    return kept


def filter_by_freshness(items: list[dict]) -> list[dict]:
    """丢弃陈年内容，并把异常时间戳归一。按信源统计丢弃量便于排查。"""
    now = now_local()
    kept, dropped = [], {}
    for item in items:
        normalized = normalize_published_at(item.get("published_at", ""), now)
        if normalized is None:
            source = item.get("source", "?")
            dropped[source] = dropped.get(source, 0) + 1
            continue
        item["published_at"] = normalized
        kept.append(item)

    if dropped:
        detail = ", ".join(f"{k}×{v}" for k, v in
                           sorted(dropped.items(), key=lambda x: -x[1]))
        logger.info(f"Freshness filter: dropped {sum(dropped.values())} stale items ({detail})")
    return kept


def fetch_cheap_sources() -> list[dict]:
    """跑所有**不花钱**的抓取源：RSS/HTML/币安广场/CoinMarketCal/行情信号/搜索引擎。

    2026-07-26 拆出这个函数是为了解耦"抓取频率"和"处理频率"。背景：cron 从
    每 4 小时改成每 12 小时降本后，排查漏召时发现高频 RSS 源（吴说等）的服务端
    窗口是固定的（约 30-50 条），12 小时间隔会让发布密集的源把窗口内容挤掉、
    永久错过（不是 bug，是滚屏丢失，详见 docs/PROJECT_PLAN.md 的已知风险章节）。
    这些源本身抓取不花钱（相对昂贵的是下游 LLM 结构化），完全可以更高频跑，
    抓到就先存档（见 crawler/staging.py），LLM 处理仍按现有节奏批量消费存档。

    唯一**不放在这里**的是 X（KOL 时间线 + 全网搜索）——按用户要求，付费/限额
    类 API 维持现有节奏，不跟着提速，避免额度消耗加快。X 抓取仍在
    `run_rss_and_scraper_crawler()` 里，只在主 pipeline 节奏下调用一次。
    """
    all_items = []

    for url, name, lang, authority in (RSS_SOURCES_P0 + RSS_SOURCES_RSSHUB + RSS_SOURCES_P1
                                      + RSS_SOURCES_P2 + RSS_SOURCES_MACRO
                                      + RSS_SOURCES_GLOBAL_MARKETS):
        all_items.extend(fetch_rss(url, name, lang, authority))
        time.sleep(0.5)

    for source in HTML_SOURCES:
        all_items.extend(fetch_html_source(source))
        time.sleep(0.5)

    all_items.extend(fetch_binance_square(BINANCE_SQUARE_QUERIES))
    all_items.extend(fetch_coinmarketcal())

    # 行情异动信号：从行情 API 直接生成事件（大幅涨跌/突破/放量/资金费率/爆仓），
    # 补的是"没有媒体会写但确实是大事"的缺口——纯规则计算，不调 LLM，零边际成本。
    try:
        market_items = run_market_signals()
        all_items.extend(market_items)
        logger.info(f"Market signals: {len(market_items)} items")
    except Exception as e:
        logger.warning(f"Market signals failed, continuing without: {e}")

    # 搜索引擎新闻召回：Google News（when: 时间算子强制）+ ddgs 英文补充，
    # 补媒体对行情/宏观事件的报道側（区别于上面的行情信号本身）。
    try:
        web_items = fetch_web_search()
        all_items.extend(web_items)
        logger.info(f"Web search: {len(web_items)} items")
    except Exception as e:
        logger.warning(f"Web search failed, continuing without: {e}")

    # dxFeed News（2026-07-28 新增）：公司通过 Binance 账号采购的机构级美股实时
    # 新闻源（MT Newswires），补的是美股/宏观这块"搜索引擎召回精度不够"的缺口。
    # 未配置凭据（DXFEED_NEWS_USER/PASS）时函数自己直接跳过，不报错。
    try:
        dxfeed_items = fetch_dxfeed_news()
        all_items.extend(dxfeed_items)
        logger.info(f"dxFeed News: {len(dxfeed_items)} items")
    except Exception as e:
        logger.warning(f"dxFeed News failed, continuing without: {e}")

    all_items = [item for item in all_items if item.get("title", "").strip()]
    all_items = filter_a_share(all_items)
    all_items = filter_by_freshness(all_items)
    logger.info(f"Cheap sources: {len(all_items)} items")
    return all_items


# 2026-07-27：agent 演示完毕后，Lawrence 要求暂停增量扫描里的 X API 调用
# （降本，X 是按拉回条数计费的唯一付费抓取渠道）。这是**暂停**，不是删除——
# 默认关闭，需要恢复时把 config/.env 里的 X_FETCH_ENABLED 改回 true 或直接
# 删掉这行即可，不用改代码、不用回滚 git。
X_FETCH_ENABLED = os.environ.get("X_FETCH_ENABLED", "true").strip().lower() != "false"


def fetch_x_sources() -> tuple[list[dict], list[dict]]:
    """X 召回分两条腿：KOL 时间线（固定 32 个账号，深度）+ 全网关键词搜索（广度）。

    搜索这条腿补的是"新闻发生了但 KOL 名单里没人发"的缺口。两边会大量撞车
    （同一条推文），把 KOL 侧的 tweet_id 传下去让搜索侧提前跳过，比事后去重
    省一遍质量过滤，也保证撞车时保留 KOL 侧的版本（权威分是人工标注的，更准）。

    单独成函数是因为它**不参与** fetch_cheap_sources 的高频抓取——X 维持
    主 pipeline 节奏，不跟着提速。

    `X_FETCH_ENABLED=false` 时整条腿直接跳过，返回空列表——不是"抓了 0 条"
    的静默异常，是刻意关闭，日志里明确写清楚原因，避免被当成故障排查。
    """
    if not X_FETCH_ENABLED:
        logger.info("X sources: 已通过 X_FETCH_ENABLED=false 暂停，本轮跳过 X 抓取（KOL + 搜索）")
        return [], []

    x_items, x_raw_posts = fetch_x_kols()
    kol_ids = {p["tweet_id"] for p in x_raw_posts}

    search_items, search_raw_posts = fetch_x_search(known_tweet_ids=kol_ids)
    new_search_items = [i for i in search_items if i.get("tweet_id") not in kol_ids]
    new_search_posts = [p for p in search_raw_posts if p.get("tweet_id") not in kol_ids]
    if len(new_search_items) != len(search_items):
        logger.info(f"X search: {len(search_items) - len(new_search_items)} overlapped with KOL feed")

    all_items = x_items + new_search_items
    all_raw_posts = x_raw_posts + new_search_posts
    all_items = filter_by_freshness([i for i in all_items if i.get("title", "").strip()])
    logger.info(f"X sources: {len(all_items)} items ({len(x_items)} KOL + {len(new_search_items)} search)")
    return all_items, all_raw_posts


def run_rss_and_scraper_crawler() -> tuple[list[dict], list[dict]]:
    """运行全部爬虫（一次性拉全量，不走存档）。返回 (all_items, x_raw_posts)。

    保留这个函数是为了向后兼容——原本 `pipeline.run_pipeline()` 只调这一个入口。
    现在生产 pipeline 优先走 `crawler.staging` 的存档消费路径（见
    `scripts/stage_fetch.py` 与 `pipeline.py` Step 1 的改动），这个函数仍可用于
    手动单轮全量抓取（调试、补数据）。
    """
    cheap_items = fetch_cheap_sources()
    x_items, x_raw_posts = fetch_x_sources()
    all_items = cheap_items + x_items
    logger.info(f"Total raw items: {len(all_items)} (cheap {len(cheap_items)} + X {len(x_items)})")
    return all_items, x_raw_posts


def fetch_coinmarketcal() -> list[dict]:
    """CoinMarketCal 催化剂日历：未来 14 天代币解锁/主网/硬分叉/会议等事件。
    free tier 3000 req/月，每轮 1 次调用。4xx 不重试（key 失效）。
    注意：isEstimated=true 时 date 是 deadline，展示用 displayedDate。"""
    key = os.environ.get("COINMARKETCAL_API_KEY", "")
    if not key:
        logger.warning("CoinMarketCal: no API key, skipped")
        return []
    try:
        from datetime import timedelta
        now = now_local()
        params = {
            "dateRangeStart": now.strftime("%Y-%m-%d"),
            "dateRangeEnd": (now + timedelta(days=14)).strftime("%Y-%m-%d"),
            "limit": 75,
        }
        resp = requests.get(
            "https://api.coinmarketcal.com/v2/events",
            params=params, headers={"x-api-key": key}, timeout=30,
        )
        data = resp.json()
        if resp.status_code != 200 or "error" in data:
            logger.warning(f"CoinMarketCal error {resp.status_code}: {data.get('error')}")
            return []
        items = []
        for e in data.get("data", []):
            coins = [c.get("symbol", "").upper() for c in e.get("coins", []) if c.get("symbol")]
            title = e.get("title", "").strip()
            if not title or not coins:
                continue
            disp = e.get("displayedDate", "")
            summary = f"[催化剂日历] {'/'.join(coins)} 事件：{title}（时间：{disp}）"
            if e.get("description"):
                summary += f" — {e['description'][:300]}"
            items.append({
                "source": "CoinMarketCal",
                "title": f"{'/'.join(coins[:3])}: {title} ({disp})",
                "url": f"https://coinmarketcal.com/en/event/{e.get('slug', '')}",
                "summary": summary,
                # 用抓取时间，不用 API 的 createdAt——后者是日历条目被录入 CoinMarketCal
                # 数据库的时间，可能是几个月前，拿它当发布时间会让催化剂事件全部被
                # 新鲜度过滤误杀。催化剂的语义是"此刻披露的未来事件"，抓取时间才对。
                "published_at": now.isoformat(),
                "lang": "en",
                "authority": 4,
                "type": "calendar",
            })
        logger.info(f"CoinMarketCal: {len(items)} upcoming catalyst events")
        return items
    except Exception as e:
        logger.warning(f"CoinMarketCal failed: {e}")
        return []
