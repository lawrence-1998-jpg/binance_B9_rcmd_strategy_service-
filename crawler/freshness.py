"""查询时新鲜度衰减 —— crawler/freshness.py（2026-07-30）

## 起因：一条人眼一看就知道错的首屏结果

2026-07-30 中午实测首屏，第 11 位是「美伊缓和致油价跌16%」（7/28），第 13 位是
「布伦特原油日内暴跌7.71%，跌破86美元/桶」（7/27）。而**当天的真实新闻**是
「美军称已完成对伊朗大规模打击」「埃及附近油船起火 油价涨8%」——局势升级、
油价上涨。两条 2-3 天前、且已被事态反转的旧叙事，压在当天真实事件前面。

## 根因：`score_timeliness` 是入库时算一次就冻住的存量字段

`crawler/scoring.py:compute_timeliness` 按 24h 半衰期做指数衰减，公式本身没问题，
但它算完就写进 `news_events.score_timeliness`，并且加权进 `importance_score`
一起落库，**此后再也不重算**。而每条内容都是"抓到当时还很新"，所以实测：

    事件                          入库日期    存量 T
    布伦特原油暴跌（3天前）        7/27       0.973
    美伊缓和油价跌16%（2天前）     7/28       0.960
    美军完成对伊朗打击（当天）      7/30       0.980

3 天前的内容 T=0.973，当天的 T=0.980——**时效因子在排序里几乎不产生任何区分度**。
于是排序完全由 I（影响力）/H（热度）决定，而旧事件恰恰在这两项上占便宜：它多
出 2-3 天时间通过跨轮归并累积信源（H 的一半就是独立信源数），越老信源越多、
分越高。系统结构性地偏向旧闻。

## 为什么做成查询时倍率，而不是定期重算存量

和 `crawler/market_weight.py`、`crawler/market_mood.py` 同一个理由，而且这里更
本质：**"这条新闻有多新"根本不是事件的固有属性，是"你什么时候看它"的函数**。
写进库里就必然过时，靠 cron 定期重算只是把过时的粒度从"永远"缩小到"一个周期"，
且每次重算都要全库写一遍。放在查询时算，任何时刻取出来都是当下正确的值。

存量 `score_timeliness` 字段保留不动：它记录的是"我们抓到它时它有多新"，对排查
抓取延迟仍然有用，只是不该再承担排序里的时效职责。

## 半衰期为什么取 48h 而不是沿用 24h

24h 半衰期下，2 天前的内容只剩 0.25 倍——对"昨天的大事今天还在发酵"这种常见
情况过于粗暴，会把仍在持续影响市场的重大事件直接打没。48h 下：

    0h→1.00   12h→0.84   24h→0.71   48h→0.50   72h→0.35   120h(5天窗口边界)→0.18

当天内容基本不打折，昨天的打七折（够重要仍能留在前排），2-3 天前的显著沉底但
不归零——配合 `crawler/source_trust.py` 的 5 天展示窗口，衰减曲线正好覆盖整个
可见区间。
"""
import math
import os
from datetime import datetime, timezone

from .dedup import parse_dt
from .timeutil import PROJECT_TZ, now_local

HALFLIFE_HOURS = float(os.environ.get("B9_FRESHNESS_HALFLIFE_H", "48"))

# 衰减下限：再老的内容也不归零。归零等于"从排序里删除"，那是展示窗口
# （source_trust.MAX_AGE_DAYS）该做的决定，不该由衰减曲线偷偷代劳。
MIN_MULTIPLIER = float(os.environ.get("B9_FRESHNESS_FLOOR", "0.15"))

# 应急开关：万一衰减把排序打乱得不符预期，不改代码就能退回"不衰减"。
ENABLED = os.environ.get("B9_FRESHNESS_ENABLED", "true").strip().lower() != "false"


def _event_time(event: dict) -> datetime | None:
    """取事件的真实发生时间。

    优先 `time_event`（LLM 从正文读出的事件真实时间，经 filter_by_event_date
    校验过），回落到 `date`。不用 `time_get_data`——那是"我们什么时候抓到的"，
    一条三天前的旧闻今天被抓到也会显示成刚刚，正是要避免的那类错误。

    ⚠️ 时区：这两列是 MySQL DATETIME，按 `timeutil.local_str` 的约定**存的是
    UTC+8 裸时间**。而 `dedup.parse_dt` 对无时区的输入默认按 UTC 解释（它本来
    是给信源 ISO 字符串用的，那个场景下 UTC 兜底是对的）。直接套用会凭空多算
    8 小时——实测表现为 hours_ago 变成负数（事件"发生在未来"）、衰减倍率被钉
    在 1.0，时效因子再次失效。所以这里显式按 PROJECT_TZ 补时区，不去改全局的
    parse_dt（那会影响 dedup 的时间窗判定，是另一个量级的改动）。
    """
    for key in ("time_event", "date"):
        dt = parse_dt(event.get(key))
        if dt is None:
            continue
        # parse_dt 给无时区输入贴的是 UTC，对 DB 裸时间来说是错的——换成 UTC+8
        if dt.tzinfo == timezone.utc and not str(event.get(key) or "").endswith(("Z", "+00:00")):
            dt = dt.replace(tzinfo=PROJECT_TZ)
        return dt
    return None


def decay_multiplier(event: dict, now: datetime | None = None) -> float:
    """返回这条事件在"此刻"的新鲜度倍率。时间解析不出来时返回 1.0（不打折）
    ——解析失败是我们的数据问题，不该让内容替我们背锅沉底。"""
    if not ENABLED:
        return 1.0
    published = _event_time(event)
    if published is None:
        return 1.0
    now = now or now_local()
    hours_ago = (now - published).total_seconds() / 3600
    if hours_ago <= 0:      # 时间戳在未来（源站时区标错等），按最新处理
        return 1.0
    decayed = math.exp(-hours_ago * math.log(2) / HALFLIFE_HOURS)
    return max(MIN_MULTIPLIER, min(1.0, decayed))


def explain(event: dict, now: datetime | None = None) -> dict:
    """返回明细，供前端/实验室展示"为什么是这个分"。"""
    published = _event_time(event)
    now = now or now_local()
    hours = None if published is None else round((now - published).total_seconds() / 3600, 1)
    return {
        "hours_ago": hours,
        "halflife_hours": HALFLIFE_HOURS,
        "multiplier": round(decay_multiplier(event, now), 4),
    }
