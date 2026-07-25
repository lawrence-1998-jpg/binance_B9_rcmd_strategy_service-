"""
数据处理 Pipeline v1.2
Step 1: 爬虫 → Step 2: 去重 → Step 3: LLM → Step 4: 聚合 → Step 5: 打分 → Step 6: 入库
"""
import os, json, math, hashlib, logging
import concurrent.futures as cf
from datetime import datetime, timezone
from pathlib import Path

import mysql.connector
from openai import OpenAI
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .sources import SECTOR_LABELS

logger = logging.getLogger(__name__)
_openai_client = None

def get_openai_client():
    global _openai_client
    if _openai_client is None:
        import os
        base_url = os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL")
        api_key = os.environ.get("OPENAI_API_KEY")
        kwargs = {"api_key": api_key} if api_key else {}
        if base_url:
            kwargs["base_url"] = base_url
        _openai_client = OpenAI(**kwargs)
    return _openai_client

RUMOR_LOG = Path(__file__).parent.parent / "logs" / "rumor_log.jsonl"
RUMOR_LOG.parent.mkdir(parents=True, exist_ok=True)

SECTOR_ENUM = SECTOR_LABELS

# ─── Step 2: 去重 ────────────────────────────────────────────────────────────

def deduplicate_raw(items: list[dict]) -> list[dict]:
    seen_urls = set()
    url_deduped = []
    for item in items:
        url = item.get("url", "").strip().rstrip("/")
        if url and url not in seen_urls:
            seen_urls.add(url)
            url_deduped.append(item)

    if len(url_deduped) <= 1:
        return url_deduped

    titles = [item.get("title", "") for item in url_deduped]
    try:
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
        mat = vec.fit_transform(titles)
        sim = cosine_similarity(mat)
    except Exception:
        return url_deduped

    keep = [True] * len(url_deduped)
    for i in range(len(url_deduped)):
        if not keep[i]:
            continue
        for j in range(i + 1, len(url_deduped)):
            if keep[j] and sim[i][j] > 0.85:
                if url_deduped[j].get("authority", 0) > url_deduped[i].get("authority", 0):
                    keep[i] = False
                    break
                else:
                    keep[j] = False

    result = [item for item, k in zip(url_deduped, keep) if k]
    logger.info(f"Dedup: {len(items)} → {len(result)}")
    return result


# ─── Step 3: LLM 结构化生成 ──────────────────────────────────────────────────

NEWS_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "news_event",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "title_en":             {"type": "string"},
                "title_zh":             {"type": "string"},
                "description_short_en": {"type": "string"},
                "description_short_zh": {"type": "string"},
                "description_long_en":  {"type": "string"},
                "description_long_zh":  {"type": "string"},
                "sectors": {"type": "array", "items": {"type": "string", "enum": SECTOR_ENUM}},
                "coins":   {"type": "array", "items": {"type": "string"}},
                "news_type": {"type": "string",
                              "enum": ["market","policy","security","project","macro","other"]},
                "event_tier": {"type": "string", "enum": ["S","A","B","C","D"]},
                "score_market_impact": {"type": "number"},
                "score_authority":     {"type": "number"},
                "score_quality":       {"type": "number"},
                "credibility_score":   {"type": "number"},
                "is_rumor":            {"type": "boolean"},
                "rumor_reason":        {"type": "string"},
            },
            "required": [
                "title_en","title_zh","description_short_en","description_short_zh",
                "description_long_en","description_long_zh","sectors","coins",
                "news_type","event_tier","score_market_impact","score_authority",
                "score_quality","credibility_score","is_rumor","rumor_reason"
            ],
            "additionalProperties": False,
        },
    },
}

