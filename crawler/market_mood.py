"""
大盘情绪聚合 —— crawler/market_mood.py

背景（2026-07-28，老板经产品同事转达）：B9 接入美股/港股/日股/韩股/世界宏观新闻后，
排序不能只是把这些事件和币圈新闻简单拼在一起——"如果整个市场都是悲观大新闻，那么
就要大悲观，反过来就要大乐观"，"排序结果尤其是首几刷要有冲击力"。这就是那次日韩
股市大跌当天，PM 在群里问的那个问题："目前 B9 与我相关页的内容...尚未传出这个关键
信息与氛围"——本模块就是用来接住这个问题的。

## 设计取舍

1. **只用高重要性事件计入情绪**（MOOD_MIN_IMPORTANCE），长尾低分事件（个股小道消息、
   常规数据播报）不该左右"大盘情绪"这种粗粒度判断——一条 C/D 档的推文情绪不该和
   "日经暴跌4%"这种 S 档事件在情绪聚合里权重相当。

2. **不碰 crawler/scoring.py 的五因子公式**。情绪对齐加成（mood_alignment_multiplier）
   只在 API 查询/展示时应用于排序，绝不写回 news_events.importance_score——那个字段
   是策略实验室、去重、历史分析全部依赖的口径，一旦被"今天的情绪"污染，昨天算出的分
   和今天算出的分就不可比了。这是一个纯展示层的、有界（≤15%）、可随时关掉的加成，
   不是排序公式的第 6 个因子。

3. **加成有方向性但不是单向放大**：只有当某条事件的情绪方向与大盘一致时才加成，
   反向或大盘接近中性时不加成也不减成——这样"大悲观时段"里少数逆势乐观的消息不会被
   排序打压到看不见，用户仍然能看到"情况没有那么糟"的信号，只是不会被推到最前面。
"""

# 48 小时而不是字面意义的"今天"：主流水线现在是每 2 天 1 轮（2026-07-27 起，
# 见 WORKLOG #57），24 小时窗口会在两轮之间大概率"无数据可用"——48 小时保证
# 无论什么时候查，至少覆盖最近一轮的产出，不会出现"情绪横幅经常性显示不可用"
# 这种看起来像故障的空窗。
MOOD_LOOKBACK_HOURS = 48

# 只统计 B 档及以上（Macro Insight 的 M 值区间对应 importance_score 大致同尺度）
# 的事件，理由见模块头部说明。
MOOD_MIN_IMPORTANCE = 0.35

# (下界（含）, 中文标签, 英文标签, 前端配色语义)
_MOOD_BUCKETS = [
    (0.50,  "极度乐观", "extreme_bullish", "green"),
    (0.15,  "偏乐观",   "bullish",         "green"),
    (-0.15, "中性",     "neutral",         "neutral"),
    (-0.50, "偏悲观",   "bearish",         "red"),
    (-1.01, "极度悲观", "extreme_bearish", "red"),
]

# 有界加成上限——排序"首几刷冲击力"用。15% 是刻意保守的数字：五因子公式里最小的
# 权重（Q，质量）都有 0.15，情绪加成不该比一个正式因子的权重还大，否则就是变相
# 把它做成了第六个因子而不是展示层的调味。
MOOD_ALIGN_BOOST = 0.15


def mood_bucket(mood_score: float) -> tuple[str, str, str]:
    for lo, zh, en, color in _MOOD_BUCKETS:
        if mood_score >= lo:
            return zh, en, color
    return "中性", "neutral", "neutral"


def compute_market_mood(events: list[dict]) -> dict:
    """events：近 MOOD_LOOKBACK_HOURS 小时内的事件字典列表，每条至少含
    sentiment_score / importance_score，展示用的话再带上 id/title_zh/market_scope。

    返回的 mood_score 是重要性加权平均情绪，范围 [-1, 1]。
    """
    scored = [e for e in events
             if e.get("sentiment_score") is not None
             and (e.get("importance_score") or 0) >= MOOD_MIN_IMPORTANCE]
    if not scored:
        return {
            "available": False,
            "reason": f"近 {MOOD_LOOKBACK_HOURS} 小时内没有 importance_score >= "
                      f"{MOOD_MIN_IMPORTANCE} 的事件参与计算",
            "sample_size": 0,
        }

    total_weight = sum(e["importance_score"] for e in scored)
    mood_score = sum(e["sentiment_score"] * e["importance_score"] for e in scored) / total_weight
    mood_score = max(-1.0, min(1.0, mood_score))
    zh, en, color = mood_bucket(mood_score)

    # 贡献最大的几条：跟大盘同向、且 |情绪|×重要性 最高的——这些是"解释这个情绪
    # 判断从哪来"的证据链，前端横幅直接引用，用户能一眼验证这个判断是否合理。
    same_dir = [e for e in scored if (e["sentiment_score"] >= 0) == (mood_score >= 0)]
    top = sorted(same_dir, key=lambda e: abs(e["sentiment_score"]) * e["importance_score"],
                reverse=True)[:3]

    return {
        "available": True,
        "mood_score": round(mood_score, 3),
        "label_zh": zh, "label_en": en, "color": color,
        "sample_size": len(scored),
        "lookback_hours": MOOD_LOOKBACK_HOURS,
        "min_importance": MOOD_MIN_IMPORTANCE,
        "top_events": [
            {"id": e.get("id"), "title_zh": e.get("title_zh"),
             "sentiment_score": e.get("sentiment_score"),
             "market_scope": e.get("market_scope")}
            for e in top
        ],
    }


def mood_alignment_multiplier(event_sentiment_score, mood_score) -> float:
    """情绪与大盘同向时的有界排序加成；反向或任一方为 None 时返回 1.0（不调整）。

    只应用于查询时的展示排序，绝不写回 importance_score——见模块头部说明 2。
    """
    if event_sentiment_score is None or mood_score is None:
        return 1.0
    if (event_sentiment_score >= 0) != (mood_score >= 0):
        return 1.0
    return 1.0 + MOOD_ALIGN_BOOST * abs(mood_score) * abs(event_sentiment_score)
