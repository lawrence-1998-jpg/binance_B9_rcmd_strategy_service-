"""
Macro Insight v1 打分。

    Score = 0.35·M + 0.20·T + 0.15·H + 0.15·A + 0.15·Q     （纯加权，无硬门）

因子口径见 docs/skill-macro-news-recommendation-v1.md 第二章。本模块只负责把 LLM
给出的原始分与管线算出的信号合成为最终分，不做召回或过滤。
"""
import logging
import math
import re
from datetime import datetime, timezone

from . import verification
from .dedup import parse_dt
from .timeutil import now_local

logger = logging.getLogger(__name__)

# 权重（合计 1.0）
#
# 2026-07-29 从五因子扩到七因子（PRD-03 / ADR-001）。M 从 0.35 让出空间给
# 两个新因子；H 和 A 各降 0.05，因为 I（冲击力）的"权威共振"子项已经吸收了
# 一部分"多家权威媒体同时报道"的信号，不降就是重复计分。
#
# Lawrence 明确"排不对也没关系，都放到策略实验室里我自己调"，所以这组数字
# 是**起点不是结论**，真正的调参在 04/05 tab 上做。
W_IMPACT, W_BREADTH, W_TIME, W_PUNCH, W_HOT, W_AUTH, W_QUAL = (
    0.26, 0.16, 0.16, 0.14, 0.10, 0.10, 0.08)

# event_tier 对应的 M 值区间，用于约束 LLM 可能越界的打分
TIER_BOUNDS = {
    "S": (0.85, 1.00),
    "A": (0.60, 0.84),
    "B": (0.35, 0.59),
    "C": (0.15, 0.34),
    "D": (0.00, 0.14),
}

TIMELINESS_HALFLIFE_HOURS = 24   # 文档 2.2：T = e^(-λΔt)，λ = ln2/24
HOTNESS_SOURCE_CAP = 8           # 文档 2.3：独立信源数 8 家以上封顶
SOCIAL_BASELINE_FLOOR = 500      # 社交基准下限，防止冷启动时少量互动就被归一成满分


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


# ── M：影响面 ────────────────────────────────────────────────────────

def compute_impact(event: dict) -> float:
    """LLM 给出的 score_market_impact，按 event_tier 区间夹紧。

    夹紧是必要的：LLM 偶尔会给 D 级事件打 0.6 的影响分（典型如被"黑客""崩盘"
    等戏剧性词汇诱导），tier 区间是它自己判的，用作自洽性约束。
    """
    raw = float(event.get("score_market_impact", 0.5) or 0.0)
    lo, hi = TIER_BOUNDS.get(event.get("event_tier", "C"), (0.0, 1.0))
    return _clamp(raw, lo, hi)


# ── T：时效 ──────────────────────────────────────────────────────────

def compute_timeliness(event: dict, now: datetime | None = None) -> float:
    """按事件真实发布时间做 24h 半衰期指数衰减。

    时间解析失败时给 0.5 中性分，而不是 0——解析失败是我们的数据问题，
    不该让内容白白背锅沉底。
    """
    published = parse_dt(event.get("published_at"))
    if published is None:
        return 0.5
    now = now or now_local()
    hours_ago = max(0.0, (now - published).total_seconds() / 3600)
    return _clamp(math.exp(-hours_ago * math.log(2) / TIMELINESS_HALFLIFE_HOURS))


# ── H：热度 ──────────────────────────────────────────────────────────

def social_baseline(events: list[dict]) -> float:
    """本轮社交互动量的 P95，作为 log 归一化的分母基准。

    用批内 P95 而非固定常数，是为了让热度随大盘活跃度自适应：淡季几百互动就算热，
    旺季同样的数字只是平均水平。下限 SOCIAL_BASELINE_FLOOR 防止某轮 X 拉取失败
    （互动全 0 或极小）时，任何一点互动都被归一化成高分。
    """
    values = [e.get("social_interactions", 0) or 0 for e in events]
    values = [v for v in values if v > 0]
    if not values:
        return float(SOCIAL_BASELINE_FLOOR)
    values.sort()
    p95 = values[min(len(values) - 1, int(len(values) * 0.95))]
    return float(max(p95, SOCIAL_BASELINE_FLOOR))