SYSTEM_PROMPT = """You are a senior crypto news analyst for Binance's news recommendation system. Given a raw news item, output structured JSON.

## Output fields
- title_en: ≤15 words, factual, no clickbait
- title_zh: ≤25 characters, 简体中文
- description_short_en / description_short_zh: 50-100 words/characters, key facts with NUMBERS (amounts, prices, percentages, multiples)
- description_long_en / description_long_zh: 200-400 words/characters, full context + market implications
- sectors: ALL applicable Binance B9 sector labels from the enum
- coins: standard ticker symbols (BTC, ETH, SOL, DOGE...)
- news_type: market/policy/security/project/macro/other

## Event tier (5-level table, determines market impact M)
- S (M 0.85-1.0): sovereign-level regulation (US/EU/China crypto law), top exchange shutdown/collapse, BTC critical price breakout/breakdown
- A (M 0.60-0.84): institutional entry/exit (ETF flows, corporate treasury), major legislation progress, ETH critical breakout, top-exchange listing of a major asset, large-scale hack (>$50M)
- B (M 0.35-0.59): top-project major events (upgrade/tokenomics change/major partnership), mainstream coin sharp moves, notable smart-money moves tracked on-chain, sector-level catalysts (Launchpool new period, Megadrop, major airdrop), meme coin frenzy with real volume, mid-scale exploits
- C (M 0.15-0.34): mid-project events, on-chain data anomalies, small listings, routine ecosystem updates
- D (M 0.0-0.14): personnel changes, generic tech/AI news without crypto path, promotional/PR content, price-prediction opinion pieces

## HOT-TOPIC RECALL PRIORITY (never underrate these; they are the product's core value)
1. MEME momentum: new viral memes, celebrity/political tokens, meme sector volume surges → at least B if there is real trading volume or smart money involvement
2. Smart money / whale moves: lookonchain/spotonchain-style wallet tracking with concrete amounts → B or higher if amounts are large
3. Sector catalysts: Launchpool/Launchpad/Megadrop new period, big airdrops, mainnet launches, halvings, unlocks → B or higher
4. Tokenomics changes: buyback/burn, emission change, fee switch, supply shock → B or higher for top-100 projects
5. On-chain security: hacks, exploits, rugs, oracle attacks → A if >$50M, B if >$5M
6. Regulatory variables: SEC/CFTC actions, ETF decisions, national crypto policy → S/A per scale

## GENERIC-TECH FIREWALL
Generic AI/big-tech/stock-market news WITHOUT a clear crypto transmission path (requires ≥2 inference hops to affect crypto) → event_tier=D, score_market_impact ≤0.20. Examples: AI company fundraising, chip earnings, generic macro commentary. EXCEPTION: news about crypto-listed AI tokens (WLD, FET, TAO...), bStocks-relevant equities (tokenized stocks on Binance), or explicit crypto-market spillover keeps normal tiering.

## SECTOR-BOUNDARY rules (for `sectors` field)
- Track sectors (MEME/AI/Gaming/DeFi/NFT/RWA/Payments): tag only if a constituent coin or the track theme is the SUBJECT of the event
- Chain-ecosystem sectors (Solana/BSC/Layer1/Layer2): tag only if the chain itself or a top ecosystem project's major event; "merely deployed on that chain" does NOT count
- Platform-mechanism sectors (Launchpool/Launchpad/Megadrop/New Listing/bStocks/Seed): tag only for mechanism changes (new period/rules/yields) or constituent-project major events

## Scoring
- score_market_impact: within tier bounds above
- score_authority: official announcement=0.9+, top media (CoinDesk/TheBlock/吴说/BlockBeats)=0.75-0.89, mid media=0.50-0.74, aggregator/search=0.30-0.49, anonymous≤0.30; rumors ×0.7
- score_quality: 1.0 minus deductions (clickbait -0.2~0.5, PR/promotional -0.2~0.4, low info density -0.1~0.4); reward concrete numbers and multi-source facts
- credibility_score: 0=unverifiable, 1=officially confirmed
- is_rumor: true if unverifiable/speculative/"rumored/allegedly/据传/据悉/消息人士"
- rumor_reason: explain why, or empty string

Chinese newsflash items (快讯) are often the FIRST report of hot events — treat them as timely primary signals, not low-quality content."""


