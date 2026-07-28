"""
Sector Insight —— 板块相关性推荐（查询时排序，不是写入时打标签）。

依据：docs/skill-sector-news-recommendation-v5.md（下称"skill 文档"）。

## 和已有 sector_tags / sectors 的关系（不要混淆）

`pipeline.py` 的 `sector_tags` 是内容理解 agent 在**写入时**做的"这条新闻属于哪些
板块"的宽泛标签（阈值 0.55，最多 3 个，存进 `news_events.sectors` /
`sector_relevance` 列）。它服务的场景是"列出这条新闻挂哪些板块"。

本模块服务的是完全不同的场景："给定板块 X，从候选池里挑 Top3 最相关内容"——
查询时（query-time）排序，不写库（除非调用方自己要缓存）。同一条内容在这两个
场景下的相关性数字可以不同：写入时的 sector_tags 判断相对宽松（毕竟只是"贴不贴
标签"，宁可少贴不可乱贴，但门槛仍是 0.55 一刀切），而这里要处理 skill 文档列出
的全部 bad case（顺带提及、同名误绑、跨板块、视角改写、ROUNDUP、传导链外推、
机制型叙事泛化），门槛与判定逻辑都更严格、更贵（每次查询都跑一遍 LLM 精判）。

## 两层管线

    Stage 1  非 LLM 预筛（成本控制核心）
             语义 embedding cosine（复用 dedup.py 已存的 256 维向量，只需为
             板块锚点新算 1 次 embedding）+ 成分币/关键词命中，两者加权合成
             prefilter_score；< PREFILTER_THRESHOLD 的直接判 Rel=0，不进 LLM。

    Stage 2  LLM 精判（gpt-5.4，只对通过预筛的候选调用，批量调用摊薄成本）
             实现 skill 文档公式：Rel = clip(0.5*EntityMatch + 0.3*Semantic
             + 0.2*Focus_bonus, 0, 1)，LLM 只负责给出子信号（entity_match /
             semantic_sim / focus_ratio / title_hit / content_genre /
             transmission_hops / is_constituent_anchor / matched_tickers），
             最终 Rel 由 Python 按 skill 文档规则确定性合成 —— 这是刻意的：
             和 crawler/scoring.py 的 compute_impact()（用 event_tier 区间
             夹紧 LLM 打分）、compute_authority()（用 verification_status 降权）
             同一个哲学：LLM 的原始数字不直接使用，用代码规则做"自洽性约束"，
             防止 LLM 偶尔被戏剧性词汇 / 名称撞车诱导给出越界分数。

之后硬门 + 打分（T/H/A/M 直接复用 crawler/scoring.py，不重新实现）、
Sector Insight 专属去重（cosine>=0.75，注意与 Macro Insight 已标定的 0.82
不同，见 DEDUP_COSINE_THRESHOLD 注释）、宁缺毋滥选 Top N。
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import numpy as np
from openai import OpenAI

from .dedup import _UnionFind, blob_to_embedding, cosine, embed_texts
from .scoring import (
    compute_authority, compute_hotness, compute_impact, compute_timeliness,
    social_baseline,
)
from .sources import SECTOR_LABELS
from .timeutil import now_local

logger = logging.getLogger(__name__)

LLM_MODEL = "gpt-5.4"        # 网关切换尝试见 crawler/pipeline.py 同名常量的注释（已回退，未生效）
LLM_BATCH_SIZE = 12          # 每次结构化调用打包的候选条数，控制单次响应体量
LLM_MAX_RETRIES = 4

_openai_client = None


def get_openai_client() -> OpenAI:
    """独立于 crawler.pipeline 的 client，避免跨模块状态耦合（同样读环境变量）。"""
    global _openai_client
    if _openai_client is None:
        kwargs = {}
        if api_key := os.environ.get("OPENAI_API_KEY"):
            kwargs["api_key"] = api_key
        if base_url := (os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL")):
            kwargs["base_url"] = base_url
        _openai_client = OpenAI(**kwargs)
    return _openai_client


# ══════════════════════════════════════════════════════════════════════
# 板块类型 + 语义锚点 + 成分币/关键词表（v1 人工整理，覆盖 sources.SECTOR_LABELS
# 全部 20 个板块；数字资产板块的成分会随时间变化，本表按 2026-07 时点整理，
# 需要像 sources.py 里的信源表一样定期维护——这是已知的持续性工作，不是一次性的）
# ══════════════════════════════════════════════════════════════════════
#
# type 对应 skill 文档补充定义 B 的三分类，决定 LLM 判定"主角"的锚点和
# transmission_hops 封顶规则：
#   track      赛道型：成分币或赛道主题本身是事件主体
#   chain      公链生态型：链本身，或链上"原生"头部生态项目
#   mechanism  平台机制型：机制本身，或机制的成分项目/标的自身重大事件
SECTOR_TYPE_TRACK = "track"
SECTOR_TYPE_CHAIN = "chain"
SECTOR_TYPE_MECHANISM = "mechanism"

SECTOR_ANCHORS: dict[str, dict] = {
    "MEME": {
        "type": SECTOR_TYPE_TRACK,
        "anchor_text": (
            "Meme coin sector: community-driven and celebrity/political meme "
            "tokens, viral dog/frog/politician themed coins, meme launchpads, "
            "pump-and-dump trading, meme coin scams and rug pulls. "
            "Examples: DOGE, SHIB, PEPE, TRUMP, WLFI, BONK, WIF, FLOKI, "
            "four.meme, pump.fun, Binance Square meme trend."
        ),
        "tickers": {"DOGE", "SHIB", "PEPE", "TRUMP", "WLFI", "BONK", "WIF",
                     "FLOKI", "MAGA", "DOGS", "BOME", "MOG", "PNUT", "POPCAT",
                     "NEIRO", "TURBO", "BRETT", "MELANIA"},
        "keywords": ["meme coin", "memecoin", "meme token", "four.meme",
                     "pump.fun", "dogecoin", "shiba inu", "vladhood",
                     "political meme", "celebrity token", "meme community"],
    },
    "DeFi": {
        "type": SECTOR_TYPE_TRACK,
        "anchor_text": (
            "DeFi decentralized finance sector: lending protocols, DEX, "
            "liquidity pools, yield farming, stablecoin/collateral mechanics, "
            "liquid staking, restaking, perp DEXs. Examples: Aave, Uniswap, "
            "Compound, MakerDAO, Lido, Curve, Morpho, Maple, Aerodrome, Euler, "
            "Frax, EigenLayer, Hyperliquid, Odos, TVL reports."
        ),
        # 2026-07-26 用真实数据标定 Stage 1 预筛时发现的缺口：EUL/HYPE/EIGEN/
        # FRAX/FRXETH/ODOS/INJ/SUN 这几个真实 DeFi 协议在 804 条真实候选里都
        # 出现过、且写入时已被打上 DeFi 标签，但初版清单没收录，导致预筛召回率
        # 只有 32.2%（59 条写入时打标的 DeFi 内容只有 19 条通过预筛）——这不是
        # 0.6 阈值本身的问题（阈值卡的是"综合分"，不是这张清单的锅），是清单
        # 覆盖不够。补全后未重新跑批量校准（见交付报告），后续应持续按这个
        # 方法（对比写入时 sectors 标签 vs 预筛通过率）找漏项，和 sources.py
        # 的信源表一样是需要长期维护的清单，不是一次性写死。
        "tickers": {"AAVE", "UNI", "MKR", "COMP", "CRV", "LDO", "STETH",
                     "MORPHO", "SYRUP", "AERO", "SUSHI", "SNX", "DAI",
                     "GMX", "PENDLE", "RAY", "JUP", "EUL", "HYPE", "EIGEN",
                     "FRAX", "FRXETH", "ODOS", "INJ", "SUN", "SPK"},
        "keywords": ["defi", "decentralized finance", "lending protocol",
                     "liquidity pool", "yield farming", "dex volume",
                     "tvl", "liquid staking", "stablecoin yield",
                     "collateral", "aave", "uniswap", "morpho", "lido"],
    },
    "Gaming": {
        "type": SECTOR_TYPE_TRACK,
        "anchor_text": (
            "Web3 gaming sector: blockchain games, GameFi tokens, play-to-earn, "
            "in-game NFT assets, gaming guilds. Examples: Pixels, Axie "
            "Infinity, Gala, ImmutableX, Ronin, gaming token rallies."
        ),
        "tickers": {"PIXEL", "AXS", "GALA", "IMX", "RON", "SAND", "MANA",
                     "ILV", "BEAM", "MAGIC", "YGG"},
        "keywords": ["gamefi", "blockchain game", "play-to-earn", "web3 game",
                     "gaming token", "in-game nft", "gaming guild"],
    },
    "AI": {
        "type": SECTOR_TYPE_TRACK,
        "anchor_text": (
            "Crypto AI sector: AI-agent tokens, decentralized compute/AI "
            "infrastructure tokens, AI-crypto integration projects. Examples: "
            "Worldcoin (WLD), Fetch.ai (FET), Bittensor (TAO), Render (RNDR), "
            "Akash, AI agent frameworks. Generic Web2 AI company news "
            "(OpenAI, big-tech AI labs) is NOT this sector unless a crypto "
            "AI token is the actual subject."
        ),
        "tickers": {"WLD", "FET", "TAO", "RNDR", "AKT", "AGIX", "OCEAN",
                     "ARKM", "VIRTUAL", "AI16Z", "GRT"},
        "keywords": ["ai agent token", "crypto ai", "decentralized ai",
                     "worldcoin", "bittensor", "ai16z", "onchain ai compute"],
    },
    "NFT": {
        "type": SECTOR_TYPE_TRACK,
        "anchor_text": (
            "NFT sector: non-fungible token collections, NFT marketplaces, "
            "digital collectibles, NFT trading volume. Examples: OpenSea, "
            "Blur, Bored Ape Yacht Club, CryptoPunks, NFT floor price moves."
        ),
        "tickers": {"BLUR", "APE", "LOOKS", "RARE"},
        "keywords": ["nft collection", "nft marketplace", "floor price",
                     "digital collectible", "opensea", "blur", "bayc",
                     "cryptopunks"],
    },
    "RWA": {
        "type": SECTOR_TYPE_TRACK,
        "anchor_text": (
            "RWA real-world-asset tokenization sector: tokenized treasuries, "
            "tokenized bonds, tokenized private credit, on-chain real estate. "
            "Examples: Ondo Finance, Centrifuge, Maple, tokenized bank "
            "deposits, tokenized money-market funds."
        ),
        "tickers": {"ONDO", "CFG", "MPL", "POLYX", "TRU", "GFI"},
        "keywords": ["real-world asset", "tokenized treasury", "tokenized "
                     "bond", "tokenized deposit", "tokenized fund",
                     "onchain private credit", "ondo finance"],
    },
    "Payments": {
        "type": SECTOR_TYPE_TRACK,
        "anchor_text": (
            "Crypto payments sector: stablecoin payment rails, cross-border "
            "settlement, merchant crypto payment adoption. Examples: XRP, "
            "Stellar (XLM), USDC/USDT payment rails, PayPal PYUSD, Ripple "
            "payment network."
        ),
        "tickers": {"XRP", "XLM", "PYUSD", "USDP", "ALGO"},
        "keywords": ["payment rail", "cross-border settlement", "stablecoin "
                     "payment", "merchant adoption", "remittance", "ripple "
                     "payments"],
    },
    "Infrastructure": {
        "type": SECTOR_TYPE_TRACK,
        "anchor_text": (
            "Blockchain infrastructure sector: L1 base-layer tech, oracles, "
            "cross-chain messaging, node/data infrastructure. Examples: "
            "Chainlink, LayerZero, The Graph, Filecoin, Celestia. NOT an "
            "exchange outage, a wallet feature, or an app-layer protocol hack "
            "— those are not base-layer infrastructure."
        ),
        "tickers": {"LINK", "ZRO", "GRT", "FIL", "TIA", "ATOM", "DOT",
                     "AR", "RENDER"},
        "keywords": ["oracle network", "cross-chain messaging", "layerzero",
                     "chainlink", "node infrastructure", "data availability",
                     "base layer"],
    },
    "tCommodities": {
        "type": SECTOR_TYPE_MECHANISM,
        "anchor_text": (
            "Tokenized commodities mechanism: tokenized gold/silver and other "
            "physical commodities on-chain. Examples: PAXG, XAUT (tokenized "
            "gold), tokenized silver. Sector subject = the tokenization "
            "mechanism or the underlying commodity's own major event (price "
            "move driven by physical commodity markets, new tokenized "
            "commodity listing) — not general macro commodity commentary."
        ),
        "tickers": {"PAXG", "XAUT", "XAGT", "KAU", "KAG"},
        "keywords": ["tokenized gold", "tokenized commodity", "tokenized "
                     "silver", "paxg", "xaut"],
    },
    "Fan Token": {
        "type": SECTOR_TYPE_TRACK,
        "anchor_text": (
            "Fan token sector: sports/entertainment fan engagement tokens "
            "issued via platforms like Chiliz/Socios. Examples: PSG fan "
            "token, Barcelona fan token, CHZ."
        ),
        "tickers": {"CHZ", "PSG", "BAR", "JUV", "CITY", "ATM"},
        "keywords": ["fan token", "chiliz", "socios", "sports fan "
                     "engagement token"],
    },
    "Solana": {
        "type": SECTOR_TYPE_CHAIN,
        "anchor_text": (
            "Solana blockchain ecosystem: Solana network upgrades/outages, "
            "Solana-native top ecosystem projects. Examples: Jupiter (JUP), "
            "Drift Protocol, Pyth Network, Jito, Raydium, Orca, Marinade — "
            "projects that are natively identified with and built primarily "
            "for Solana. A project merely bridging to or also deployed on "
            "Solana, while its own story is unrelated to Solana, is NOT this "
            "sector's subject."
        ),
        "tickers": {"SOL", "JUP", "DRIFT", "PYTH", "JTO", "RAY", "ORCA",
                     "MNGO", "TNSR", "BONK", "WIF"},
        "keywords": ["solana network", "solana ecosystem", "solana-native",
                     "jupiter exchange", "drift protocol", "pyth network",
                     "solana outage", "solana upgrade"],
    },
    "BSC": {
        "type": SECTOR_TYPE_CHAIN,
        "anchor_text": (
            "BNB Smart Chain (BSC) ecosystem: BSC network upgrades, "
            "BSC-native top ecosystem projects. Examples: PancakeSwap, "
            "Venus Protocol, four.meme (BSC-native meme launchpad), BNB "
            "Chain data/outages. A project merely deployed on BSC while its "
            "own story is unrelated to BSC is NOT this sector's subject."
        ),
        "tickers": {"BNB", "CAKE", "XVS", "TWT"},
        "keywords": ["bnb chain", "bnb smart chain", "bsc ecosystem",
                     "pancakeswap", "four.meme", "venus protocol"],
    },
    "Layer1/Layer2": {
        "type": SECTOR_TYPE_CHAIN,
        "anchor_text": (
            "Layer1/Layer2 blockchain ecosystems (excluding Solana/BSC which "
            "have dedicated sectors): Ethereum, Bitcoin, Arbitrum, Optimism, "
            "Base, Polygon, Avalanche, Sui, Aptos, TON network upgrades, "
            "outages, and native ecosystem projects."
        ),
        "tickers": {"ETH", "BTC", "ARB", "OP", "POL", "MATIC", "AVAX",
                     "SUI", "APT", "TON", "STX", "NEAR", "ADA"},
        "keywords": ["layer 1", "layer 2", "mainnet upgrade", "rollup",
                     "ethereum upgrade", "arbitrum", "optimism", "base "
                     "chain", "polygon"],
    },
    "Launchpool": {
        "type": SECTOR_TYPE_MECHANISM,
        "anchor_text": (
            "Binance Launchpool mechanism: new project added to Launchpool, "
            "BNB/FDUSD staking mining periods, farming rewards, APY changes. "
            "Sector subject = the mechanism itself (new period/rules/yield "
            "change) or a Launchpool project's own major event — NOT any "
            "yield-narrative story that merely 'feels similar' in theme."
        ),
        "tickers": set(),   # 机制型：成分币逐期变化，无法固定；靠关键词命中
        "keywords": ["launchpool", "bnb staking", "fdusd farming", "mining "
                     "period", "staking rewards", "new launchpool project"],
    },
    "Launchpad": {
        "type": SECTOR_TYPE_MECHANISM,
        "anchor_text": (
            "Binance Launchpad mechanism: new token sale/IEO launched via "
            "Launchpad. Sector subject = the mechanism itself (new project "
            "sale, allocation rules) or a Launchpad project's own major "
            "event."
        ),
        "tickers": set(),
        "keywords": ["launchpad", "token sale", "ieo", "initial exchange "
                     "offering"],
    },
    "Megadrop": {
        "type": SECTOR_TYPE_MECHANISM,
        "anchor_text": (
            "Binance Megadrop mechanism: new project airdrop via Megadrop, "
            "BNB locking/Web3 quiz tasks for airdrop allocation. Sector "
            "subject = the mechanism itself or a Megadrop project's own "
            "major event."
        ),
        "tickers": set(),
        "keywords": ["megadrop", "airdrop allocation", "bnb locking task"],
    },
    "Seed": {
        "type": SECTOR_TYPE_MECHANISM,
        "anchor_text": (
            "Binance Seed Tag mechanism: early-stage / higher-risk project "
            "listing tag. Sector subject = the Seed Tag mechanism itself or "
            "a Seed-tagged project's own major event. NOT generic venture "
            "'seed funding round' news — that is a pure name collision with "
            "unrelated venture capital seed rounds."
        ),
        "tickers": set(),
        "keywords": ["seed tag", "binance seed"],
    },
    "New Listing": {
        "type": SECTOR_TYPE_MECHANISM,
        "anchor_text": (
            "Binance new spot/futures listing mechanism: a token newly "
            "listed (or delisted) on Binance spot or perpetual markets. "
            "Sector subject = the listing/delisting event itself."
        ),
        "tickers": set(),
        "keywords": ["new listing", "will list", "spot trading opens",
                     "perpetual contract launch", "delisting"],
    },
    "Monitoring": {
        "type": SECTOR_TYPE_MECHANISM,
        "anchor_text": (
            "On-chain monitoring/alerting sector: whale-tracking and "
            "exploit-tracking products and the assets they track as their "
            "own theme (Lookonchain, Whale Alert, PeckShield, SlowMist, "
            "CertiK reports as the actual subject). A security firm merely "
            "being QUOTED inside an unrelated story does NOT make that story "
            "a Monitoring-sector event."
        ),
        "tickers": set(),
        "keywords": ["lookonchain", "whale alert", "peckshield", "slowmist",
                     "certik", "onchain monitoring", "whale tracking",
                     "exploit tracking"],
    },
    "bStocks": {
        "type": SECTOR_TYPE_MECHANISM,
        "anchor_text": (
            "Binance tokenized stocks (bStocks) mechanism: tokenized equity "
            "products on Binance (e.g. tokenized COIN, TSLA, NVDA shares). "
            "Sector subject = the tokenization mechanism itself, or the "
            "SINGLE underlying stock's own major event (earnings, M&A) where "
            "that stock is a bStocks constituent. General equity-market "
            "sentiment (chip-stock selloff, Fed rate moves) reaching bStocks "
            "requires >=2 inference hops and must be capped low."
        ),
        "tickers": {"COIN", "TSLA", "TSLLT", "SKHYB", "CXMT", "NVDA",
                     "HOOD", "MSTR"},
        "keywords": ["tokenized stock", "bstocks", "tokenized equity",
                     "tokenized share"],
    },
}

# 缺省锚点：SECTOR_LABELS 里若有条目未在上表精细维护，退化为"板块名 + 空成分表"，
# 预筛几乎总会判定语义分低（因为锚点文本信息量太少），保证不会因为查表缺失而
# 静默给出虚高分数——宁可这个板块的 Sector Insight 效果差，也不能给错。
for _label in SECTOR_LABELS:
    if _label not in SECTOR_ANCHORS:
        SECTOR_ANCHORS[_label] = {
            "type": SECTOR_TYPE_TRACK,
            "anchor_text": f"Binance sector: {_label}.",
            "tickers": set(),
            "keywords": [],
        }
        logger.warning(f"SECTOR_ANCHORS: '{_label}' 使用缺省锚点（未精细维护），"
                       "预筛/精判效果可能偏弱，需要人工补充 anchor_text/tickers/keywords")


TYPE_LABEL_ZH = {
    SECTOR_TYPE_TRACK: "赛道型",
    SECTOR_TYPE_CHAIN: "公链生态型",
    SECTOR_TYPE_MECHANISM: "平台机制型",
}


# ══════════════════════════════════════════════════════════════════════
# Stage 1：非 LLM 预筛
# ══════════════════════════════════════════════════════════════════════
#
# 阈值标定说明（真实数据验证，2026-07-26，508 条真实事件 / 5 板块）：
#
# 用户原话要求"相关性低于 0.6 统一算成 0"。这个 0.6 是对**综合预筛分**而不是
# 对原始 embedding cosine 的要求——直接拿原始 cosine 卡 0.6 在真实数据上完全
# 不可行：text-embedding-3-small 在 256 维截断下，同板块强相关内容与锚点的
# cosine 普遍只有 0.35~0.55（"DeFi 锚点文本" vs "Aave WETH 激励计划结束"这类
# 强相关标题实测 cosine≈0.42），而明显无关内容（"北约峰会讨论"）也有 0.15~0.25
# 的基线相似度（同为英文财经语料的词汇共现）。若把 0.6 直接套在 cosine 上，
# 会把几乎全部真正相关的内容都误杀在预筛这一层，LLM 精判阶段永远拿不到候选。
#
# 因此设计为：prefilter_score = SEMANTIC_WEIGHT * cosine + ENTITY_WEIGHT *
# entity_hit（entity_hit 是 0/0.5/0.8/1.0 的离散信号，命中已知成分币/关键词），
# 两者加权后的**综合分**再卡 0.6。这样"成分币直接命中"的内容（entity_hit=1.0）
# 只需要 cosine > 0.1 左右就能过预筛（这是对的——GC-1.1 标题即主角这种一望而
# 知的正例，不该被语义分卡掉）；而"没有命中任何已知成分币/关键词，纯靠语义
# 相似"的内容，必须 cosine 达到 (0.6 - 0)/SEMANTIC_WEIGHT ≈ 0.6/0.55 ≈ 1.09，
# 也就是**不可能仅凭语义单独通过预筛**——这是有意的收紧：纯语义信号在 256 维
# 空间里噪音大，容易把"同为加密新闻"当成"同板块"（BC-1.3 的预筛版本），所以
# 预筛阶段要求"要么命中关键词/成分币，要么二者都有中等强度"，不接受"语义分
# 单科满分但零实体命中"这种组合直接放行——这类边界情况让它们经由 entity_hit
# 部分分（关键词在正文里командировка命中给 0.5）补足，而不是纯语义硬撑。
#
# 实测验证（见 scripts/ 或本文件 --calibrate 输出）：对 MEME/DeFi/Solana/
# Launchpool/Gaming 5 个板块、508 条候选跑一遍，写入时已标记该板块的内容
# （sector_relevance/sectors 命中，作为弱 ground truth）里，命中 entity_hit>0
# 的比例约 90%+，说明"是否命中已知成分币/关键词"本身就是主信号，纯语义分只是
# 补充——这与本模块的权重设计（entity 0.5 更重）方向一致。
SEMANTIC_WEIGHT = 0.55
ENTITY_WEIGHT = 0.45
PREFILTER_THRESHOLD = 0.6


def normalize_ticker(raw: str) -> str:
    return (raw or "").strip().upper().lstrip("$")


def _entity_hit_score(coins: list, entities: list, title_en: str, title_zh: str,
                      desc_en: str, desc_zh: str, sector_def: dict) -> tuple[float, list[str]]:
    """成分币/关键词命中打分：1.0（ticker 命中）> 0.8（标题关键词命中）
    > 0.5（正文关键词命中）> 0（无命中）。返回 (分数, 命中的证据列表)。

    ticker 命中优先级最高且不打折——这是结构化数据（内容理解管线已经从正文里
    抽出来的 coins 字段），比标题/正文关键词的字符串匹配更可信。
    """
    tickers = sector_def.get("tickers") or set()
    keywords = sector_def.get("keywords") or []
    evidence = []

    coin_set = {normalize_ticker(c) for c in (coins or []) if c}
    hit_tickers = coin_set & tickers
    if hit_tickers:
        evidence.append(f"coins命中: {sorted(hit_tickers)}")
        return 1.0, evidence

    # entities 字段是内容理解管线抽取的结构化实体（目前覆盖率不高，命中即用）
    entity_names = {(e.get("name") or "").strip().upper()
                    for e in (entities or []) if isinstance(e, dict)}
    if entity_names & tickers:
        evidence.append(f"entities命中: {sorted(entity_names & tickers)}")
        return 1.0, evidence

    title_text = f"{title_en or ''} {title_zh or ''}".lower()
    for kw in keywords:
        if kw.lower() in title_text:
            evidence.append(f"标题关键词命中: {kw}")
            return 0.8, evidence

    desc_text = f"{desc_en or ''} {desc_zh or ''}".lower()
    for kw in keywords:
        if kw.lower() in desc_text:
            evidence.append(f"正文关键词命中: {kw}")
            return 0.5, evidence

    return 0.0, evidence


def prefilter_candidates(candidates: list[dict], sector: str, client,
                         tracker=None) -> tuple[list[dict], list[dict]]:
    """Stage 1：非 LLM 预筛。返回 (通过预筛, 被预筛淘汰)，两者都带 prefilter_* 字段。

    成本：只有 1 次 embedding API 调用（板块锚点文本），候选内容的 embedding
    全部复用 news_events.embedding 里已经存好的向量（写入时 dedup 阶段算过），
    不重新计算——这是预筛"接近零成本"的关键。
    """
    sector_def = SECTOR_ANCHORS[sector]
    anchor_vec = embed_texts([sector_def["anchor_text"]], client, tracker)[0]

    passed, rejected = [], []
    for cand in candidates:
        cand_vec = cand.get("_embedding")
        semantic = cosine(cand_vec, anchor_vec) if cand_vec is not None else 0.0
        entity_score, evidence = _entity_hit_score(
            cand.get("coins"), cand.get("entities"),
            cand.get("title_en"), cand.get("title_zh"),
            cand.get("description_short_en"), cand.get("description_short_zh"),
            sector_def,
        )
        score = SEMANTIC_WEIGHT * max(0.0, semantic) + ENTITY_WEIGHT * entity_score
        cand["prefilter_score"] = round(score, 4)
        cand["prefilter_semantic"] = round(float(semantic), 4)
        cand["prefilter_entity"] = round(entity_score, 4)
        cand["prefilter_evidence"] = evidence

        if score >= PREFILTER_THRESHOLD:
            passed.append(cand)
        else:
            cand["filtered_reason"] = (
                f"预筛淘汰（分数 {score:.3f} < {PREFILTER_THRESHOLD}）：语义相似度 "
                f"{semantic:.3f}，成分币/关键词{'未命中' if not evidence else '弱命中 ' + str(evidence)}"
            )
            rejected.append(cand)

    logger.info(f"Sector Insight [{sector}] prefilter: {len(candidates)} → "
               f"{len(passed)} passed / {len(rejected)} rejected "
               f"(threshold={PREFILTER_THRESHOLD})")
    return passed, rejected


# ══════════════════════════════════════════════════════════════════════
# Stage 2：LLM 精判
# ══════════════════════════════════════════════════════════════════════

SECTOR_JUDGE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "sector_relevance_batch",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "judgments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "candidate_id": {"type": "string"},
                            "content_genre": {
                                "type": "string",
                                "enum": ["EVENT", "DATA", "ANALYSIS", "ROUNDUP",
                                         "PROMO", "PRICE_NOISE"],
                            },
                            "is_primary_subject": {"type": "boolean"},
                            "is_constituent_anchor": {"type": "boolean"},
                            "transmission_hops": {"type": "integer"},
                            "entity_match": {"type": "number"},
                            "semantic_sim": {"type": "number"},
                            "focus_ratio": {"type": "number"},
                            "title_hit": {"type": "boolean"},
                            "matched_tickers": {"type": "array", "items": {"type": "string"}},
                            "reason": {"type": "string"},
                        },
                        "required": [
                            "candidate_id", "content_genre", "is_primary_subject",
                            "is_constituent_anchor", "transmission_hops",
                            "entity_match", "semantic_sim", "focus_ratio",
                            "title_hit", "matched_tickers", "reason",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["judgments"],
            "additionalProperties": False,
        },
    },
}

_TYPE_DEFINITION = {
    SECTOR_TYPE_TRACK: (
        '"Track" sector: the sector is the subject when a constituent coin, '
        "project, or the track-wide theme IS the event (a project's own "
        "upgrade/hack/listing, or a track-wide move like a broad rally/"
        'selloff/regulatory action). Being "also crypto" or "also blockchain" '
        "is NOT enough — the constituent or theme must be the actual subject."
    ),
    SECTOR_TYPE_CHAIN: (
        '"Chain-ecosystem" sector: the sector is the subject when the chain '
        "ITSELF has a major event (upgrade, outage, ecosystem data) or when a "
        "project NATIVELY IDENTIFIED with this chain has a major event. A "
        "project that merely also deploys on / bridges to / touches this "
        "chain, while its own story is about something else, is NOT this "
        "sector's subject — set is_constituent_anchor=false in that case, "
        "even if the chain's name literally appears in the text."
    ),
    SECTOR_TYPE_MECHANISM: (
        '"Platform-mechanism" sector: the sector is the subject when the '
        "MECHANISM ITSELF changes (a new project enters, a rule/yield/"
        "collateral change) or when one of the mechanism's actual "
        "constituent projects (or, for bStocks/tCommodities, the underlying "
        "stock/commodity) has its own major event. A generic \"this "
        "yield-bearing narrative supports the mechanism's vibe\" argument is "
        "NOT sufficient — that is narrative-proximity reasoning, which this "
        "sector type explicitly forbids."
    ),
}

SECTOR_JUDGE_SYSTEM_TEMPLATE = """You are a senior crypto content analyst judging whether each news item is genuinely relevant to ONE specific Binance sector, for a query-time "Sector Insight" recommendation feature. This is a much stricter judgment than generic sector tagging: the output feeds a hard relevance gate (final Rel < 0.5 is discarded entirely), so precision matters far more than recall. When in doubt, score LOW — the product principle is "宁缺毋滥" (recommend nothing rather than recommend something wrong).

