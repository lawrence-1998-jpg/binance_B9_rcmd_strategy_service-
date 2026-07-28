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
from .dedup import (COSINE_THRESHOLD, aggregate_events, build_fingerprint,
                    embed_texts, fallback_id)
from .market_cap import annotate_events as annotate_market_cap
from .market_cap import persist_coin_metrics
from .scoring import score_events
from .sources import SECTOR_LABELS
from .usage_tracker import UsageTracker
from .verification import persist_verification, verify_events

logger = logging.getLogger(__name__)

LLM_MODEL = "gpt-5.4"
# 2026-07-28：曾尝试切到公司 LiteLLM 网关（config/.env 有完整记录），已回退——
# 网关地址 litellm.devfdg.net 解析到私网 IP（172.21.x.x，内部 ELB），只有在
# Binance 内网/VPN 上的机器能连通，这台跑生产 pipeline 的 GCP VM 连不上（DNS
# 都解析不出来，不是防火墙拦截，无法绕过）。现状：仍用直连 OpenAI 的个人账号
# key。若要真正切网关，需要网关方把服务开放给公网/VM 所在网段，或者把 pipeline
# 挪到能连通内网的机器上跑——这两者都不是"改几行 env"能解决的，需要用户判断。
# 另外网关上的 claude-opus-4-8 实测经 Bedrock 通道不支持这里依赖的
# response_format strict json_schema，即使网络问题解决，换模型前也需要先验证
# schema 兼容性。
# 降级模型：只给"信息已经结构化、不需要判断力"的条目用，不是给"低权威"条目用——
# 低权威信源（匿名X贴、聚合搜索结果）恰恰是谣言甄别、事件分级最需要判断力的地方，
# 权威度低不等于任务简单，两者不能划等号。真正简单的是 market_signal（行情异动，
# 数据播报模板生成，见 crawler/market_signals.py:_item）和 calendar（CoinMarketCal
# 日历条目，见 crawler/main.py 的 summary 拼接）—— 这两类内容本身就是模板化数据，
# LLM 只是把已知数字套进 schema，不涉及谣言判断/事件定性等需要推理的工作。
LLM_MODEL_LITE = "gpt-5.4-nano"
LLM_LITE_TYPES = {"market_signal", "calendar"}
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


def semantic_prefilter(items: list[dict], client, tracker=None,
                       threshold: float = None) -> list[dict]:
    """LLM **之前**的语义级粗去重（2026-07-28 新增）。

    起因：Lawrence 要求"通过一些简单的预处理把一样的内容前置识别掉，不要所有的
    东西都过模型，避免重复浪费"。上面的 `prefilter_duplicates` 用的是字符 n-gram
    TF-IDF，实测在 800 条真实积压上只压掉 18%，而且把阈值从 0.85 一路降到 0.60
    也只多压 3.6%——不是阈值没调好，是**字面相似度天然抓不住两类重复**：
      · 跨语言："Metaplanet acquires Siiibo Securities" 与
        "Metaplanet 收购 Siiibo Securities" 字面重合接近 0
      · 同事件改写："日经指数因芯片股大跌超3%" 与 "日经跌3.6%，芯片股重挫"
    embedding 两种都能抓（上面两例实测相似度 0.826 / 0.93）。

    成本对比是这件事成立的关键：text-embedding-3-small 每条标题约 20 token，
    1000 条约 $0.0004；而一次 LLM 结构化约 $0.011/条。**用 embedding 挡掉一条
    重复，省下的钱是它自身成本的两万多倍**，所以这一步近似免费。

    阈值复用 dedup.COSINE_THRESHOLD（0.82）——那是本项目在 855 条真实事件、
    28 万配对上标定过的"同一事件"分界点（见 dedup.py 文件头），不另起一套。
    实测 800 条积压：TF-IDF 后 656 条 → 本步后 594 条，总压缩率 18% → 25.7%，
    抽样 6 组合并簇人工核对全部为真重复。

    失败即放行：embedding 调用出错时原样返回，宁可多花 LLM 的钱也不丢召回
    （与 dedup.embed_texts 的零矩阵降级语义不同——那边零向量互不归簇是安全的，
    这里如果拿到零矩阵会让所有条目两两相似度为 0，反而不会误杀，但仍显式兜底）。
    """
    if len(items) <= 1:
        return items
    threshold = COSINE_THRESHOLD if threshold is None else threshold

    try:
        vectors = embed_texts([i.get("title", "") for i in items], client, tracker=tracker)
    except Exception as e:
        logger.warning(f"语义粗去重跳过（embedding 失败，原样放行不丢召回）：{e}")
        return items
    if getattr(vectors, "size", 0) == 0:
        return items

    sim = vectors @ vectors.T
    keep = [True] * len(items)
    folded = 0
    for i in range(len(items)):
        if not keep[i]:
            continue
        for j in range(i + 1, len(items)):
            if not keep[j] or sim[i][j] <= threshold:
                continue
            # 与 prefilter_duplicates 同一口径：同一事件保留权威更高的信源
            if items[j].get("authority", 0) > items[i].get("authority", 0):
                keep[i] = False
                folded += 1
                break
            keep[j] = False
            folded += 1

    result = [it for it, k in zip(items, keep) if k]
    logger.info(f"语义粗去重（LLM 前）: {len(items)} → {len(result)}，"
                f"折叠 {folded} 条重复，按 $0.011/条估算省下约 ${folded * 0.011:.2f}")
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
                # description_long 只产中文（2026-07-26 起）：英文长文没有下游消费方
                # （前端只展示中文长文，详见 web/index.html 的 description_long_zh
                # 取值逻辑），且是 output token 里最大的一块，砍掉即减负载又降成本。
                "description_long_zh":  {"type": "string"},
                # sector_tags 取代了原来的 sectors 字符串数组：每个板块必须附相关度
                # 与判定锚点，这是产品要求的「真相关才打」的量化落地。对外的
                # `sectors` 列由 filter_sector_tags() 按阈值过滤生成，前端不变。
                "sector_tags": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "sector":    {"type": "string", "enum": SECTOR_LABELS},
                            "relevance": {"type": "number"},
                            "anchor":    {"type": "string"},
                        },
                        "required": ["sector", "relevance", "anchor"],
                        "additionalProperties": False,
                    },
                },
                "coins":   {"type": "array", "items": {"type": "string"}},
                # 结构化实体。比 coins 丰富：人物/机构/项目/公链/地区/产品都进来，
                # 供前端做实体聚合页与「同一主体的历史新闻」召回。
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {"type": "string",
                                     "enum": ["person", "organization", "project",
                                              "chain", "region", "product"]},
                        },
                        "required": ["name", "type"],
                        "additionalProperties": False,
                    },
                },
                # 情绪 = 对市场的方向性影响，不是文章语气
                "sentiment":       {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
                "sentiment_score": {"type": "number"},
                "impact_horizon":  {"type": "string",
                                    "enum": ["immediate", "short_term",
                                             "medium_term", "long_term"]},
                "news_type": {"type": "string",
                              "enum": ["market", "policy", "security", "project", "macro", "other"]},
                # 2026-07-28 新增：市场归属，与 news_type 正交（news_type 判事件性质，
                # market_scope 判属于哪个市场）。见 SYSTEM_PROMPT 的 MARKET SCOPE 章节。
                "market_scope": {"type": "string",
                                 "enum": ["crypto", "us_stock", "hk_stock", "jp_stock",
                                          "kr_stock", "macro_policy", "general"]},
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
                "description_long_zh", "sector_tags", "coins",
                "entities", "sentiment", "sentiment_score", "impact_horizon",
                "news_type", "market_scope", "event_tier", "event_subject", "event_action", "event_date",
                "score_market_impact", "score_authority", "score_quality",
                "credibility_score", "is_rumor", "rumor_reason",
            ],
            "additionalProperties": False,
        },
    },
}