def enrich_one(item: dict) -> dict | None:
    user_content = (
        f"Source: {item.get('source','')}\n"
        f"Title: {item.get('title','')}\n"
        f"Summary: {item.get('summary','')[:600]}\n"
        f"URL: {item.get('url','')}\n"
        f"Published: {item.get('published_at','')}"
    )
    import time as _t
    last_err = None
    for attempt in range(5):  # 最多重试4次，429限流指数退避
        try:
            resp = get_openai_client().chat.completions.create(
                model="gpt-5.4",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format=NEWS_SCHEMA,
            )
            enriched = json.loads(resp.choices[0].message.content)
            enriched.update({
                "source":       item.get("source"),
                "url":          item.get("url"),
                "published_at": item.get("published_at"),
                "lang":         item.get("lang", "en"),
                "authority":    item.get("authority", 3),
                "type":         item.get("type", "rss"),
                "tweet_id":     item.get("tweet_id"),
            })
            return enriched
        except Exception as e:
            last_err = e
            msg = str(e)
            if "429" in msg or "rate_limited" in msg:
                _t.sleep(2 ** attempt + 1)  # 2/3/5/9/17s 退避
                continue
            if "402" in msg or "insufficient_credits" in msg:
                logger.error(f"LLM credits exhausted: {msg[:120]}")
                return None
            _t.sleep(1)
    logger.warning(f"LLM error (after retries) for {item.get('url','')}: {last_err}")
    return None


def enrich_batch(items: list[dict], max_workers: int = 4) -> list[dict]:
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(enrich_one, items))
    return [r for r in results if r is not None]


# ─── Step 4: 事件聚合 ────────────────────────────────────────────────────────

def aggregate_events(items: list[dict]) -> list[dict]:
    if not items:
        return []
    titles = [item.get("title_en", "") for item in items]
    try:
        vec = TfidfVectorizer(analyzer="word", ngram_range=(1, 2))
        mat = vec.fit_transform(titles)
        sim = cosine_similarity(mat)
    except Exception:
        return items

    assigned = [False] * len(items)
    groups = []
    for i in range(len(items)):
        if assigned[i]:
            continue
        group = [i]
        assigned[i] = True
        pub_i = items[i].get("published_at", "")
        for j in range(i + 1, len(items)):
            if assigned[j]:
                continue
            # 48h 时间窗口
            pub_j = items[j].get("published_at", "")
            try:
                ti = datetime.fromisoformat(pub_i.replace("Z", "+00:00"))
                tj = datetime.fromisoformat(pub_j.replace("Z", "+00:00"))
                if abs((ti - tj).total_seconds()) > 48 * 3600:
                    continue
            except Exception:
                pass
            if sim[i][j] > 0.65:
                group.append(j)
                assigned[j] = True
        groups.append(group)

    events = []
    for group in groups:
        group_items = [items[i] for i in group]
        primary = max(group_items, key=lambda x: x.get("authority", 0))

        sources = []
        seen_urls = set()
        for it in group_items:
            url = it.get("url", "")
            if url not in seen_urls:
                seen_urls.add(url)
                sources.append({
                    "name":         it.get("source", ""),
                    "url":          url,
                    "type":         it.get("type", "rss"),
                    "authority":    it.get("authority", 3),
                    "published_at": it.get("published_at", ""),
                    "x_tweet_id":   it.get("tweet_id"),
                })

        event = {**primary}
        event["sources"] = sources
        event["source_count"] = len(set(s["name"].split("/")[0] for s in sources))
        event["source_names"] = sorted(set(s["name"] for s in sources))
        event["is_verified"] = event["source_count"] >= 2
        event["merged_sources_count"] = len(group_items)
        event["cluster_id"] = hashlib.sha256(
            primary.get("title_en", "").encode()
        ).hexdigest()[:16]
        events.append(event)

    logger.info(f"Aggregate: {len(items)} → {len(events)} events")
    return events


# ─── Step 5: Macro Insight 打分 ──────────────────────────────────────────────

