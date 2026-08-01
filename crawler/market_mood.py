"""
大盘情绪聚合 —— crawler/market_mood.py

背景（2026-07-28，老板经产品同事转达）：B9 接入美股/港股/日股/韩股/世界宏观新闻后，
排序不能只是把这些事件和币圈新闻简单拼在一起——"如果整个市场都是悲观大新闻，那么
就要大悲观，反过来就要大乐观"，"排序结果尤其是首几刷要有冲击力"。这就是那次日韩
股市大跌当天，PM 在群里问的那个问题："目前 B9 与我相关页的内容...尚未传出这个关键
信息与氛围"——本模块就是用来接住这个问题的。

## 设计取舍

1. **只用 S/A 档事件计入情绪**（MOOD_TIERS），且用 event_tier 而不是
   importance_score 做筛选门槛——这是 2026-07-28 上线当天就发现并改掉的一个真实
   错误：最初用 `importance_score >= 0.35` 当门槛，实测发现 48 小时窗口里有
   782 条 D 档事件（LLM 判定"次要"）的 importance_score 均值高达 0.317，部分
   个体轻松超过 0.35——因为 importance_score 是五因子加权总分，M（影响面）虽然
   被夹在 D 档区间（0-0.14），但 T（时效）/H（热度）/A（权威）/Q（质量）四个
   因子不受 tier 约束，单独拉高照样能把总分推过 0.35。结果是"重要性分蒙混过关
   的次要事件"占了情绪样本的大多数（460 条里的绝大部分），把两条真正的 S 档
   崩盘事件稀释成了统计噪音（KOSPI/日经暴跌当天算出的 mood_score 只有 -0.009，
   被前端渲染成"中性"，用户直接质疑"这样大跌还是中性？"）。
   改用 event_tier IN ('S','A') 做门槛后，同一天的样本从 460 条收窄到 18 条，
   mood_score 变成 -0.154（偏悲观）——这才是"大盘情绪"这个概念该问的问题：
   "最近发生的大事整体是什么方向"，不是"所有沾边的内容加权平均是什么方向"。
   importance_score 仍然用作样本内部的权重（越重要的 S/A 档事件影响力越大），
   只是不再兼任"够不够格参与计算"的门槛——这两件事必须分开，门槛要看 LLM 对
   事件本身重要性的判断（tier），不能看会被时效/热度污染的复合分。

2. **不碰 crawler/scoring.py 的基础因子公式**。两个加分项（同向 / 反转）只在 API
   查询/展示时作为外层倍率应用于排序，绝不写回 news_events.importance_score——
   那个字段是策略实验室、去重、历史分析全部依赖的口径，一旦被"今天的情绪"污染，
   昨天算出的分和今天算出的分就不可比了。加分项合计封顶 +50%，可随时把系数调 0
   退回纯基础排序（这也是验证它们真实贡献的 A/B 对照方式）。

3. **加成有方向性但不是单向放大**：只有当某条事件的情绪方向与大盘一致时才加成，
   反向或大盘接近中性时不加成也不减成——这样"大悲观时段"里少数逆势乐观的消息不会被
   排序打压到看不见，用户仍然能看到"情况没有那么糟"的信号，只是不会被推到最前面。

4. **样本权重叠加市场重要性与新鲜度**（2026-07-30 补）。上线时权重只用
   `importance_score`，结果实测情绪横幅的三条"驱动因素"清一色是韩股
   （韩国KOSPI跌7% / KOSDAQ熔断 / 韩股暴跌后外资观望），而首屏排序在 PRD-04
   之后已经是美股为主——**同一个产品的两块界面在讲互相矛盾的故事**。

   根因和 PRD-04 是同一个：门槛用的 `event_tier` 由 LLM 相对"事件自己所在市场"
   判定，小市场的 S/A 档率被系统性抬高（实测韩股 13.6% vs 美股 0.15%），
   于是韩股在 S/A 样本池里严重超配。PRD-04 在排序层用市场权重修正了这件事，
   但情绪层当时没跟着改。

   现在样本权重改为 `importance_score × 市场重要性 × 新鲜度`，与排序层用同一套
   倍率——"我们认为哪个市场更重要"和"多久以前的事还算数"这两个判断，不该在
   排序和情绪两处给出不同答案。门槛仍然是 tier（不变，理由见上面第 1 条）。
"""
import os

# 2026-07-30 从 48 小时收到 24 小时（Lawrence 要求）。
#
# 当初取 48 是因为主流水线每 2 天才跑 1 轮，24 小时窗口会在两轮之间"无数据
# 可用"，横幅显示空窗看起来像故障。**这个前提早已不成立**——2026-07-28 起
# pipeline 改成每小时 1 轮、头部媒体 30 分钟抓一次（见 crontab 与 WORKLOG
# #76），24 小时窗口里稳定有几百条事件，实测样本量完全够。
#
# 而 48 小时的代价是真实的："大盘情绪"本该回答"此刻市场什么氛围"，48 小时
# 会把前天的行情一起算进来——行情反转时（比如 7/28 美伊缓和油价跌、7/30 美军
# 打击伊朗油价涨）横幅会显示两种相反行情的平均值，等于什么都没说。
MOOD_LOOKBACK_HOURS = int(os.environ.get("B9_MOOD_LOOKBACK_H", "24"))