SYSTEM_PROMPT = """You are a senior financial news analyst for Binance's news recommendation system. The product covers BOTH crypto markets AND the global macro/equity markets that move crypto sentiment and that the same users trade (US/HK/Japan/Korea stocks, central bank policy, tariffs/trade, major economic data) — think Robinhood-style "one feed for everything that moves the prices I hold", not a crypto-only trade rag. Given a raw news item, output structured JSON.

## Output fields
- title_en: ≤15 words, factual, no clickbait
- title_zh: ≤25 characters, 简体中文
- description_short_en / description_short_zh: 50-100 words/characters, key facts with NUMBERS (amounts, prices, percentages, multiples)
- description_long_zh: 中文长文本，字数上限按 event_tier 分档，是硬上限不是参考值：
    * S/A 档：≤300字，完整背景 + 市场含义
    * B 档：≤160字，关键背景 + 一句影响判断
    * C/D 档：≤80字，只写结论性事实，不做背景铺垫、不做传导路径分析、不用修饰句
  D 档不需要论证"为什么这与加密关系不大"，一句话说清"发生了什么"即可，不用展开
  地缘政治/宏观逻辑分析。
  这个字段只输出成文，绝对不要出现任何关于分档/字数/判断过程本身的文字（例如
  "先定档位""字数已控制在xx档""按规则应归为……"这类元话语一律不许出现，直接
  写事件内容本身）。
- market_scope: see MARKET SCOPE rules below — which market this event belongs to
- sector_tags: see SECTOR-BOUNDARY rules below — scored, evidence-backed, AT MOST 3.
  Only applies to crypto-sector relevance; empty array is the CORRECT and EXPECTED output
  for market_scope ≠ crypto items unless the item also has a direct, named crypto angle
- coins: see COIN TICKER rules below. Empty array is correct when the item names no crypto asset
- entities / sentiment / sentiment_score / impact_horizon: see CONTENT TAGS below
- news_type: market/policy/security/project/macro/other

## MARKET SCOPE (for `market_scope`) — which market does this event belong to
- crypto: the event is about crypto assets, protocols, exchanges, or crypto-specific regulation
- us_stock: US equities, indices (S&P 500/Nasdaq/Dow), Fed policy, US CPI/jobs data, US-listed
  company earnings/M&A — even when it has no crypto angle at all
- hk_stock: Hong Kong equities, Hang Seng Index, HK-listed company events
- jp_stock: Japan equities, Nikkei/TOPIX, Bank of Japan policy, yen moves
- kr_stock: Korea equities, KOSPI/KOSDAQ, Korean won moves
- macro_policy: cross-border/global economic policy that does not belong to one specific
  market above — tariffs and trade wars, G7/G20 decisions, global central bank coordination,
  major sovereign credit events, oil/commodity shocks with broad market effect
- general: does not fit any of the above but still belongs on this product (rare; prefer a
  specific value whenever one plausibly fits)

Do NOT tag mainland China A-share content (Shanghai/Shenzhen Composite, ChiNext, individual
A-share tickers) with any value — this content should not reach you at all (filtered upstream);
if it slips through, classify as macro_policy ONLY if the story is about broad Chinese economic
policy (PBOC rate moves, GDP, tariffs affecting global markets), never if it is about specific
A-share index levels or individual mainland-listed stocks.

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
For market_scope=crypto items, use the crypto-specific ladder:
- S (M 0.85-1.0): sovereign-level regulation (US/EU/China crypto law), top exchange shutdown/collapse, BTC critical price breakout/breakdown
- A (M 0.60-0.84): institutional entry/exit (ETF flows, corporate treasury), major legislation progress, ETH critical breakout, top-exchange listing of a major asset, large-scale hack (>$50M)
- B (M 0.35-0.59): top-project major events (upgrade/tokenomics change/major partnership), mainstream coin sharp moves, notable smart-money moves tracked on-chain, sector-level catalysts (Launchpool new period, Megadrop, major airdrop), meme coin frenzy with real volume, mid-scale exploits
- C (M 0.15-0.34): mid-project events, on-chain data anomalies, small listings, routine ecosystem updates
- D (M 0.0-0.14): personnel changes, promotional/PR content, price-prediction opinion pieces. (An item that is really about equities/macro belongs in another market_scope with its own ladder — do NOT dump it here just because it lacks a crypto angle; see CLASSIFY FIRST below.)

For market_scope=us_stock/hk_stock/jp_stock/kr_stock/macro_policy items, use this SEPARATE
ladder — score by magnitude of impact on THAT market / on global sentiment, not by crypto
transmission (the GENERIC-TECH FIREWALL below does NOT apply to these items):
- S (M 0.85-1.0): national index single-day move ≥4% (or circuit-breaker-level moves like
  ≥7-8% in an Asian market), surprise central bank emergency action, market-wide crash/panic
  ("Black Monday"-style multi-market selloff), sovereign default or credit crisis
- A (M 0.60-0.84): scheduled central bank rate decision (esp. surprise/off-consensus), major
  index move 2-4%, major tariff/trade-war escalation, mega-cap earnings shock moving the
  whole index, key inflation/jobs print that beats/misses sharply
- B (M 0.35-0.59): single large-cap earnings (non-index-moving), sector rotation, notable but
  contained index move (1-2%), routine but market-relevant central bank commentary
- C (M 0.15-0.34): routine data prints in line with expectations, single-stock news without
  broad market effect, analyst notes/price targets
- D (M 0.0-0.14): opinion/commentary pieces, evergreen explainers, PR/promotional content

## HOT-TOPIC RECALL PRIORITY (never underrate these; they are the product's core value)
1. MEME momentum: new viral memes, celebrity/political tokens, meme sector volume surges → at least B if there is real trading volume or smart money involvement
2. Smart money / whale moves: lookonchain/spotonchain-style wallet tracking with concrete amounts → B or higher if amounts are large
3. Sector catalysts: Launchpool/Launchpad/Megadrop new period, big airdrops, mainnet launches, halvings, unlocks → B or higher
4. Tokenomics changes: buyback/burn, emission change, fee switch, supply shock → B or higher for top-100 projects
5. On-chain security: hacks, exploits, rugs, oracle attacks → A if >$50M, B if >$5M
6. Regulatory variables: SEC/CFTC actions, ETF decisions, national crypto policy → S/A per scale

## CLASSIFY FIRST, THEN SCORE — order matters, do not skip this
Decide `market_scope` BEFORE deciding `event_tier`. A story about chip stocks, AI companies,
tariffs, central banks, earnings, or an equity index is us_stock / hk_stock / jp_stock /
kr_stock / macro_policy — it is NOT "a crypto item with no crypto angle". Misclassifying such
a story as market_scope=crypto and then penalising it for lacking a crypto angle is the single
worst failure mode of this system: it silently buries exactly the mainstream-market news the
product now exists to surface. When in doubt between crypto and a market scope, pick the market
scope — the product wants this content.

Mainstream market news is FIRST-CLASS content here, not crypto-adjacent color commentary.
Score it on the non-crypto ladder above, on its own merits. Do not force sector_tags/coins
onto it; empty arrays are the correct output unless the item genuinely names a crypto asset
or protocol. Never assign a low tier to a genuinely significant market/macro story merely
because it has no crypto transmission path — significance to ITS OWN market is the criterion.

## LOW-VALUE FILTER — applies to ALL scopes
Regardless of market_scope, these get event_tier=D, score_market_impact ≤0.20:
opinion/commentary with no new facts, evergreen explainers, PR/promotional content,
price-prediction pieces, and content with no market relevance at all (sports, entertainment,
local human-interest). This is about the item being LOW-INFORMATION, never about which market
it belongs to.

For market_scope=crypto items specifically, one extra rule: an item framed as crypto news that
actually just recycles generic AI/big-tech/equity news with no crypto transmission path is D —
but first re-check whether it should simply have been classified as us_stock/macro_policy
instead (per CLASSIFY FIRST above); that is usually the right answer. EXCEPTION: news about
crypto-listed AI tokens (WLD, FET, TAO...), bStocks-relevant equities (tokenized stocks on
Binance), or explicit crypto-market spillover keeps normal tiering.

## SECTOR-BOUNDARY rules (for `sector_tags`) — TAG ONLY WHAT IS GENUINELY RELATED
Over-tagging is the single most damaging failure mode of this system: a wrong sector tag
routes the item into a feed where it does not belong, and users lose trust in the whole
sector view. An empty `sector_tags` array is a perfectly good answer and is much better
than a plausible-looking wrong tag. Most news items deserve 0 or 1 sector tag.

Hard limits: AT MOST 3 tags. Never emit a tag whose relevance would be below 0.55.

For every tag you MUST fill `anchor` — the concrete coin ticker, project name, chain, or
platform mechanism PRESENT IN THIS ITEM that justifies the tag (≤4 words).
If you cannot name a specific anchor from the item's own text, the tag is wrong: drop it.
"the topic feels related", "crypto in general", "market sentiment" are NOT valid anchors.

`relevance` scale (0-1), same rubric as the downstream sector-recommendation skill:
- 0.90-1.00  a constituent asset / the sector mechanism IS the subject of the event
             (e.g. "Binance opens new Launchpool period" → Launchpool 0.95, anchor="Launchpool new period")
- 0.70-0.89  the event directly changes the sector's fundamentals, flows or rules, and a
             named constituent is involved (e.g. "PNUT surges 60% on volume spike" → MEME 0.8)
- 0.55-0.69  the sector is materially affected but is NOT the subject; a named constituent
             appears only as context (e.g. a DeFi-wide TVL report that names Aave → DeFi 0.6)
- below 0.55 mere mention, adjacency, or thematic vibe → DO NOT OUTPUT

Transmission-hop caps (these OVERRIDE the scale above):
- 1 hop (event touches a constituent asset/mechanism directly): no cap
- 1 hop but the asset is NOT a constituent of that sector: cap 0.55
- 2+ hops (equity markets, Web2 tech, macro mood, "narrative feels similar"): cap 0.40
  → which means the tag is dropped. This is the intended outcome.

Two labels are chronic over-tagging magnets — treat them as NARROW, not as catch-alls:
- Infrastructure = L1 base layer / oracles / cross-chain messaging / node & data infra
  ONLY. It is NOT "anything technical". An exchange outage, a wallet feature, a payment
  integration, a hack of an app-layer protocol are NOT Infrastructure.
- Monitoring = on-chain monitoring & alerting as the sector theme (whale / exploit tracking
  products and their assets). A single security firm being quoted in a story does NOT make
  the story a Monitoring event.

Boundary anchors per sector family (unchanged, these decide WHETHER a tag is admissible
at all — the relevance score then decides how strongly):
- Track sectors (MEME/AI/Gaming/NFT/RWA/Payments/DeFi/Infrastructure/tCommodities/Fan Token):
  tag only if a constituent coin or the track theme is the SUBJECT of the event
- Chain-ecosystem sectors (Solana/BSC/Layer1/Layer2): tag only if the chain itself or a top
  ecosystem project has a major event; "merely deployed on that chain" does NOT count
- Platform-mechanism sectors (Launchpool/Launchpad/Megadrop/New Listing/bStocks/Seed/Monitoring):
  tag only for mechanism changes (new period/rules/yields) or constituent-project major events

Worked NEGATIVE examples — these must produce ZERO sector tags:
- "OpenAI raises $40B at $300B valuation" → not AI (no crypto AI-token anchor; AI sector
  means crypto AI tokens like WLD/FET/TAO, not AI companies)
- "Fed holds rates steady, BTC dips 2%" → not any sector (macro; BTC is not a sector)
- "SEC delays decision on a spot XRP ETF" → not Payments, not RWA (regulatory event about
  one asset; XRP being a payments coin does not make an ETF ruling a Payments-sector event)
- "Solana-based DEX raises $5M seed round" → not Seed (the Seed sector is Binance's Seed Tag
  listing mechanism, not venture seed rounds — a pure name collision), and Solana only if
  the project is a top ecosystem project

## COIN TICKER rules (for `coins`) — feeds an exact market-cap lookup, so precision matters
- Only tickers of assets that ACTUALLY EXIST and are central to the event. Max 6.
  A ranking / comparison / roundup piece IS about the assets it ranks — list them.
- Never invent a ticker, never abbreviate a project name into a ticker you are unsure of,
  never emit a ticker for a product/index/pair that has no token. If unsure, omit it.
- Use the CURRENT ticker after any token migration: Polygon → POL (not MATIC).
- Wrapped/staked derivatives keep their own ticker (WBTC, WETH, stETH) — do not fold to BTC/ETH.
- For a tokenized equity (bStocks), emit the tokenized asset's ticker if the item names one,
  otherwise the underlying stock ticker; do not translate a company name into a guessed ticker.
- Do NOT output market-cap, price or valuation numbers here — those are looked up from
  market data downstream, never from your memory.

## CONTENT TAGS
- entities: up to 6 named entities that matter to the event, canonical English names.
  type ∈ person / organization / project / chain / region / product.
  Include only entities that ACT or are ACTED UPON in the event. NEVER include the outlet
  named in the `Source:` line of the input — that is the reporter, not a participant.
  Skip entities that only appear as background comparison.
  Canonicalize: "美国证券交易委员会" → "SEC", "币安" → "Binance", "以太坊基金会" → "Ethereum Foundation".
- sentiment / sentiment_score: the DIRECTIONAL EFFECT ON THE RELEVANT MARKET (crypto assets/
  sectors for market_scope=crypto items; the equity index/market itself for us_stock/hk_stock/
  jp_stock/kr_stock/macro_policy items) — NOT the article's tone, and NOT whether the story is
  pleasant. bullish (score +0.1..+1.0) / bearish (-1.0..-0.1) / neutral (-0.1..+0.1).
  |score| encodes strength: 0.8+ regime-changing (e.g. a market-wide crash, a surprise
  emergency rate cut), 0.4-0.8 clearly directional (a >2% index move, a hawkish surprise),
  0.1-0.4 mild tilt. A hack is bearish for the victim's assets even if funds were recovered.
  Routine data reports, neutral explainers and balanced coverage → neutral, score ~0.
  Sign MUST agree with the label. This field feeds a market-mood aggregate across the whole
  feed (crypto + macro combined) — be honest about magnitude, do not compress everything
  toward neutral just because the story is "just data".
- impact_horizon: when the market effect mainly plays out —
  immediate (<24h, price reacts now), short_term (1-7d), medium_term (1-4w),
  long_term (>1 month, e.g. legislation taking effect next year).

## Scoring
- score_market_impact: within tier bounds above
- score_authority: official announcement=0.9+, top media (crypto: CoinDesk/TheBlock/吴说/BlockBeats; mainstream markets: Reuters/Bloomberg/CNBC/WSJ/FT/Nikkei Asia/MarketWatch)=0.75-0.89, mid media (SCMP/Korea Herald/Cointelegraph-tier)=0.50-0.74, aggregator/search=0.30-0.49, anonymous≤0.30; rumors ×0.7
- score_quality: 1.0 minus deductions (clickbait -0.2~0.5, PR/promotional -0.2~0.4, low info density -0.1~0.4); reward concrete numbers and multi-source facts
- credibility_score: 0=unverifiable, 1=officially confirmed
- is_rumor: true if unverifiable/speculative/"rumored/allegedly/据传/据悉/消息人士"
- rumor_reason: explain why, or empty string

Chinese newsflash items (快讯) are often the FIRST report of hot events — treat them as timely primary signals, not low-quality content."""