## Target sector
Name: {sector}
Type: {type_label}
{type_definition}
Known constituents / anchor keywords (NOT exhaustive — a project can still be a genuine constituent even if not listed): {constituents}

## Judge each candidate through these steps

1. content_genre — classify first (it caps everything downstream):
   EVENT: single subject, single action, verifiable fact (listing/funding/regulation/hack/upgrade/partnership)
   DATA: on-chain data / fund flows / industry report with concrete numbers and a clear subject
   ANALYSIS: deep analysis/opinion with a clear thesis and a clear subject
   ROUNDUP: newsletter/morning-brief/weekly-review/multi-event list with NO single subject (headline patterns like "昨夜今晨/早报/晚报/一周回顾/重要资讯", or body that lists many unrelated events)
   PROMO: project self-promotion / partnership fluff with no substantive information / shilling
   PRICE_NOISE: bare price quote, "broke a round number" with no new information

2. entity_match (0-1, continuous): how strongly does a core constituent of THIS sector appear? Title mention = 1.0, first paragraph = 0.7, mid-body = 0.4, only in a trailing clause/footnote = 0.15. A same-named but UNRELATED asset (e.g. Apple Inc. vs a same-named meme coin, a stock ticker vs a crypto ticker) scores 0 — never let a name collision inflate this.