# 只统计 LLM 判定为 S/A 档的事件——用 tier 而不是 importance_score 做门槛，
# 理由见模块头部说明 1（复合分会被时效/热度/权威因子污染，tier 是 LLM 对事件
# 本身重要性的直接判断，不受这些因子干扰）。
MOOD_TIERS = ("S", "A")

# (下界（含）, 中文标签, 英文标签, 前端配色语义)
_MOOD_BUCKETS = [
    (0.50,  "极度乐观", "extreme_bullish", "green"),
    (0.15,  "偏乐观",   "bullish",         "green"),
    (-0.15, "中性",     "neutral",         "neutral"),
    (-0.50, "偏悲观",   "bearish",         "red"),
    (-1.01, "极度悲观", "extreme_bearish", "red"),
]



def mood_bucket(mood_score: float) -> tuple[str, str, str]:
    for lo, zh, en, color in _MOOD_BUCKETS:
        if mood_score >= lo:
            return zh, en, color
    return "中性", "neutral", "neutral"


def compute_market_mood(events: list[dict]) -> dict:
    """events：近 MOOD_LOOKBACK_HOURS 小时内的事件字典列表，每条至少含
    sentiment_score / importance_score / event_tier，展示用的话再带上
    id/title_zh/market_scope。

    返回的 mood_score 是 S/A 档事件按 importance_score 加权的平均情绪，范围 [-1, 1]。
    """
    scored = [e for e in events
             if e.get("sentiment_score") is not None
             and e.get("event_tier") in MOOD_TIERS]
    if not scored:
        return {
            "available": False,
            "reason": f"近 {MOOD_LOOKBACK_HOURS} 小时内没有 {'/'.join(MOOD_TIERS)} 档事件参与计算",
            "sample_size": 0,
        }

    # 样本权重 = 重要性 × 市场重要性 × 新鲜度（见模块说明 4）。延迟 import：
    # market_weight/freshness 都不反向依赖本模块，但放在函数内可以避免
    # crawler 包 import 期的循环依赖风险。
    from . import freshness, market_weight
    for e in scored:
        e["_mood_weight"] = (float(e["importance_score"])
                             * market_weight.market_multiplier(e)
                             * freshness.decay_multiplier(e))

    total_weight = sum(e["_mood_weight"] for e in scored)
    if total_weight <= 0:      # 全被衰减到地板且重要性为 0 的极端情况
        return {
            "available": False,
            "reason": "近期 S/A 档事件的加权总权重为 0",
            "sample_size": len(scored),
        }
    mood_score = sum(e["sentiment_score"] * e["_mood_weight"] for e in scored) / total_weight
    mood_score = max(-1.0, min(1.0, mood_score))
    zh, en, color = mood_bucket(mood_score)

    # 贡献最大的几条：跟大盘同向、且 |情绪|×权重 最高的——这些是"解释这个情绪
    # 判断从哪来"的证据链，前端横幅直接引用，用户能一眼验证这个判断是否合理。
    # 用与 mood_score 同一套权重排序，否则会出现"横幅说偏悲观、但列出的理由
    # 并不是真正把它拉悲观的那几条"这种自相矛盾。
    same_dir = [e for e in scored if (e["sentiment_score"] >= 0) == (mood_score >= 0)]
    top = sorted(same_dir, key=lambda e: abs(e["sentiment_score"]) * e["_mood_weight"],
                reverse=True)[:3]

    return {
        "available": True,
        "mood_score": round(mood_score, 3),
        "label_zh": zh, "label_en": en, "color": color,
        "sample_size": len(scored),
        "lookback_hours": MOOD_LOOKBACK_HOURS,
        "tiers": list(MOOD_TIERS),
        "top_events": [
            {"id": e.get("id"), "title_zh": e.get("title_zh"),
             "sentiment_score": e.get("sentiment_score"),
             "market_scope": e.get("market_scope")}
            for e in top
        ],
    }


