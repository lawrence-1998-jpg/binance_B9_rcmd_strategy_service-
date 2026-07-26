"""
Macro Insight v1 打分。

    Score = 0.35·M + 0.20·T + 0.15·H + 0.15·A + 0.15·Q     （纯加权，无硬门）

因子口径见 docs/skill-macro-news-recommendation-v1.md 第二章。本模块只负责把 LLM
给出的原始分与管线算出的信号合成为最终分，不做召回或过滤。
"""
import logging
import math
from datetime import datetime, timezone

from . import verification
from .dedup import parse_dt
from .timeutil import now_local

logger = logging.getLogger(__name__)

# 权重（合计 1.0）
W_IMPACT, W_TIME, W_HOT, W_AUTH, W_QUAL = 0.35, 0.20, 0.15, 0.15, 0.15

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


# ── 合成 ─────────────────────────────────────────────────────────────

def compute_macro_score(event: dict, baseline: float,
                        now: datetime | None = None) -> dict:
    """算出五因子分与加权总分，返回可直接写库的字段字典。"""
    M = compute_impact(event)
    T = compute_timeliness(event, now)
    H = compute_hotness(event, baseline)
    A = compute_authority(event)
    Q = compute_quality(event)

    score = W_IMPACT * M + W_TIME * T + W_HOT * H + W_AUTH * A + W_QUAL * Q

    return {
        "score_market_impact": round(M, 4),
        "score_timeliness":    round(T, 4),
        "score_hotness":       round(H, 4),
        "score_authority":     round(A, 4),
        "score_quality":       round(Q, 4),
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
