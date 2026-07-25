"""
数据处理 Pipeline v2.0

    抓取 → 粗去重 → LLM 结构化 → 语义聚合 → 社交信号 → 跨轮归并 → 打分 → 入库

本模块负责 LLM 结构化与整体编排；去重逻辑在 dedup.py，打分在 scoring.py，
读写库在 storage.py。

v2.0 相对 v1.2 的改动集中在去重（详见 dedup.py 头部说明）：
  1. 事件 id 改由稳定三元组指纹派生，不再 hash LLM 改写后的标题
  2. 语义聚合从 TF-IDF 词频换成真 embedding
  3. 新增跨轮归并，堵住 cron 每轮重复插入的口子
另外 H 因子接入了 X 社交互动信号（此前只有信源数）。
"""
import concurrent.futures as cf
import json
import logging
import os
import time
from pathlib import Path

from openai import OpenAI
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import storage
from .dedup import aggregate_events, build_fingerprint, fallback_id
from .scoring import score_events
from .sources import SECTOR_LABELS
from .usage_tracker import UsageTracker
from .verification import persist_verification, verify_events

logger = logging.getLogger(__name__)

LLM_MODEL = "gpt-5.4"
LLM_WORKERS = 4          # 并发度。OpenAI 官方 key TPM 500k，4 并发无限流压力
LLM_MAX_RETRIES = 5

RUMOR_LOG = Path(__file__).parent.parent / "logs" / "rumor_log.jsonl"
RUMOR_LOG.parent.mkdir(parents=True, exist_ok=True)

_openai_client = None


def get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        kwargs = {}
        if api_key := os.environ.get("OPENAI_API_KEY"):
            kwargs["api_key"] = api_key
        if base_url := (os.environ.get("OPENAI_API_BASE") or
                        os.environ.get("OPENAI_BASE_URL")):
            kwargs["base_url"] = base_url
        _openai_client = OpenAI(**kwargs)
    return _openai_client


# ── Step 2: 粗去重（LLM 前的省钱预过滤）──────────────────────────────

def prefilter_duplicates(items: list[dict], threshold: float = 0.85) -> list[dict]:
    """按 URL 与标题字面相似度做粗筛，纯粹为了少花 LLM 的钱。

    注意这**不是**真正的去重——字面相似度抓不住同义改写，真去重在 LLM 之后由
    dedup.aggregate_events 用语义向量完成。这里阈值定得高（0.85），宁可漏放也不
    误杀：误杀一条就是永久丢失召回。
    """
    seen_urls, url_deduped = set(), []
    for item in items:
        url = item.get("url", "").strip().rstrip("/")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        url_deduped.append(item)

    if len(url_deduped) <= 1:
        return url_deduped

    try:
        # char_wb n-gram：对中文和英文都能工作，且对轻微改写有一定容忍
        matrix = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4)).fit_transform(
            [item.get("title", "") for item in url_deduped]
        )
        sim = cosine_similarity(matrix)
    except ValueError:
        return url_deduped

    keep = [True] * len(url_deduped)
    for i in range(len(url_deduped)):
        if not keep[i]:
            continue
        for j in range(i + 1, len(url_deduped)):
            if not keep[j] or sim[i][j] <= threshold:
                continue
            # 同一事件保留权威更高的信源
            if url_deduped[j].get("authority", 0) > url_deduped[i].get("authority", 0):
                keep[i] = False
                break
            keep[j] = False

    result = [item for item, k in zip(url_deduped, keep) if k]
    logger.info(f"Prefilter: {len(items)} → {len(result)}")
    return result