def compute_macro_score(event: dict) -> dict:
    # M：影响面（LLM 估算 + event_tier 边界约束）
    M = float(event.get("score_market_impact", 0.5))
    tier_bounds = {"S": (0.85, 1.0), "A": (0.60, 0.84),
                   "B": (0.35, 0.59), "C": (0.15, 0.34), "D": (0.0, 0.14)}
    lo, hi = tier_bounds.get(event.get("event_tier", "C"), (0.0, 1.0))
    M = max(lo, min(hi, M))

    # T：时效性（24h 半衰期指数衰减）
    try:
        pub = datetime.fromisoformat(event.get("published_at", "").replace("Z", "+00:00"))
        hours_ago = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
        T = math.exp(-hours_ago * math.log(2) / 24)
        T = max(0.0, min(1.0, T))
    except Exception:
        T = 0.5

    # H：热度（source_count log 压缩）
    sc = event.get("source_count", 1)
    H = min(1.0, math.log1p(sc) / math.log1p(5))

    # A：权威性（谣言打 7 折）
    A = float(event.get("score_authority", 0.5))
    if event.get("is_rumor", False):
        A = A * 0.7

    # Q：质量
    Q = float(event.get("score_quality", 0.5))

    score = 0.35 * M + 0.20 * T + 0.15 * H + 0.15 * A + 0.15 * Q

    return {
        "score_market_impact": round(M, 4),
        "score_timeliness":    round(T, 4),
        "score_hotness":       round(H, 4),
        "score_authority":     round(A, 4),
        "score_quality":       round(Q, 4),
        "importance_score":    round(score, 4),
    }


# ─── Step 6: 写入 MySQL ───────────────────────────────────────────────────────

def get_mysql_conn():
    return mysql.connector.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", 3306)),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", "***REMOVED***"),
        database=os.environ.get("MYSQL_DATABASE", "crypto_news"),
        charset="utf8mb4",
    )


def generate_event_id(title_en: str, date_str: str) -> str:
    raw = f"{title_en.lower().strip()}_{date_str}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _to_mysql_dt(value: str | None) -> str | None:
    """ISO8601 (含 T/Z/毫秒/时区) → MySQL DATETIME 'YYYY-MM-DD HH:MM:SS'"""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def write_to_mysql(events: list[dict], conn):
    cursor = conn.cursor()
    sql = """
    INSERT INTO news_events (
        id, title_en, title_zh, date, time_event, time_get_data,
        description_short_en, description_short_zh,
        description_long_en, description_long_zh,
        sectors, coins, news_type, event_tier,
        score_market_impact, score_timeliness, score_hotness,
        score_authority, score_quality, importance_score,
        credibility_score, is_rumor, rumor_reason,
        sources, source_names, source_count, is_verified, language_origin,
        cluster_id, merged_sources_count
    ) VALUES (
        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
    )
    ON DUPLICATE KEY UPDATE
        source_count         = GREATEST(source_count, VALUES(source_count)),
        source_names         = VALUES(source_names),
        is_verified          = (source_count >= 2),
        importance_score     = VALUES(importance_score),
        score_timeliness     = VALUES(score_timeliness),
        score_hotness        = VALUES(score_hotness),
        updated_at           = CURRENT_TIMESTAMP
    """
    now = datetime.now(timezone.utc)
    written = 0
    for event in events:
        date_str = (event.get("published_at") or "")[:10] or now.strftime("%Y-%m-%d")
        event_id = generate_event_id(event.get("title_en", ""), date_str)
        scores = compute_macro_score(event)
        try:
            cursor.execute(sql, (
                event_id,
                event.get("title_en", ""),
                event.get("title_zh", ""),
                date_str,
                _to_mysql_dt(event.get("published_at")),
                now.strftime("%Y-%m-%d %H:%M:%S"),
                event.get("description_short_en", ""),
                event.get("description_short_zh", ""),
                event.get("description_long_en", ""),
                event.get("description_long_zh", ""),
                json.dumps(event.get("sectors", []), ensure_ascii=False),
                json.dumps(event.get("coins", []), ensure_ascii=False),
                event.get("news_type", "other"),
                event.get("event_tier", "C"),
                scores["score_market_impact"],
                scores["score_timeliness"],
                scores["score_hotness"],
                scores["score_authority"],
                scores["score_quality"],
                scores["importance_score"],
                event.get("credibility_score", 0.5),
                bool(event.get("is_rumor", False)),
                event.get("rumor_reason", ""),
                json.dumps(event.get("sources", []), ensure_ascii=False),
                json.dumps(event.get("source_names", []), ensure_ascii=False),
                event.get("source_count", 1),
                bool(event.get("is_verified", False)),
                event.get("lang", "en"),
                event.get("cluster_id", ""),
                event.get("merged_sources_count", 1),
            ))
            written += 1
        except Exception as e:
            logger.warning(f"MySQL write error for {event.get('title_en','')}: {e}")
    conn.commit()
    cursor.close()
    logger.info(f"MySQL: wrote {written} events")
    return written