# prompt 版本指纹 —— enrich bridge（本地 Claude 预处理）用它保证口径一致：
# Mac worker 领任务时带走这个 hash，回传结果也带着它；pipeline 只认 hash 相同
# 的缓存。SYSTEM_PROMPT 或 NEWS_SCHEMA 任何一个字符变动，旧缓存自动全部失效，
# 不需要人肉记得"改了 prompt 要清缓存"。
import hashlib as _hashlib
PROMPT_VERSION_HASH = _hashlib.sha256(
    (SYSTEM_PROMPT + json.dumps(NEWS_SCHEMA, sort_keys=True)).encode()
).hexdigest()[:16]

# 缓存结果的合法性底线：schema 的 required 字段必须全在。worker 上传前已经
# 校验过一次，这里是第二道闸——不合格的缓存条目按未命中处理，落回 OpenAI。
_REQUIRED_ENRICH_KEYS = frozenset(NEWS_SCHEMA["json_schema"]["schema"]["required"])


def _valid_cached_enrichment(entry) -> bool:
    return isinstance(entry, dict) and _REQUIRED_ENRICH_KEYS.issubset(entry.keys())


# ── LLM 输出后处理（标签口径收口）─────────────────────────────────────
#
# 对外发布阈值 0.55，和 docs/sector-news-mock-evaluation.md 里下游板块推荐 skill
# 的 Rel 硬门保持一致——两边用同一把尺子，分数才可比。
# 低于阈值的标签仍**完整保留**在 sector_relevance 列里（LLM 已经算了，扔掉可惜），
# 只是不进前端可见的 sectors。两级设计的目的是让阈值改代码就能调，不必重跑 LLM。
SECTOR_PUBLISH_THRESHOLD = 0.55
MAX_PUBLISHED_SECTORS = 3