# ── Step 3: LLM 结构化 ───────────────────────────────────────────────

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
                "sectors": {"type": "array", "items": {"type": "string", "enum": SECTOR_LABELS}},
                "coins":   {"type": "array", "items": {"type": "string"}},
                "news_type": {"type": "string",
                              "enum": ["market", "policy", "security", "project", "macro", "other"]},
                "event_tier": {"type": "string", "enum": ["S", "A", "B", "C", "D"]},
                # 事件指纹三元组 —— 去重的第一道网，见 dedup.build_fingerprint
                "event_subject": {"type": "string"},
                "event_action":  {"type": "string"},
                "event_date":    {"type": "string"},
                "score_market_impact": {"type": "number"},
                "score_authority":     {"type": "number"},
                "score_quality":       {"type": "number"},
                "credibility_score":   {"type": "number"},
                "is_rumor":            {"type": "boolean"},
                "rumor_reason":        {"type": "string"},
            },
            "required": [
                "title_en", "title_zh", "description_short_en", "description_short_zh",
                "description_long_en", "description_long_zh", "sectors", "coins",
                "news_type", "event_tier", "event_subject", "event_action", "event_date",
                "score_market_impact", "score_authority", "score_quality",
                "credibility_score", "is_rumor", "rumor_reason",
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

## EVENT FINGERPRINT — read this carefully, it drives de-duplication
`event_subject`, `event_action` and `event_date` identify WHICH REAL-WORLD EVENT this item
reports. Two articles covering the same event MUST produce IDENTICAL values for all three,
even when written in different languages, by different outlets, with different wording.
You are not describing this article — you are naming the underlying event.

- event_subject: the main actor or object, as a lowercase snake_case English slug.
  Use the CANONICAL name, never the article's exact phrasing. Normalize aggressively:
    * coins by ticker, not full name: bitcoin→btc, ethereum→eth, solana→sol
    * drop outlet-specific adjectives, dates and figures from the subject
    * drop person names when a role is the real subject
  Examples:
    "美国比特币以太坊现货ETF" / "U.S. spot BTC and ETH ETFs" → us_spot_btc_eth_etf
    "Robinhood CEO Vlad Tenev's X account" / "Robinhood 首席执行官社媒" → robinhood_ceo
    "币安" / "Binance exchange" → binance

- event_action: what happened, lowercase snake_case English slug. Strongly prefer this
  controlled vocabulary; only invent a slug when nothing fits:
    net_outflow, net_inflow, hacked, exploited, scam_promotion, listed, delisted,
    launched, acquired, invested, raised_funding, partnership, upgrade, lawsuit,
    fined, approved, rejected, banned, resigned, appointed, price_surge, price_drop,
    unlock, burn, buyback, shutdown, outage, announcement, report, forecast

- event_date: the date the EVENT occurred (NOT the publish date), YYYY-MM-DD.
  If the text says "on July 24", use that date. If the event date is unclear, use the
  publish date. Never leave this empty.

Worked example — these two headlines describe ONE event and must produce identical triples:
  "US Spot Bitcoin, Ether ETFs See $310.6M Net Outflows on July 24"
  "U.S. spot BTC and ETH ETFs post July 24 outflows"
  → subject=us_spot_btc_eth_etf, action=net_outflow, date=2026-07-24

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


def enrich_one(item: dict, tracker=None) -> dict | None:
    """单条 LLM 结构化。429 指数退避重试，402 立即放弃。

    `tracker`（crawler.usage_tracker.UsageTracker）记录本次调用的 token 用量，
    供成本监控使用；不传则跳过记录，不影响结构化本身。
    """
    user_content = (
        f"Source: {item.get('source', '')}\n"
        f"Title: {item.get('title', '')}\n"
        f"Summary: {item.get('summary', '')[:600]}\n"
        f"URL: {item.get('url', '')}\n"
        f"Published: {item.get('published_at', '')}"
    )

    last_error = None
    for attempt in range(LLM_MAX_RETRIES):
        try:
            resp = get_openai_client().chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format=NEWS_SCHEMA,
            )
            if tracker is not None:
                tracker.record_chat(getattr(resp, "usage", None))
            enriched = json.loads(resp.choices[0].message.content)
            # 保留原始抓取元数据，后续聚合/打分要用
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
            last_error = e
            message = str(e)
            if "429" in message or "rate_limited" in message:
                time.sleep(2 ** attempt + 1)   # 2 / 3 / 5 / 9 / 17 秒
                continue
            if "402" in message or "insufficient_credits" in message:
                logger.error(f"LLM credits exhausted: {message[:120]}")
                return None
            time.sleep(1)

    logger.warning(f"LLM failed after retries [{item.get('url', '')}]: {last_error}")
    return None


def enrich_batch(items: list[dict], max_workers: int = LLM_WORKERS, tracker=None) -> list[dict]:
    with cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(lambda item: enrich_one(item, tracker), items))
    return [r for r in results if r is not None]