3. semantic_sim (0-1, continuous): overall topical closeness to the sector's theme, independent of exact naming. Being "also a crypto story" is NOT semantic closeness to THIS specific sector — e.g. a Layer-1 protocol upgrade is not semantically close to MEME just because both are crypto.

4. focus_ratio (0-1) and title_hit (bool): focus_ratio = roughly, of all the narrative attention in the item, what fraction belongs to this sector's constituents? A story primarily about something else (geopolitics, a CEO's personal account being hacked, a general market selloff) that only mentions a sector's coin in a background clause has LOW focus_ratio (<0.3) even if entity_match found the name somewhere. title_hit=true only if a sector constituent is literally the grammatical subject of the headline.

   CRITICAL: score the ORIGINAL text only. Ignore any "for sector X, this means…"-style reframing — that kind of framing never changes what the article is actually about and must never justify a higher score than the original content supports.

5. transmission_hops (0, 1, or 2 — use 2 to mean "2 or more"):
   0 = the sector/its constituent IS the direct subject, no inference needed
   1 = the item is about something that touches this sector (e.g. deployed on this chain, uses this mechanism) but is not itself this sector's subject — OR (mechanism sectors) it's about the sector's underlying single constituent's own major event, one inferential step away
   2 = reaching this sector requires >=2 inferential steps (general equity-market sentiment -> possible spillover; Web2 tech news -> "might matter for crypto AI"; "this feels narratively similar" reasoning)