def filter_sector_tags(sector_tags: list) -> tuple[list[str], list[dict]]:
    """sector_tags → (对外 sectors 数组, 完整 sector_relevance 明细)。

    「真相关才打」的最后一道闸：除了分数门槛，还要求 anchor 非空 —— prompt 里
    锚点是强制项，交不出锚点的标签按定义就是拍脑袋打的。
    """
    detail, published = [], []
    for tag in sector_tags or []:
        if not isinstance(tag, dict):
            continue
        sector = (tag.get("sector") or "").strip()
        if not sector:
            continue
        try:
            relevance = round(float(tag.get("relevance", 0.0)), 3)
        except (TypeError, ValueError):
            relevance = 0.0
        anchor = (tag.get("anchor") or "").strip()
        detail.append({"sector": sector, "relevance": relevance, "anchor": anchor})
        if relevance >= SECTOR_PUBLISH_THRESHOLD and anchor:
            published.append((relevance, sector))

    detail.sort(key=lambda d: -d["relevance"])
    published.sort(key=lambda p: -p[0])
    seen, sectors = set(), []
    for _, sector in published[:MAX_PUBLISHED_SECTORS]:
        if sector not in seen:
            seen.add(sector)
            sectors.append(sector)
    return sectors, detail


def normalize_tags(enriched: dict, source: str = "") -> None:
    """就地把 LLM 原始输出规整成下游要的形状。

    下游（storage.write_events / api）读的仍是 `sectors` 字符串数组，形状不变；
    新增的明细放在 sector_relevance / entities / sentiment 等新字段里。

    `source` 是这条新闻的信源名，用来把"发这条稿的媒体自己"从 entities 里剔掉
    —— prompt 已经写了不要带，但 Source: 就摆在输入里，实测 20 条样本中有 7 条
    仍把 CoinDesk / Blockworks / Yahoo Finance 这类出口当成事件实体输出。
    信源信息在 sources 列里已经完整存着，实体列表里再来一份既冗余又会污染
    "同一主体历史新闻"的召回。
    """
    sectors, detail = filter_sector_tags(enriched.pop("sector_tags", []))
    enriched["sectors"] = sectors
    enriched["sector_relevance"] = detail

    # 情绪分与标签互相校正：schema 管不住"标 bullish 却给负分"这类不一致，
    # 以数值为准重算标签（数值参与排序，标签只是展示）。
    try:
        score = max(-1.0, min(1.0, float(enriched.get("sentiment_score", 0.0))))
    except (TypeError, ValueError):
        score = 0.0
    enriched["sentiment_score"] = round(score, 3)
    if score >= 0.1:
        enriched["sentiment"] = "bullish"
    elif score <= -0.1:
        enriched["sentiment"] = "bearish"
    else:
        enriched["sentiment"] = "neutral"

    outlet = _outlet_key(source)
    entities = []
    for entity in enriched.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        name = (entity.get("name") or "").strip()
        if not name or (outlet and _outlet_key(name) == outlet):
            continue
        entities.append({"name": name[:128],
                         "type": entity.get("type", "organization")})
    enriched["entities"] = entities[:6]