def compute_hotness(event: dict, baseline: float) -> float:
    """H = 0.6·log归一(社交互动) + 0.4·min(独立信源数 / 8, 1)

    此前的实现只有信源数那一半，X KOL 的赞/转/评/引数据明明已经落在 x_raw_posts
    表里却完全没接进来——这正是文档给社交互动 0.6 权重要解决的信号。
    """
    social = max(0, int(event.get("social_interactions", 0) or 0))
    social_part = math.log10(1 + social) / math.log10(1 + baseline)

    sources = max(1, int(event.get("source_count", 1) or 1))
    source_part = min(sources / HOTNESS_SOURCE_CAP, 1.0)

    return _clamp(0.6 * _clamp(social_part) + 0.4 * source_part)


# ── A：权威 ──────────────────────────────────────────────────────────

def compute_authority(event: dict) -> float:
    """LLM 给出的信源权威分，谣言打 7 折（文档 2.4），再按真实性校验结论降权。

    两道折扣叠加是有意的，它们防的是不同东西：`is_rumor` 是 LLM 从**文本措辞**
    判断的（"据传"/"消息人士"），而 verification 看的是**客观信号**（几家独立
    机构报道、信源可信度分层、有无矛盾报道）。一条写得像板上钉钉、但只有一个
    陌生账号说的消息，LLM 不会标 rumor，只有校验层能压住它。
    """
    authority = _clamp(float(event.get("score_authority", 0.5) or 0.0))
    if event.get("is_rumor"):
        authority *= 0.7
    return _clamp(authority * verification.authority_multiplier(event))


# ── Q：质量 ──────────────────────────────────────────────────────────

def compute_quality(event: dict) -> float:
    """LLM 给出的信噪质量分（标题党/软文/低信息密度扣分）。"""
    return _clamp(float(event.get("score_quality", 0.5) or 0.0))


# ── B：广度（2026-07-29 新增，PRD-03 R2）─────────────────────────────
#
# 「影响一个指数」和「影响一只股票」是完全不同的量级，而此前系统里没有任何
# 字段区分这件事——这正是我们的内容质感与 CNBC 差异的根源：他们首屏是
# "Dow rallies 600 points"（指数级），我们是"分析师比较联合太平洋与诺福克南方"
# （个股级），两者在旧的五因子下可能拿到相近的分。
#
# 值由 LLM 的 breadth_level 映射而来，不让模型直接给 0-1 分——枚举比连续分
# 稳定得多，模型在"这是板块级还是多标的级"上比在"这该给 0.55 还是 0.6"上
# 可靠。缺失时给 single_asset 的值：拿不准就当窄的，避免把噪音抬上来。
BREADTH_VALUES = {
    "cross_market": 1.00,   # 跨市场/跨资产类别：美联储决议、全球债市抛售、战争扰动油路
    "market_index": 0.80,   # 单一市场大盘：日经跌4%、KOSPI熔断、道指涨600点
    "sector":       0.60,   # 板块级：芯片股集体重挫、DeFi 普跌
    "multi_asset":  0.35,   # 2-5 个具名标的：AMD/美光/英伟达同步下跌
    "single_asset": 0.15,   # 单一公司/代币
}
BREADTH_DEFAULT = BREADTH_VALUES["single_asset"]


def compute_breadth(event: dict) -> float:
    return BREADTH_VALUES.get(event.get("breadth_level"), BREADTH_DEFAULT)


# ── I：冲击力（2026-07-29 新增，PRD-03 R3）───────────────────────────
#
# Lawrence 的原始描述包含三个成分，逐一对照现有因子后**只保留两个**：
#   · 数值幅度（跌18%/涨600点）—— 现有因子完全没捕获，✅ 真新增，是本因子核心
#   · 多家权威媒体报道 —— H 因子里有 min(信源数/8,1) 但被社交互动稀释，
#     A 因子只看单一最高权威，⚠️ 部分覆盖，用"权威共振"子项补强
#   · 对社会经济重大影响 —— ❌ 已被 M（影响面）+ B（广度）覆盖两遍，
#     再单列就是三重计分，**刻意不做**
#
# 全部纯计算，0 次 LLM 调用。
W_PUNCH_MAGNITUDE, W_PUNCH_RESONANCE = 0.65, 0.35

# 幅度提取。只做**百分比**，金额/点数放后续——百分比覆盖了绝大多数有冲击力的
# 标题，且量纲统一、误判风险最低（金额要处理亿/万/M/B 多种量纲，点数要知道
# 指数基数才有意义）。
#
# 排除项是踩过的坑的产物：不能匹配到"2026年""第57期""涨幅超过"这种，
# 所以要求百分号紧跟数字，且数字前不能是年份特征。
_PCT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")