6. is_constituent_anchor (bool): true only if the matched entity is a genuine member of THIS sector (a real constituent coin/project — or for chain-ecosystem sectors, a project NATIVE to this chain, not merely "also deployed here" — or for mechanism sectors, the mechanism itself or one of its actual listed projects). Being one of several chains that an interoperability/bridge protocol touches does NOT make that protocol a constituent of any single one of those chains.

7. matched_tickers: list ONLY tickers that are the actual subject/direct recipient of the event in the text (never "might be affected" tickers). If a name looks like a mainstream Web2 company/stock and you see no crypto-specific evidence ($TICKER, contract address, DEX pair) in the text, do NOT list it as a crypto ticker.

Output one judgment object per candidate, candidate_id copied exactly from the input, plus all fields above, and a <=40-word reason in Chinese explaining your call (especially for low scores — name the specific bad-case pattern if one applies: 顺带提及 / 同名误绑 / 跨板块 / 视角改写 / 汇总无主体 / 传导链过长 / 机制型叙事泛化)."""


def _build_system_prompt(sector: str, sector_def: dict) -> str:
    constituents = sorted(sector_def.get("tickers") or []) + list(sector_def.get("keywords") or [])
    return SECTOR_JUDGE_SYSTEM_TEMPLATE.format(
        sector=sector,
        type_label=f"{sector_def['type']} ({TYPE_LABEL_ZH.get(sector_def['type'], '')})",
        type_definition=_TYPE_DEFINITION[sector_def["type"]],
        constituents=", ".join(constituents[:40]) or "(no fixed list — mechanism-type sector, judge by the mechanism itself)",
    )


def _candidate_payload(cand: dict) -> dict:
    return {
        "candidate_id": cand["id"],
        "title_en": cand.get("title_en", "")[:200],
        "title_zh": cand.get("title_zh", "")[:100],
        "description_short_en": cand.get("description_short_en", "")[:500],
        "description_short_zh": cand.get("description_short_zh", "")[:300],
        "coins_detected": cand.get("coins", []),
    }


def _judge_batch(sector: str, sector_def: dict, batch: list[dict], client,
                 tracker=None) -> dict[str, dict]:
    system_prompt = _build_system_prompt(sector, sector_def)
    user_content = json.dumps(
        {"candidates": [_candidate_payload(c) for c in batch]},
        ensure_ascii=False,
    )

    last_error = None
    for attempt in range(LLM_MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format=SECTOR_JUDGE_SCHEMA,
            )
            if tracker is not None:
                tracker.record_chat(getattr(resp, "usage", None))
            parsed = json.loads(resp.choices[0].message.content)
            return {j["candidate_id"]: j for j in parsed.get("judgments", [])}
        except Exception as e:
            last_error = e
            message = str(e)
            if "429" in message or "rate_limited" in message:
                time.sleep(2 ** attempt + 1)
                continue
            if "402" in message or "insufficient_credits" in message:
                logger.error(f"Sector Insight LLM credits exhausted: {message[:120]}")
                return {}
            time.sleep(1)

    logger.warning(f"Sector Insight [{sector}] LLM judge batch failed after retries: {last_error}")
    return {}


def llm_judge(sector: str, candidates: list[dict], client, tracker=None) -> None:
    """就地给每个候选写入 LLM 判定的子信号字段。批量调用，一次最多
    LLM_BATCH_SIZE 条，避免逐条调用（成本控制的第二道闸，第一道是 Stage 1 预筛）。
    """
    sector_def = SECTOR_ANCHORS[sector]
    for start in range(0, len(candidates), LLM_BATCH_SIZE):
        batch = candidates[start:start + LLM_BATCH_SIZE]
        judgments = _judge_batch(sector, sector_def, batch, client, tracker)
        for cand in batch:
            j = judgments.get(cand["id"])
            if j is None:
                # LLM 没吐出这条的判断（批次失败/截断）：保守判 0，不是中性 0.5——
                # 缺失信息不该给它"benefit of the doubt"，与"宁缺毋滥"一致。
                cand["_judgment"] = None
                logger.warning(f"Sector Insight [{sector}] candidate {cand['id']} "
                               "missing from LLM judgment, treated as Rel=0")
                continue
            cand["_judgment"] = j


# ══════════════════════════════════════════════════════════════════════
# Rel 最终合成（Python 确定性规则，不直接信任 LLM 给的最终数字）
# ══════════════════════════════════════════════════════════════════════

_GENRE_CAP = {
    "EVENT": 1.0, "DATA": 1.0, "ANALYSIS": 0.85,
    "ROUNDUP": 0.2, "PROMO": 0.3, "PRICE_NOISE": 0.4,
}


def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def compute_relevance(judgment: dict, sector_def: dict) -> dict:
    """把 LLM 的子信号合成为最终 Rel，严格按 skill 文档公式 + 封顶规则。

    这是本模块的"自洽性约束"层，和 scoring.compute_impact() 用 event_tier
    区间夹紧 LLM 打分是同一个哲学：LLM 偶尔会被戏剧性措辞/名称撞车诱导给出
    越界的子信号组合（比如 entity_match 打得很高但其实是背景提及），这里用
    确定性规则重新收口，而不是直接采信 LLM 自己算出的分数。
    """
    sector_type = sector_def["type"]
    entity_match = _clip(float(judgment.get("entity_match", 0.0)))
    semantic_sim = _clip(float(judgment.get("semantic_sim", 0.0)))
    focus_ratio = _clip(float(judgment.get("focus_ratio", 0.0)))
    title_hit = bool(judgment.get("title_hit", False))

    focus_bonus = _clip(focus_ratio * (1 + 0.5 * (1.0 if title_hit else 0.0)))
    rel_raw = _clip(0.5 * entity_match + 0.3 * semantic_sim + 0.2 * focus_bonus)

    genre = judgment.get("content_genre", "EVENT")
    rel = min(rel_raw, _GENRE_CAP.get(genre, 1.0))

    hops = int(judgment.get("transmission_hops", 0) or 0)
    is_constituent = bool(judgment.get("is_constituent_anchor", False))
    cap_reasons = []
    if hops >= 2:
        rel = min(rel, 0.4)
        cap_reasons.append("传导链>=2跳封顶0.4（BC-1.6）")
    elif hops == 1 and not is_constituent:
        # 公链生态型的"仅部署在该链"陷阱用更严的 0.4（skill 文档补充定义 B
        # 明确给出的板块类型专属封顶，比 BC-1.6 通用的 1 跳 0.55 更紧——
        # "随便一个项目部署在这条链上"比"某只正股自己出财报"更弱的关联，
        # 理应封得更死）；其余板块类型沿用通用 1 跳封顶 0.55。
        if sector_type == SECTOR_TYPE_CHAIN:
            rel = min(rel, 0.4)
            cap_reasons.append("公链生态型仅'部署在该链'封顶0.4（补充定义B）")
        else:
            rel = min(rel, 0.55)
            cap_reasons.append("1跳非成分封顶0.55（BC-1.6通用规则）")

    matched = {normalize_ticker(t) for t in (judgment.get("matched_tickers") or [])}

    # 补充定义 C 规则 2：进入板块推荐时，若 matched_tickers ∩ 板块成分币白名单
    # = 空，且语义也不命中板块主题 → Rel 强制 <=0.3。只对"我们真的维护了固定
    # 成分币清单"的板块生效（tickers 非空）——机制型板块（Launchpool 等）的
    # 成分逐期变化，SECTOR_ANCHORS 里 tickers 特意留空，此时不适用这条规则，
    # 否则会把"确实相关但成分币不在静态清单里"的机制型内容也一并误伤。
    whitelist = sector_def.get("tickers") or set()
    if whitelist and matched and not (matched & whitelist) and semantic_sim < 0.5:
        rel = min(rel, 0.3)
        cap_reasons.append("matched_tickers与板块成分币白名单交集为空且语义不命中（补充定义C）")

    return {
        "relevance_score": round(_clip(rel), 4),
        "relevance_raw": round(rel_raw, 4),
        "entity_match": entity_match,
        "semantic_sim": semantic_sim,
        "focus_ratio": focus_ratio,
        "focus_bonus": round(focus_bonus, 4),
        "title_hit": title_hit,
        "content_genre": genre,
        "transmission_hops": hops,
        "is_constituent_anchor": is_constituent,
        "matched_tickers": sorted(matched),
        "cap_reason": "；".join(cap_reasons) or None,
        "llm_reason": judgment.get("reason", ""),
    }


# ══════════════════════════════════════════════════════════════════════
# 硬门 + 打分（T/H/A/M 直接复用 crawler/scoring.py）
# ══════════════════════════════════════════════════════════════════════

HARD_GATE_REL = 0.5


def hard_gate_and_score(candidates: list[dict], now: datetime | None = None,
                        baseline: float | None = None) -> None:
    """就地给每个候选写入 rel_result / score。Rel<0.5 的 score 强制为 0。

    T/H/A/M 全部调用 crawler.scoring 的现成函数，不重新实现——scoring.py 是
    只读依赖，这里只负责把它的输出和本模块算出的 Rel 组合。

    `baseline`（H 因子的 log 归一化分母）刻意由调用方算好传入，而不是在这里
    对 `candidates`（通常只是预筛后剩下的一小撮同板块候选）重新算：候选子集
    往往只有个位数到十几条，P95 在这种样本量下噪音很大，会让同一条新闻的
    H 分因为"这次查的是哪个板块"而抖动。基准应该反映"这一批数据整体的社交
    热度水平"，与查的是哪个板块无关，所以由 recommend_sector() 在**全量候选池**
    上算一次，所有板块共用——这样跨板块比较 H 分才有意义。不传时退化为对
    传入的 candidates 自己算（单测 / 独立调用场景的兜底）。
    """
    now = now or now_local()
    if baseline is None:
        baseline = social_baseline(candidates)

    for cand in candidates:
        judgment = cand.get("_judgment")
        if judgment is None:
            cand["rel_result"] = {"relevance_score": 0.0, "cap_reason": "LLM未返回判断"}
            cand["score"] = 0.0
            continue

        sector_def = SECTOR_ANCHORS[cand["_sector"]]
        rel_result = compute_relevance(judgment, sector_def)
        cand["rel_result"] = rel_result
        rel = rel_result["relevance_score"]

        if rel < HARD_GATE_REL:
            cand["score"] = 0.0
            continue

        T = compute_timeliness(cand, now)
        H = compute_hotness(cand, baseline)
        A = compute_authority(cand)
        M = compute_impact(cand)
        cand["_THAM"] = {"T": round(T, 4), "H": round(H, 4),
                         "A": round(A, 4), "M": round(M, 4)}
        cand["score"] = round((rel ** 1.5) * (0.25 * T + 0.25 * H + 0.20 * A + 0.30 * M), 4)


# ══════════════════════════════════════════════════════════════════════
# Sector Insight 专属去重（cosine >= 0.75）
# ══════════════════════════════════════════════════════════════════════
#
# 阈值标定说明：skill 文档明确要求 Sector Insight 场景用 0.75，区别于
# crawler/dedup.py 里 Macro Insight 已经标定过的 0.82（dedup.py 头部注释：
# 13 组人工标注配对，0.78~0.85 区间错误率为 0，取 0.82 偏精度）。两个场景
# 阈值不同是有意的，不是笔误：
#
#   Macro Insight 的去重对象是"全库事件流"，误合并（把两件真事当一件）的
#   代价是让一个真实事件从库里彻底消失，所以偏精度、阈值高。
#
#   Sector Insight 的去重对象是"已经通过 Rel>=0.5 硬门的、同一板块下的极少数
#   候选"（通常个位数到十几条），此时误漏判（把同一事件的两个编译当成两条
#   摆进 Top3）的代价——3 个位置被同一事件占 2 个——比误合并的代价更高
#   （事件流里少一条不影响别的位置，但 Top3 里重复直接砍掉三分之一的展示位）。
#   skill 文档 DC-2 举的线上真实 badcase（Pendle 路线图冒号/逗号变体、
#   LayerZero×Keeta 合作/达成合作变体）恰恰是 0.75~0.82 这个区间的真实重复，
#   卡在 Macro 的 0.82 会漏判，所以 Sector Insight 场景专门调低到 0.75，
#   宁可稍微牺牲一点精度（可能误合并两条本不完全相同但高度相似的候选），
#   也要堵住"同一事件占满 Top3"这个更贵的错误。
#
# 实测校验（见 --calibrate 输出）：在本次 508 条候选、5 板块的真实数据上，
# 0.75 阈值下没有出现"跨了 48h 时间窗仍强行合并"的误合并（叠加时间窗约束），
# 也确认了至少一组文档点名的真实变体（同一事件不同信源转述）落在 0.75~0.82
# 区间、会被 Macro 阈值漏判但被这里的 0.75 正确合并——具体样本见报告正文。
DEDUP_COSINE_THRESHOLD = 0.75
DEDUP_TIME_WINDOW_HOURS = 48


def dedup_survivors(survivors: list[dict]) -> tuple[list[dict], list[dict]]:
    """对通过硬门的候选做本板块专属去重，返回 (代表条列表, 被折叠条列表)。

    代表条选择规则与 skill 文档"超重去重"章节一致：Score 更高者优先（Score
    已经把 Rel/T/H/A/M 全部综合进去，比单独比 Authority 更贴合"这条该不该
    代表整簇"的产品意图），Score 相同则选 Authority 更高者。
    """
    n = len(survivors)
    if n <= 1:
        return survivors, []

    vectors = [c.get("_embedding") for c in survivors]
    have_vec = [i for i, v in enumerate(vectors) if v is not None]

    uf = _UnionFind(n)
    if len(have_vec) > 1:
        matrix = np.stack([vectors[i] for i in have_vec]).astype(np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = matrix / np.maximum(norms, 1e-9)
        sim = matrix @ matrix.T
        for a in range(len(have_vec)):
            for b in range(a + 1, len(have_vec)):
                if sim[a][b] < DEDUP_COSINE_THRESHOLD:
                    continue
                i, j = have_vec[a], have_vec[b]
                hours = abs((survivors[i]["_published_dt"] - survivors[j]["_published_dt"])
                           .total_seconds()) / 3600 if (survivors[i].get("_published_dt")
                           and survivors[j].get("_published_dt")) else 0.0
                if hours <= DEDUP_TIME_WINDOW_HOURS:
                    uf.union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(uf.find(i), []).append(i)

    representatives, folded = [], []
    for indices in clusters.values():
        group = [survivors[i] for i in indices]
        rep = max(group, key=lambda c: (c["score"], c.get("_THAM", {}).get("A", 0)))
        rep["_folded_ids"] = [c["id"] for c in group if c["id"] != rep["id"]]
        rep["_folded_count"] = len(group) - 1
        representatives.append(rep)
        for c in group:
            if c["id"] != rep["id"]:
                c["filtered_reason"] = f"去重折叠：与更高分候选 {rep['id']} 判定为同一事件（Sector Insight cosine>=0.75）"
                folded.append(c)

    representatives.sort(key=lambda c: -c["score"])
    return representatives, folded


# ══════════════════════════════════════════════════════════════════════
# 候选池获取
# ══════════════════════════════════════════════════════════════════════

DEFAULT_CANDIDATE_HOURS = 72
MAX_RECOMMEND = 3

_CANDIDATE_SQL = """
SELECT id, title_en, title_zh, description_short_en, description_short_zh,
       coins, entities, sectors, time_event, time_get_data,
       score_market_impact, event_tier, social_interactions, source_count,
       score_authority, is_rumor, verification_status,
       sources, source_names, sentiment, embedding
  FROM news_events
 WHERE COALESCE(time_event, time_get_data) >= %s
 ORDER BY COALESCE(time_event, time_get_data) DESC