# ── 两个加分项（2026-07-29 拆分，PRD-03 R4/R5）───────────────────────
#
# 原本只有一个"同向加成"。Lawrence 采纳了回音室风险的分析后要求拆成两个
# 独立因子，各自可在策略实验室调：
#
#   · 同向 boost：大盘悲观时放大负面、乐观时放大正面 —— 制造氛围感
#   · 反转 boost：大盘悲观时**反而**把重大利好顶上来 —— 防回音室
#
# 为什么必须有第二个：单独的同向放大会让"大盘暴跌 → 首屏全是坏消息"，
# 而此时一条"美联储可能提前降息"的反转信号恰恰被压到看不见。金融产品里
# 放大情绪＝放大追涨杀跌，真正伤害用户的不是内容平，是该看到反转时看不到。
#
# 反转 boost 的 **tier ∈ S/A 硬约束**是它成立的前提（Lawrence 确认"加的对"）：
# 没有这个约束，大盘悲观时所有反向的噪音都会被扶上来，反而更乱。只有
# "重大且与大盘反向"才是真信号。
MOOD_ALIGN_BOOST = 0.25      # k_s：同向加成上限，原 0.15，本期按需求调高
MOOD_REVERSAL_BOOST = 0.20   # k_r：反转加成上限
REVERSAL_TIERS = ("S", "A")  # 反转加成只对重大事件生效
BONUS_TOTAL_CAP = 0.50       # 两项合计封顶 +50%，防止加分项盖过基础排序


def sentiment_align_bonus(event_sentiment_score, mood_score, k=None) -> float:
    """情绪同向加分。返回 0~k 的**加数**（不是倍率），反向或数据缺失返回 0。"""
    k = MOOD_ALIGN_BOOST if k is None else k
    if event_sentiment_score is None or mood_score is None:
        return 0.0
    if (event_sentiment_score >= 0) != (mood_score >= 0):
        return 0.0
    return k * abs(mood_score) * abs(event_sentiment_score)


def reversal_bonus(event_sentiment_score, mood_score, event_tier, k=None) -> float:
    """反转信号加分。只在「方向与大盘相反」**且**「事件为 S/A 档」时生效。"""
    k = MOOD_REVERSAL_BOOST if k is None else k
    if event_sentiment_score is None or mood_score is None:
        return 0.0
    if (event_sentiment_score >= 0) == (mood_score >= 0):
        return 0.0          # 同向 → 交给 sentiment_align_bonus，两者互斥
    if event_tier not in REVERSAL_TIERS:
        return 0.0          # 低档位的反向噪音不该被扶上来
    return k * abs(mood_score) * abs(event_sentiment_score)


# 交易实体加成（ADR-002 块 B）。老板要的是"刺激标的物交易"的感觉——
# 一条能落到具体可买标的的新闻，比一条纯宏观评论更容易引发交易动作。
#
# **分档而不是一刀切**是关键：实测 Benzinga 的"盘前综述"一条挂 7 个 ticker
# （DJI,IXIC,SPX,SPY,QQQ,IWM,MSFT），那恰恰是最没有交易指向性的内容；真正
# 刺激交易的是"NVDA 财报炸了"这种单一主标的事件。不分档会把泛泛的大盘综述
# 系统性顶上去，与需求意图正好相反。
TRADABLE_BONUS_FOCUSED = 0.06     # 1-2 个可交易标的：指向明确
TRADABLE_BONUS_BROAD = 0.02       # ≥5 个：宽泛市场评论，给一点但不多
TRADABLE_BROAD_THRESHOLD = 5


def tradable_bonus(event: dict, k_focused=None, k_broad=None) -> float:
    """有可交易标的的加成。没有标的物 → 0，不惩罚，只是不加分。"""
    n = event.get("tradable_count")
    if n is None:
        # 兼容还没跑过 persist_tradable_entities 的存量行：现场从 JSON 数
        from . import tradable as _t
        n = _t.tradable_count(event.get("tradable_entities"))
    n = int(n or 0)
    if n <= 0:
        return 0.0
    kf = TRADABLE_BONUS_FOCUSED if k_focused is None else k_focused
    kb = TRADABLE_BONUS_BROAD if k_broad is None else k_broad
    return kb if n >= TRADABLE_BROAD_THRESHOLD else kf


def mood_multiplier(event: dict, mood_score, k_align=None, k_reversal=None,
                    k_tradable=None, k_tradable_broad=None, cap=None) -> dict:
    """算出某条事件的展示层倍率。返回明细，便于策略实验室展示"为什么是这个分"。

    只应用于查询/展示时的排序，绝不写回 importance_score——见模块头部说明 2。
    """
    s = event.get("sentiment_score")
    align = sentiment_align_bonus(s, mood_score, k_align)
    rev = reversal_bonus(s, mood_score, event.get("event_tier"), k_reversal)
    trad = tradable_bonus(event, k_tradable, k_tradable_broad)
    # 三个加分项共用同一个封顶：新增加分项必须纳入既有 cap，否则叠加起来
    # 会突破策略配置里声明的上限，让"封顶"这个概念失效。
    total = min(align + rev + trad, BONUS_TOTAL_CAP if cap is None else cap)
    return {
        "sentiment_align": round(align, 4),
        "reversal": round(rev, 4),
        "tradable": round(trad, 4),
        "total_bonus": round(total, 4),
        "multiplier": round(1.0 + total, 4),
    }


def mood_alignment_multiplier(event_sentiment_score, mood_score) -> float:
    """[保留兼容] 旧的单一同向倍率。新代码请用 mood_multiplier()。"""
    return 1.0 + sentiment_align_bonus(event_sentiment_score, mood_score)