# 无数字但本身就意味着剧烈波动的词。命中直接给满分——"熔断""崩盘"不需要
# 再看百分比，它们的语义就是极端。
_EXTREME_WORDS_RE = re.compile(
    r"熔断|崩盘|暴跌|暴涨|涨停|跌停|重挫|狂飙|闪崩|清零|归零|"
    r"circuit breaker|crash|plunge|plummet|soar|surge|collapse|rout",
    re.IGNORECASE)


def extract_magnitude_pct(text: str) -> float | None:
    """从标题/摘要里抽最大的百分比幅度。返回 None 表示没抽到。"""
    if not text:
        return None
    vals = []
    for m in _PCT_RE.finditer(text):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        # >100% 的多半是"上涨800倍""市值占GDP137%"这类非涨跌幅语境，
        # 不参与冲击力判定，避免把统计数字当成暴涨暴跌。
        if 0 < v <= 100:
            vals.append(v)
    return max(vals) if vals else None


def _magnitude_score(pct: float | None, text: str) -> float:
    if _EXTREME_WORDS_RE.search(text or ""):
        return 1.0
    if pct is None:
        return 0.10
    if pct >= 15:
        return 1.00
    if pct >= 8:
        return 0.75
    if pct >= 4:
        return 0.55
    if pct >= 2:
        return 0.35
    return 0.10


def _resonance_score(event: dict) -> float:
    """权威共振：几家 authority≥4 的独立机构在报同一件事。

    与 H 因子里的信源数不同：H 数的是**所有**信源（含匿名 X 账号），
    这里只数**权威机构**，且不被社交互动稀释——"三家一线财经媒体同时报"
    本身就是"这是件大事"的强信号。
    """
    sources = event.get("sources") or []
    authoritative = 0
    top_tier = False
    for s in sources:
        try:
            a = int(s.get("authority") or 0)
        except (TypeError, ValueError):
            a = 0
        if a >= 4:
            authoritative += 1
        if a >= 5:
            top_tier = True
    if authoritative >= 3:
        return 1.00
    if authoritative == 2:
        return 0.65
    if top_tier:
        return 0.45
    return 0.15


def compute_punch(event: dict) -> dict:
    """返回 {"score": 0-1, "magnitude_pct": float|None}。

    取标题 + 短摘要做幅度提取——长摘要里常有历史对比数字（"较2020年涨40%"），
    会把冲击力判高。标题和短摘要说的是"现在发生了什么"。
    """
    text = " ".join(filter(None, [
        event.get("title_zh") or event.get("title") or "",
        event.get("title_en") or "",
        event.get("description_short_zh") or "",
    ]))
    pct = extract_magnitude_pct(text)
    score = (W_PUNCH_MAGNITUDE * _magnitude_score(pct, text)
             + W_PUNCH_RESONANCE * _resonance_score(event))
    return {"score": _clamp(score), "magnitude_pct": pct}


# ── 合成 ─────────────────────────────────────────────────────────────

def compute_macro_score(event: dict, baseline: float,
                        now: datetime | None = None) -> dict:
    """算出七因子分与加权总分，返回可直接写库的字段字典。

    注意这里算的是 **BaseScore**——情绪同向/反转两个加分项**不在这里应用**，
    它们只在查询/展示时作为外层倍率生效（ADR-001 D2）。理由：加分项依赖
    `mood_score` 这个每天都在变的全局量，写进库会让跨天的分数不可比，
    而 importance_score 是策略实验室、去重、历史分析共同依赖的口径。
    """
    M = compute_impact(event)
    B = compute_breadth(event)
    T = compute_timeliness(event, now)
    punch = compute_punch(event)
    I = punch["score"]
    H = compute_hotness(event, baseline)
    A = compute_authority(event)
    Q = compute_quality(event)

    score = (W_IMPACT * M + W_BREADTH * B + W_TIME * T + W_PUNCH * I
             + W_HOT * H + W_AUTH * A + W_QUAL * Q)

    return {
        "score_market_impact": round(M, 4),
        "score_breadth":       round(B, 4),
        "score_timeliness":    round(T, 4),
        "score_punch":         round(I, 4),
        "score_hotness":       round(H, 4),
        "score_authority":     round(A, 4),
        "score_quality":       round(Q, 4),
        "punch_magnitude_pct": punch["magnitude_pct"],
        "importance_score":    round(score, 4),
    }


def score_events(events: list[dict], now: datetime | None = None) -> list[dict]:
    """给整批事件打分（批内共享同一个社交基准）。"""
    baseline = social_baseline(events)
    now = now or now_local()
    for event in events:
        event["scores"] = compute_macro_score(event, baseline, now)
    logger.info(f"Scored {len(events)} events (social baseline P95={baseline:.0f})")
    return events