def _outlet_key(name: str) -> str:
    """媒体名归一化，用于把信源自身从实体里剔除。

    去掉 X/ 前缀、空格、大小写差异，让 "X/TheBlock__" / "TheBlock" /
    "The Block" 归一到同一个 key。
    """
    key = (name or "").strip().lower()
    if key.startswith("x/"):
        key = key[2:]
    return "".join(ch for ch in key if ch.isalnum())


def build_enrich_input(item: dict) -> str:
    """构造送给 LLM 的用户输入。独立成函数是给 enrich bridge 复用的——
    本地 Claude worker 必须和 OpenAI 路径用**字节级相同**的输入格式，
    否则同一条新闻两条路径可能产出不同的事件三元组，破坏跨轮归并。"""
    return (
        f"Source: {item.get('source', '')}\n"
        f"Title: {item.get('title', '')}\n"
        f"Summary: {item.get('summary', '')[:600]}\n"
        f"URL: {item.get('url', '')}\n"
        f"Published: {item.get('published_at', '')}"
    )


def enrich_one(item: dict, tracker=None, cached: dict | None = None) -> dict | None:
    """单条 LLM 结构化。429 指数退避重试，402 立即放弃。

    `tracker`（crawler.usage_tracker.UsageTracker）记录本次调用的 token 用量，
    供成本监控使用；不传则跳过记录，不影响结构化本身。

    `cached`：enrich bridge 预处理结果（本地 Claude 按同一 prompt 算好的原始
    结构化输出）。合法则直接采用——**跳过的只有那一次 API 调用**，后面的
    normalize_tags / 元数据合并与 OpenAI 路径走完全相同的代码，保证两条路径
    产出的事件形状一致。不合法（缺字段/类型不对）→ 当作未命中，照常走 OpenAI。
    """
    if cached is not None and _valid_cached_enrichment(cached):
        enriched = dict(cached)  # 不改缓存原件
        normalize_tags(enriched, source=item.get("source", ""))
        enriched.update({
            "source":       item.get("source"),
            "url":          item.get("url"),
            "published_at": item.get("published_at"),
            "lang":         item.get("lang", "en"),
            "authority":    item.get("authority", 3),
            "type":         item.get("type", "rss"),
            "tweet_id":     item.get("tweet_id"),
            "_enriched_by": "claude-local",   # 观测用；write_events 按列写库，多余键自然忽略
        })
        return enriched

    user_content = build_enrich_input(item)

    model = LLM_MODEL_LITE if item.get("type") in LLM_LITE_TYPES else LLM_MODEL

    last_error = None
    for attempt in range(LLM_MAX_RETRIES):
        try:
            resp = get_openai_client().chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format=NEWS_SCHEMA,
            )
            if tracker is not None:
                tracker.record_chat(getattr(resp, "usage", None), model=model)
            enriched = json.loads(resp.choices[0].message.content)
            # 暂存 normalize 之前的原始输出，run_pipeline 会批量回写进
            # llm_enrich_cache——同一条 URL 下一轮直接命中缓存，不再付费。
            # 主要受益者是 X 条目（不走 staging，低频 KOL 的同几条推文此前
            # 最长连付 7 天结构化费用）；顺带 pending 端点会跳过已缓存条目，
            # Mac worker 也不会重复算 OpenAI 已经算过的。
            raw_llm_output = dict(enriched)
            # sector_tags → sectors + sector_relevance，并剔除信源自身实体
            normalize_tags(enriched, source=item.get("source", ""))
            # 保留原始抓取元数据，后续聚合/打分要用
            enriched.update({
                "source":       item.get("source"),
                "url":          item.get("url"),
                "published_at": item.get("published_at"),
                "lang":         item.get("lang", "en"),
                "authority":    item.get("authority", 3),
                "type":         item.get("type", "rss"),
                "tweet_id":     item.get("tweet_id"),
                "_cache_writeback": raw_llm_output,
                "_cache_model":     model,
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


def enrich_batch(items: list[dict], max_workers: int = LLM_WORKERS, tracker=None,
                 cache_map: dict | None = None) -> list[dict]:
    """批量结构化。`cache_map` 是 {url_hash: 预处理结果}，命中的条目免 API 调用。"""
    from .staging import url_hash as _uh
    cache_map = cache_map or {}
    with cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(
            lambda item: enrich_one(item, tracker,
                                    cached=cache_map.get(_uh(item.get("url", "")))),
            items))
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


# ── 内容理解标签落库 ─────────────────────────────────────────────────
#
# 单独走 UPDATE 而不是改 storage._INSERT_EVENT_SQL：storage.py 是多方共用的热点
# 文件，新增字段各自用 UPDATE 收口，互不打架（verification.persist_verification
# 与 market_cap.persist_coin_metrics 是同一个路子）。
# `sectors` 列不在这里写 —— 它由 storage.write_events 正常写入，形状没变。

_CONTENT_TAG_SQL = """
UPDATE news_events
   SET entities         = %s,
       sentiment        = %s,
       sentiment_score  = %s,
       sector_relevance = %s,
       impact_horizon   = %s
 WHERE id = %s
"""


def persist_content_tags(events: list[dict], conn) -> int:
    """把实体/情绪/板块相关度写回 news_events。必须在 write_events 之后调用。"""
    if not events:
        return 0
    cursor = conn.cursor()
    written = 0
    for event in events:
        if "sector_relevance" not in event and "entities" not in event:
            continue
        try:
            cursor.execute(_CONTENT_TAG_SQL, (
                json.dumps(event.get("entities") or [], ensure_ascii=False),
                event.get("sentiment") or None,
                event.get("sentiment_score"),
                json.dumps(event.get("sector_relevance") or [], ensure_ascii=False),
                event.get("impact_horizon") or None,
                event["id"],
            ))
            written += cursor.rowcount
        except Exception as e:
            logger.warning(f"content tags write failed [{event.get('id')}]: {e}")
    conn.commit()
    cursor.close()
    logger.info(f"MySQL: content tags written for {written}/{len(events)} events")
    return written


# ── Pipeline 编排 ────────────────────────────────────────────────────

def run_pipeline() -> dict:
    """跑完整一轮，返回各阶段水位统计。

    2026-07-26 起 Step 1 改为「消费存档 + 实时抓 X」，不再每轮重新抓一遍免费源。
    背景：免费源（RSS/HTML/搜索引擎/行情信号）现在由独立的高频 cron
    （`scripts/stage_fetch.py`，建议每 1-2 小时）抓取后先存进 `raw_items_staging`
    表，本函数只负责取出上一轮以来新存的、还没处理过的条目——这样抓取节奏和
    LLM 处理节奏解耦，高频源不再受本 pipeline 12 小时一次的周期限制而滚屏丢失
    （详见 crawler/staging.py 顶部说明）。X 是唯一例外：按用户要求维持原节奏，
    不接入高频存档路径，仍在本函数里实时抓取。

    如果存档表是空的（比如高频 cron 还没跑过，或数据库刚初始化），自动回退到
    `run_rss_and_scraper_crawler()` 做一次性全量抓取，保证 pipeline 任何时候都
    能独立跑通，不依赖另一个 cron 的状态。
    """
    from . import staging
    from .main import fetch_x_sources, run_rss_and_scraper_crawler

    start = time.time()
    conn = storage.get_mysql_conn()
    stats = {"raw": 0, "deduped": 0, "enriched": 0, "events": 0,
             "rumors": 0, "merged": 0}
    tracker = UsageTracker()  # 本轮 OpenAI 用量，见 usage_tracker.py

    # 分阶段计时。2026-07-26 加的——此前想知道"pipeline 为什么这么久"只能翻
    # 日志按时间戳手动倒推。每个阶段跑完记一次 lap()，最后连同 duration 一起
    # 存进 pipeline_runs.stage_timings（JSON），下次直接查库就有分解。
    _lap_start = [start]

    def lap(stage: str) -> None:
        now = time.time()
        stats.setdefault("stage_timings", {})[stage] = round(now - _lap_start[0], 2)
        _lap_start[0] = now

    try:
        # 1. 抓取：消费存档的免费源 + 实时抓 X
        staged_items = staging.fetch_staged_items(conn)
        x_items, x_raw_posts = fetch_x_sources()

        if staged_items:
            raw_items = staged_items + x_items
            logger.info(f"Step 1: {len(staged_items)} staged + {len(x_items)} X (live)")
        else:
            # 存档表为空（高频 cron 尚未运行过等）—— 回退到一次性全量抓取，
            # 保证 pipeline 任何时候都能独立跑通，不依赖另一个 cron 的状态。
            # 此时 fetch_x_sources 已经抓过一次 X，这里再用
            # run_rss_and_scraper_crawler 会重复抓 X，可接受
            # （回退路径本就是异常情况，不追求最优，追求能跑通）。
            logger.warning("Step 1: staging table empty, falling back to full live fetch")
            raw_items, fallback_x_posts = run_rss_and_scraper_crawler()
            x_raw_posts = x_raw_posts or fallback_x_posts

        stats["raw"] = len(raw_items)
        logger.info(f"Step 1 crawl: {stats['raw']} raw items")
        lap("fetch")

        # 2. X 推文落表（必须早于事件写库，H 因子要读回互动量）
        storage.write_x_posts(x_raw_posts, conn)

        # 3. 粗去重（省 LLM 成本）：字面 TF-IDF → 语义 embedding 两道。
        #    第二道是 2026-07-28 加的，抓的是第一道天然抓不住的跨语言/改写重复，
        #    成本近似为零（见 semantic_prefilter 的说明）。
        deduped = prefilter_duplicates(raw_items)
        deduped = semantic_prefilter(deduped, get_openai_client(), tracker=tracker)
        stats["deduped"] = len(deduped)
        lap("prefilter")

        # 4. LLM 结构化 —— 实测这是整条 pipeline 的绝对大头（曾占单轮总耗时
        #    96%+），批量大时单轮可以跑到 40 分钟量级，不是卡住，是 gpt-5.4
        #    在真的处理这么多条。想加速只能加 LLM_WORKERS 并发数（注意会提高
        #    瞬时速率，需要留意 TPM 限额），成本本身不受并发数影响。
        #
        #    2026-07-26 起接入 enrich bridge：先查本地 Claude 预处理缓存
        #    （Lawrence 的 Mac 闲时用 Claude Max 额度算好的），命中的条目
        #    零 OpenAI 成本；未命中/缓存不可用 → 与从前完全一样走 OpenAI。
        #    Mac 关机几天也只是缓存全 miss，pipeline 行为不变。
        from .staging import url_hash as _url_hash_fn
        cache_map = storage.load_enrich_cache(
            conn, [_url_hash_fn(i.get("url", "")) for i in deduped],
            PROMPT_VERSION_HASH)
        enriched = enrich_batch(deduped, tracker=tracker, cache_map=cache_map)
        stats["enriched"] = len(enriched)
        if deduped and not enriched:
            # 全军覆没 = LLM 侧系统性故障（key 失效/欠费/全面限流），不是数据问题。
            # 必须炸出来：staging 条目未标记消费，下一轮会原样重取，零丢失；
            # 若这里静默续跑，本轮会以 status=success、0 事件收场，批次无声蒸发
            # （2026-07-26 review 确认过这条静默路径真实存在）。
            raise RuntimeError(
                f"LLM enrichment returned 0/{len(deduped)} — aborting run; "
                f"staged items remain unconsumed for retry next round")
        used_hashes = [_url_hash_fn(e.get("url", "")) for e in enriched
                       if e.get("_enriched_by") == "claude-local"]
        stats["llm_cache_hits"] = len(used_hashes)
        if used_hashes:
            logger.info(f"Step 4 bridge: {len(used_hashes)}/{len(deduped)} items "
                        f"pre-enriched by local Claude (zero OpenAI cost)")
            storage.mark_enrich_cache_consumed(conn, used_hashes)

        # 4.5 OpenAI 结果回写缓存（2026-07-26，Lawrence 拍板"现在就做"）：
        #     同 URL 下一轮零成本，主要止住 X 条目跨轮重复付费的血。
        #     纯优化路径，失败只打日志，绝不影响主流程。
        writeback = []
        for e in enriched:
            raw = e.pop("_cache_writeback", None)
            model_used = e.pop("_cache_model", None)
            if raw is not None:
                writeback.append((_url_hash_fn(e.get("url", "")), raw,
                                  f"openai/{model_used or LLM_MODEL}"))
        if writeback:
            try:
                storage.save_enrich_cache(conn, writeback, PROMPT_VERSION_HASH)
                logger.info(f"Step 4.5 cache writeback: {len(writeback)} OpenAI "
                            f"results cached for future rounds")
            except Exception as e:
                logger.warning(f"cache writeback skipped (harmless): {e}")
        stats["rumors"] = sum(1 for e in enriched if e.get("is_rumor"))
        logger.info(f"Step 4 LLM: {stats['enriched']} enriched, "
                    f"{stats['rumors']} flagged as rumor (kept, down-weighted)")
        lap("llm_enrich")

        # 5. 事件指纹 + 语义聚合（DC-1 ~ DC-3）
        attach_fingerprints(enriched)
        events = aggregate_events(enriched, get_openai_client(), tracker=tracker)
        stats["events"] = len(events)
        lap("dedup_aggregate")

        # 6. 跨轮归并（DC-4）。命中既有行的事件会复用其 id，写库时走 UPDATE 分支
        recent = storage.load_recent_events(conn)
        events, stats["merged"] = storage.merge_with_existing(events, recent)
        stats["events"] = len(events)

        # 7. 社交互动信号（喂给 H 因子）。必须放在归并之后：归并会合并 sources，
        #    在合并后的完整推文集合上统计，互动量才不会漏算
        storage.attach_social_metrics(events, conn)
        lap("cross_run_merge")

        # 7.5 真实性校验（DC 之外的另一道闸）。全部基于客观信号——按机构去重后的
        #     独立佐证数、信源可信度分层、时间一致性、矛盾检测——零 LLM 调用。
        #     必须在打分之前：compute_authority 会用到校验结论做降权。
        verification_stats = verify_events(events, conn=conn)
        stats["unverified"] = (verification_stats.get("UNVERIFIED", 0)
                               + verification_stats.get("DISPUTED", 0))
        logger.info(f"Step 7.5 verification: {verification_stats}")
        lap("verification")

        # 7.6 币种市值标签。纯查表（CoinGecko 快照 + 币安现货交叉校验），
        #     0 次 LLM 调用，行情快照 6 小时缓存，多数轮次 0 次 HTTP 请求。
        try:
            annotate_market_cap(events)
        except Exception as e:
            # 行情源挂掉不该拖垮整条 pipeline：少几个标签，事件照常入库
            logger.warning(f"Step 7.6 market cap tagging skipped: {e}")
        lap("market_cap")

        # 8. 打分 + 入库
        score_events(events)
        storage.write_events(events, conn)

        # 9. 校验结论 + 新增标签落库。必须在 write_events 之后——都是 UPDATE，行得先存在
        persist_verification(events, conn)
        persist_content_tags(events, conn)
        storage.persist_x_post_links(events, conn)
        try:
            persist_coin_metrics(events, conn)
        except Exception as e:
            logger.warning(f"coin metrics persist skipped: {e}")
        # 存档标记放在写库全部成功之后（见 staging.fetch_staged_items 的说明）
        staging.mark_staged_consumed(conn, staged_items)
        lap("score_and_write")

        duration = round(time.time() - start, 2)
        tracker.log_summary()
        logger.info(f"Stage timings (s): {stats['stage_timings']}")
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
