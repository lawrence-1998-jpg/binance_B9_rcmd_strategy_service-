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
    RSS_SOURCES_P0, RSS_SOURCES_P1, RSS_SOURCES_RSSHUB,
    HTML_SOURCES, BINANCE_SQUARE_QUERIES, CRYPTO_KOLS, X_TWEETS_PER_KOL,
)

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}


# ── RSS 抓取（官方 + RSSHub 通用）────────────────────────────────────

def fetch_rss(url: str, source_name: str, lang: str, authority: int) -> list[dict]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        feed = feedparser.parse(resp.content)
        items = []
        for entry in feed.entries[:30]:
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
            "published_at": datetime.now(timezone.utc).isoformat(),
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
            "published_at": datetime.now(timezone.utc).isoformat(),
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

def run_rss_and_scraper_crawler() -> tuple[list[dict], list[dict]]:
    """运行全部爬虫。返回 (all_items, x_raw_posts)"""
    all_items = []

    for url, name, lang, authority in RSS_SOURCES_P0 + RSS_SOURCES_RSSHUB + RSS_SOURCES_P1:
        all_items.extend(fetch_rss(url, name, lang, authority))
        time.sleep(0.5)

    for source in HTML_SOURCES:
        all_items.extend(fetch_html_source(source))
        time.sleep(0.5)

    all_items.extend(fetch_binance_square(BINANCE_SQUARE_QUERIES))
    all_items.extend(fetch_coinmarketcal())

    x_items, x_raw_posts = fetch_x_kols()
    all_items.extend(x_items)

    all_items = [item for item in all_items if item.get("title", "").strip()]
    logger.info(f"Total raw items: {len(all_items)} (incl. {len(x_items)} X)")
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
        now = datetime.now(timezone.utc)
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
                "published_at": e.get("createdAt", "") or "",
                "lang": "en",
                "authority": 4,
                "type": "calendar",
            })
        logger.info(f"CoinMarketCal: {len(items)} upcoming catalyst events")
        return items
    except Exception as e:
        logger.warning(f"CoinMarketCal failed: {e}")
        return []