def write_x_raw_posts(posts: list[dict], conn):
    """X 原始推文落 x_raw_posts 表"""
    if not posts:
        return 0
    cursor = conn.cursor()
    sql = """
    INSERT INTO x_raw_posts (
        tweet_id, kol_username, kol_display_name, kol_followers_count,
        kol_verified, kol_profile_url, tweet_title, tweet_body, tweet_url,
        tweet_lang, like_count, retweet_count, reply_count, quote_count,
        impression_count, published_at
    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE
        like_count=VALUES(like_count), retweet_count=VALUES(retweet_count),
        reply_count=VALUES(reply_count), quote_count=VALUES(quote_count),
        impression_count=VALUES(impression_count), fetched_at=CURRENT_TIMESTAMP
    """
    written = 0
    for p in posts:
        try:
            pub = (p.get("published_at") or "").replace("T", " ").replace("Z", "")[:19] or None
            cursor.execute(sql, (
                p["tweet_id"], p["kol_username"], p.get("kol_display_name", ""),
                p.get("kol_followers_count", 0), bool(p.get("kol_verified", False)),
                p.get("kol_profile_url", ""), p.get("tweet_title", ""),
                p.get("tweet_body", ""), p.get("tweet_url", ""),
                p.get("tweet_lang", "en"), p.get("like_count", 0),
                p.get("retweet_count", 0), p.get("reply_count", 0),
                p.get("quote_count", 0), p.get("impression_count", 0), pub,
            ))
            written += 1
        except Exception as e:
            logger.warning(f"x_raw_posts write error {p.get('tweet_id')}: {e}")
    conn.commit()
    cursor.close()
    logger.info(f"MySQL: wrote {written} x_raw_posts")
    return written


# ─── 完整 Pipeline 入口 ──────────────────────────────────────────────────────

def run_pipeline() -> dict:
    import time as _time
    start = _time.time()
    conn = get_mysql_conn()
    run_cursor = conn.cursor()
    stats = {"raw": 0, "deduped": 0, "enriched": 0, "events": 0, "rumors": 0}

    try:
        from .main import run_rss_and_scraper_crawler

        # Step 1
        raw_items, x_raw_posts = run_rss_and_scraper_crawler()
        stats["raw"] = len(raw_items)
        logger.info(f"Step 1: {stats['raw']} raw items")

        # Step 1.5: X 原始推文落表
        write_x_raw_posts(x_raw_posts, conn)

        # Step 2
        deduped = deduplicate_raw(raw_items)
        stats["deduped"] = len(deduped)

        # Step 3
        enriched = enrich_batch(deduped, max_workers=4)
        stats["enriched"] = len(enriched)
        stats["rumors"] = sum(1 for e in enriched if e.get("is_rumor"))
        logger.info(f"Step 3: {stats['enriched']} enriched, {stats['rumors']} rumors (kept)")

        # Step 4
        events = aggregate_events(enriched)
        stats["events"] = len(events)

        # Step 6
        write_to_mysql(events, conn)

        duration = round(_time.time() - start, 2)
        run_cursor.execute(
            "INSERT INTO pipeline_runs (raw_count,deduped_count,enriched_count,events_count,rumors_count,duration_seconds,status) VALUES (%s,%s,%s,%s,%s,%s,'success')",
            (stats["raw"], stats["deduped"], stats["enriched"], stats["events"], stats["rumors"], duration)
        )
        conn.commit()
        logger.info(f"Pipeline done in {duration}s: {stats}")

    except Exception as e:
        duration = round(_time.time() - start, 2)
        logger.error(f"Pipeline error: {e}")
        try:
            run_cursor.execute(
                "INSERT INTO pipeline_runs (duration_seconds,status,error_msg) VALUES (%s,'error',%s)",
                (duration, str(e))
            )
            conn.commit()
        except Exception:
            pass
        raise
    finally:
        run_cursor.close()
        conn.close()

    return stats