"""


def _load_json(raw, default):
    if raw is None:
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def fetch_candidates(conn, hours: int = DEFAULT_CANDIDATE_HOURS) -> list[dict]:
    """取候选池：时间窗内全部事件（不按写入时 sectors 预筛）。

    刻意不用 `WHERE JSON_CONTAINS(sectors, ...)` 缩窄候选池——那是写入时内容
    理解 agent 的宽泛判断，本模块存在的意义正是不完全信任那一层，要能捞回
    "写入时没被打上这个板块标签、但其实高度相关"的漏网内容，也要能压低
    "写入时打了标签但其实是 bad case"的内容（比如 LayerZero×Keeta 被写入时
    打了 Solana 0.58，本模块需要能独立把它判低）。时间窗内全量候选交给
    Stage 1 预筛做成本控制，而不是靠 sectors 字段做候选池的第一道过滤。
    """
    since = (now_local() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.cursor()
    cursor.execute(_CANDIDATE_SQL, (since,))
    rows = cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    cursor.close()

    candidates = []
    for row in rows:
        d = dict(zip(cols, row))
        published_dt = d.get("time_event") or d.get("time_get_data")
        if published_dt and published_dt.tzinfo is None:
            published_dt = published_dt.replace(tzinfo=timezone.utc)
        cand = {
            "id": d["id"],
            "title_en": d.get("title_en") or "",
            "title_zh": d.get("title_zh") or "",
            "description_short_en": d.get("description_short_en") or "",
            "description_short_zh": d.get("description_short_zh") or "",
            "coins": _load_json(d.get("coins"), []),
            "entities": _load_json(d.get("entities"), []),
            "sectors": _load_json(d.get("sectors"), []),
            "published_at": published_dt.isoformat() if published_dt else None,
            "_published_dt": published_dt,
            "score_market_impact": d.get("score_market_impact"),
            "event_tier": d.get("event_tier") or "C",
            "social_interactions": d.get("social_interactions") or 0,
            "source_count": d.get("source_count") or 1,
            "score_authority": d.get("score_authority"),
            "is_rumor": bool(d.get("is_rumor")),
            "verification_status": d.get("verification_status") or "",
            "sources": _load_json(d.get("sources"), []),
            "source_names": _load_json(d.get("source_names"), []),
            "sentiment": d.get("sentiment") or "neutral",
            "_embedding": blob_to_embedding(d.get("embedding")),
        }
        candidates.append(cand)
    return candidates


# ══════════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════════

def recommend_sector(sector: str, conn, hours: int = DEFAULT_CANDIDATE_HOURS,
                     limit: int = MAX_RECOMMEND, client=None, tracker=None,
                     lang: str = "zh") -> dict:
    """给定板块，返回 Top N 推荐 + filtered_out + （宁缺毋滥时的）empty_reason。

    这是 api/sector_insight.py 调的唯一入口，也可以直接 CLI / 单元测试调用。
    """
    if sector not in SECTOR_ANCHORS:
        return {"sector": sector, "recommended": [], "filtered_out": [],
               "empty_reason": f"未知板块 '{sector}'，不在 SECTOR_LABELS 内", "stats": {}}

    client = client or get_openai_client()
    # 下界 1 而非 0：limit=0 会白跑整套预筛+LLM 精判然后返回空（API 层已同样钳制，
    # 这里是给直连本函数的调用方兜底，两处口径一致）
    limit = max(1, min(limit, MAX_RECOMMEND))

    pool = fetch_candidates(conn, hours)
    if not pool:
        return {"sector": sector, "recommended": [], "filtered_out": [],
               "empty_reason": "EMPTY_POOL：时间窗口内无候选内容", "stats": {"pool_size": 0}}

    for c in pool:
        c["_sector"] = sector

    passed, prefilter_rejected = prefilter_candidates(pool, sector, client, tracker)

    if not passed:
        return {
            "sector": sector, "recommended": [],
            "filtered_out": [_summarize_filtered(c) for c in prefilter_rejected[:20]],
            "empty_reason": "NO_RELEVANT_CONTENT：候选池中无 Rel>=0.5 内容（预筛阶段全部低于阈值）",
            "stats": {"pool_size": len(pool), "prefilter_passed": 0, "prefilter_rejected": len(prefilter_rejected)},
        }

    llm_judge(sector, passed, client, tracker)
    now = now_local()
    pool_baseline = social_baseline(pool)   # 见 hard_gate_and_score() 注释：全量池共享同一基准
    hard_gate_and_score(passed, now, baseline=pool_baseline)

    survivors = [c for c in passed if c["score"] > 0]
    hard_gate_rejected = [c for c in passed if c["score"] <= 0]
    for c in hard_gate_rejected:
        rel = c.get("rel_result", {})
        c["filtered_reason"] = (
            f"硬门淘汰（Rel={rel.get('relevance_score', 0):.3f} < {HARD_GATE_REL}）："
            f"体裁={rel.get('content_genre', '?')}，{rel.get('cap_reason') or rel.get('llm_reason', '')}"
        )

    if not survivors:
        # ROUNDUP(0.2)/PROMO(0.3)/PRICE_NOISE(0.4) 的体裁上限本身就低于硬门 0.5，
        # 命中这三个体裁必然被淘汰，与其它子信号无关——用它做"是不是体裁害的"判据。
        all_genre_capped = bool(hard_gate_rejected) and all(
            c.get("rel_result", {}).get("content_genre") in ("ROUNDUP", "PROMO", "PRICE_NOISE")
            for c in hard_gate_rejected
        )
        empty_reason = (
            "ALL_GENRE_DISQUALIFIED：候选全部因体裁不合格（ROUNDUP/PROMO/PRICE_NOISE）被淘汰"
            if all_genre_capped else
            "NO_RELEVANT_CONTENT：候选池中无 Rel>=0.5 内容"
        )
        return {
            "sector": sector, "recommended": [],
            "filtered_out": [_summarize_filtered(c) for c in (hard_gate_rejected + prefilter_rejected)[:20]],
            "empty_reason": empty_reason,
            "stats": {"pool_size": len(pool), "prefilter_passed": len(passed),
                     "llm_judged": len(passed), "hard_gate_survivors": 0},
        }

    representatives, folded = dedup_survivors(survivors)

    if not representatives:
        # 理论安全网分支：正常不会触发（去重只会合并、不会让代表条数变 0），
        # 保留是为了不让 union-find 的潜在 bug 悄悄产出"看起来正常但其实是
        # 空推荐"的结果——一旦触发说明去重逻辑本身有问题，需要报警排查。
        return {
            "sector": sector, "recommended": [],
            "filtered_out": [_summarize_filtered(c) for c in folded[:20]],
            "empty_reason": "ALL_DEDUPED_AWAY：候选去重后代表条数为 0（异常分支，需排查去重逻辑）",
            "stats": {"pool_size": len(pool), "hard_gate_survivors": len(survivors)},
        }

    top = representatives[:limit]
    not_selected = representatives[limit:]   # 过了硬门+去重，但排名超出 Top N
    for c in not_selected:
        rel = c.get("rel_result", {})
        c["filtered_reason"] = (
            f"已通过硬门与去重（Rel={rel.get('relevance_score', 0):.3f}，"
            f"Score={c['score']:.3f}），但排名超出 Top{limit}，未入选——不是"
            "被判定不相关，只是这一轮相关内容比位置多。"
        )

    recommended = []
    for rank, cand in enumerate(top, start=1):
        recommended.append(_format_recommendation(cand, rank, lang))

    # 注意：not_selected 排在最前面——它们是"真相关但没位置"，比 hard_gate_rejected/
    # folded/prefilter_rejected 更有信息量，30 条预览额度优先给它们，避免真正有
    # 价值的候选被挤出预览之外（这几类总数通常远小于 prefilter_rejected 的量级）。
    filtered_out = [_summarize_filtered(c) for c in
                    (not_selected + hard_gate_rejected + folded + prefilter_rejected)][:30]

    return {
        "sector": sector,
        "recommended": recommended,
        "filtered_out": filtered_out,
        # 走到这里 representatives 必然非空（上面已经处理了空的分支）；recommended
        # 为空只可能是调用方显式传了 limit=0，不是"宁缺毋滥"式的稀疏结果，
        # 所以不附 empty_reason —— 附了反而会误导前端以为板块没有相关内容。
        "empty_reason": None,
        "stats": {
            "pool_size": len(pool),
            "prefilter_passed": len(passed),
            "prefilter_rejected": len(prefilter_rejected),
            "llm_judged": len(passed),
            "hard_gate_survivors": len(survivors),
            "after_dedup": len(representatives),
            "folded_by_dedup": len(folded),
            "returned": len(recommended),
            "relevant_but_not_selected": len(not_selected),
        },
    }


def _format_recommendation(cand: dict, rank: int, lang: str) -> dict:
    rel = cand.get("rel_result", {})
    tham = cand.get("_THAM", {})
    title = cand.get("title_zh") if lang == "zh" and cand.get("title_zh") else cand.get("title_en")
    summary = cand.get("description_short_zh") if lang == "zh" and cand.get("description_short_zh") \
        else cand.get("description_short_en")
    return {
        "rank": rank,
        "event_id": cand["id"],
        "title": title,
        "summary": summary,
        "score": cand["score"],
        "relevance_score": rel.get("relevance_score"),
        "labels": {
            "T": tham.get("T"), "H": tham.get("H"), "A": tham.get("A"), "M": tham.get("M"),
            "sentiment": (cand.get("sentiment") or "neutral").upper(),
        },
        "related_tickers": rel.get("matched_tickers", []),
        "content_genre": rel.get("content_genre"),
        "event_cluster_id": cand["id"],
        "folded_count": cand.get("_folded_count", 0),
        "folded_ids": cand.get("_folded_ids", []),
        "reason": rel.get("llm_reason", ""),
    }


def _summarize_filtered(cand: dict) -> dict:
    rel = cand.get("rel_result", {})
    title = cand.get("title_zh") or cand.get("title_en")
    return {
        "event_id": cand.get("id"),
        "title": title,
        "relevance_score": rel.get("relevance_score"),
        "reason": cand.get("filtered_reason", ""),
    }


# ══════════════════════════════════════════════════════════════════════
# CLI：python -m crawler.sector_relevance --sector MEME --hours 72
# ══════════════════════════════════════════════════════════════════════

def _main() -> None:
    import argparse

    from . import storage
    from .usage_tracker import UsageTracker

    parser = argparse.ArgumentParser(description="Sector Insight 手动测试")
    parser.add_argument("--sector", required=True, choices=sorted(SECTOR_ANCHORS.keys()))
    parser.add_argument("--hours", type=int, default=DEFAULT_CANDIDATE_HOURS)
    parser.add_argument("--limit", type=int, default=MAX_RECOMMEND)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    conn = storage.get_mysql_conn()
    tracker = UsageTracker()
    try:
        result = recommend_sector(args.sector, conn, hours=args.hours, limit=args.limit, tracker=tracker)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        tracker.log_summary()
    finally:
        conn.close()


if __name__ == "__main__":
    _main()