def attach_fingerprints(items: list[dict]) -> None:
    """给每条 enriched 条目算事件指纹。

    LLM 没给出可用三元组时回退到旧的标题 hash——这条自身就失去跨轮归并能力，
    但仍有 embedding 语义层兜底，不会整条漏掉。
    """
    missing = 0
    for item in items:
        fingerprint = build_fingerprint(
            item.get("event_subject", ""),
            item.get("event_action", ""),
            item.get("event_date", "") or (item.get("published_at") or "")[:10],
        )
        if not fingerprint:
            missing += 1
            fingerprint = fallback_id(
                item.get("title_en", ""), (item.get("published_at") or "")[:10]
            )
        item["event_fingerprint"] = fingerprint

    if missing:
        logger.warning(f"{missing}/{len(items)} items lacked a usable event triple")


# ── Pipeline 编排 ────────────────────────────────────────────────────

def run_pipeline() -> dict:
    """跑完整一轮，返回各阶段水位统计。"""
    from .main import run_rss_and_scraper_crawler

    start = time.time()
    conn = storage.get_mysql_conn()
    stats = {"raw": 0, "deduped": 0, "enriched": 0, "events": 0,
             "rumors": 0, "merged": 0}
    tracker = UsageTracker()  # 本轮 OpenAI 用量，见 usage_tracker.py

    try:
        # 1. 抓取
        raw_items, x_raw_posts = run_rss_and_scraper_crawler()
        stats["raw"] = len(raw_items)
        logger.info(f"Step 1 crawl: {stats['raw']} raw items")

        # 2. X 推文落表（必须早于事件写库，H 因子要读回互动量）
        storage.write_x_posts(x_raw_posts, conn)

        # 3. 粗去重（省 LLM 成本）
        deduped = prefilter_duplicates(raw_items)
        stats["deduped"] = len(deduped)

        # 4. LLM 结构化
        enriched = enrich_batch(deduped, tracker=tracker)
        stats["enriched"] = len(enriched)
        stats["rumors"] = sum(1 for e in enriched if e.get("is_rumor"))
        logger.info(f"Step 4 LLM: {stats['enriched']} enriched, "
                    f"{stats['rumors']} flagged as rumor (kept, down-weighted)")

        # 5. 事件指纹 + 语义聚合（DC-1 ~ DC-3）
        attach_fingerprints(enriched)
        events = aggregate_events(enriched, get_openai_client(), tracker=tracker)
        stats["events"] = len(events)

        # 6. 跨轮归并（DC-4）。命中既有行的事件会复用其 id，写库时走 UPDATE 分支
        recent = storage.load_recent_events(conn)
        events, stats["merged"] = storage.merge_with_existing(events, recent)
        stats["events"] = len(events)

        # 7. 社交互动信号（喂给 H 因子）。必须放在归并之后：归并会合并 sources，
        #    在合并后的完整推文集合上统计，互动量才不会漏算
        storage.attach_social_metrics(events, conn)

        # 7.5 真实性校验（DC 之外的另一道闸）。全部基于客观信号——按机构去重后的
        #     独立佐证数、信源可信度分层、时间一致性、矛盾检测——零 LLM 调用。
        #     必须在打分之前：compute_authority 会用到校验结论做降权。
        verification_stats = verify_events(events, conn=conn)
        stats["unverified"] = (verification_stats.get("UNVERIFIED", 0)
                               + verification_stats.get("DISPUTED", 0))
        logger.info(f"Step 7.5 verification: {verification_stats}")

        # 8. 打分 + 入库
        score_events(events)
        storage.write_events(events, conn)

        # 9. 校验结论落库。必须在 write_events 之后——它是 UPDATE，行得先存在
        persist_verification(events, conn)

        duration = round(time.time() - start, 2)
        tracker.log_summary()
        storage.record_run(conn, stats, duration, usage=tracker.snapshot())
        logger.info(f"Pipeline done in {duration}s: {stats}")

    except Exception as e:
        duration = round(time.time() - start, 2)
        logger.error(f"Pipeline failed: {e}")
        tracker.log_summary()
        storage.record_run(conn, stats, duration, status="error", error=str(e),
                          usage=tracker.snapshot())
        raise
    finally:
        conn.close()

    return stats
