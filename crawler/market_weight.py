"""市场重要性权重 —— crawler/market_weight.py（2026-07-29，PRD-04）

## 为什么需要这个模块

Lawrence 反馈「韩国的都排在了上面。其实我们美股才是最重要的」。查证下来这不是
权重没调好，是**分档口径本身有系统性偏差**——实测近 2 天：

    市场        供给量   S档数   S档率     Top30占位
    us_stock     658      1     0.15%        3
    kr_stock      44      6    13.6%         6      ← 供给只有 1/15，占位却是 2 倍
    jp_stock      51      1     2.0%         1
    crypto       948      2     0.2%         4

韩股的 S 档率是美股的 **90 倍**。

根因在 `crawler/pipeline.py` 的 SYSTEM_PROMPT 里那句
「significance to ITS OWN market is the criterion」——它当初是为了解决"非加密
新闻被无差别打低分埋掉"，那个问题确实解决了，但**过度纠正**：tier 变成相对
「自己所在市场」判定的，而排序是全局的。于是「韩国财长为一只杠杆 ETF 致歉」
（对韩国是大事）能压过「影响全球风险偏好的美股常规新闻」（对美股是常规）。

## 为什么不能靠"更聪明的因子"解决

实测对比两条 kr_stock / S 档事件：

                        韩财长就ETF致歉   KOSPI跌超8%触发熔断
    market_scope           kr_stock          kr_stock
    event_tier                S                 S
    breadth_level        market_index      market_index
    冲击力 I                 1.00              1.00
    幅度                    17%（正文提到大盘数字）  11.89%

**在所有既有因子上完全无法区分**。所以只能在「市场」这一层引入全局相关性权重，
在市场内部找判据是死路。

## 为什么是查询时倍率，而不是写进 importance_score

和两个情绪加分项同样的理由（见 crawler/market_mood.py 的说明 2）：
`importance_score` 是「事件本身有多重要」的口径，掺进「我们产品更关心哪个市场」
这种**运营偏好**就污染了；而且写库意味着改一次权重要全库重算，实验室里也就
没法实时调。放在查询时相乘，改了立刻生效、随时可退回 1.0 做 A/B 对照。

最终分的完整形态：

    FinalScore = BaseScore × MarketWeight × (1 + 同向加成 + 反转加成)
"""
import os

# 各 market_scope 的全局相关性倍率。默认值的依据见 docs/prd/PRD-04。
# us_stock 显式提到 1.20 而不是留在 1.0：Lawrence 要的是"大大提高"，让它在
# 界面上也看得出是被主动提权的，而不是"别人降了所以它相对高了"。
DEFAULT_MARKET_WEIGHTS = {
    "us_stock":      1.20,   # 全球用户真正关注的市场
    "crypto":        1.00,   # 主场业务，基准
    "macro_policy":  1.00,   # 跨国宏观，天然全球相关
    "social_signal": 0.85,   # 有市场传导路径但间接
    "general":       0.70,   # 归类不明确
    "hk_stock":      0.65,
    "jp_stock":      0.60,
    "kr_stock":      0.55,   # 当前问题最集中
}

# 未知/缺失 market_scope 的兜底。取 general 同档——不认识的东西不该享受高权重，
# 但也不该被当成噪音打到地板（它可能只是新增的分类还没加进表里）。
DEFAULT_WEIGHT = 0.70

# 权重可调范围。上限 2.0 给运营留出"某个市场临时置顶"的空间。
MIN_WEIGHT, MAX_WEIGHT = 0.0, 2.0

# 跨市场豁免的下限。命中豁免时权重不低于这个值（即不打折）。
CROSS_MARKET_FLOOR = 1.0

# 允许用环境变量整体关掉这一层（应急开关：万一权重配错导致线上排序异常，
# 不用改代码就能退回"所有市场一视同仁"）。
ENABLED = os.environ.get("B9_MARKET_WEIGHT_ENABLED", "true").strip().lower() != "false"


def resolve_weights(raw: dict | None = None) -> dict:
    """把外部传入的权重（实验室滑杆 / API 参数）归一成完整的权重表。

    缺失的键用默认值补齐、非法值忽略——调用方只传想改的那几个市场即可，
    不用每次都传全量 8 个。
    """
    weights = dict(DEFAULT_MARKET_WEIGHTS)
    for key, value in (raw or {}).items():
        if key not in DEFAULT_MARKET_WEIGHTS:
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        weights[key] = max(MIN_WEIGHT, min(MAX_WEIGHT, v))
    return weights


def market_multiplier(event: dict, weights: dict | None = None) -> float:
    """返回某条事件的市场重要性倍率。

    **cross_market 豁免**是这个函数的核心逻辑，也是 Lawrence 那句
    「日韩是在剧烈波动和大事件（比如芯片暴跌，且这个是也会比较大影响美国
    市场的）的时候才会是大部分用户关心的新闻」的直接编码：

      · 「油价飙升拖累韩国 KOSPI 跌 7%」→ breadth=cross_market → **不打折**
      · 「韩财长就单一个股杠杆 ETF 致歉」→ breadth=market_index → 打 0.55

    用现成的 breadth_level 而不是新增字段：「已经外溢到多个市场」正是
    cross_market 这一档的定义，语义完全吻合，不需要让 LLM 多判一次。

    豁免只做**下限保护**（max 而不是直接赋值）：us_stock 的 1.20 不会因为
    这条新闻恰好是跨市场就被压回 1.0。
    """
    if not ENABLED:
        return 1.0
    weights = weights if weights is not None else DEFAULT_MARKET_WEIGHTS
    base = weights.get(event.get("market_scope"), DEFAULT_WEIGHT)
    if event.get("breadth_level") == "cross_market":
        return max(base, CROSS_MARKET_FLOOR)
    return base


def explain(event: dict, weights: dict | None = None) -> dict:
    """返回倍率明细，供策略实验室展示「为什么是这个分」。"""
    weights = weights if weights is not None else DEFAULT_MARKET_WEIGHTS
    scope = event.get("market_scope")
    base = weights.get(scope, DEFAULT_WEIGHT)
    exempt = event.get("breadth_level") == "cross_market" and base < CROSS_MARKET_FLOOR
    return {
        "market_scope": scope,
        "base_weight": round(base, 4),
        "cross_market_exempt": exempt,
        "multiplier": round(market_multiplier(event, weights), 4),
    }
