# Skill 01 · 市场重要性倍率（market_weight）

> **一句话**：事件分档是「相对自己所在市场」判的，但排序是全局的——所以需要在市场这一层引入一个全局相关性倍率。

---

## 1. 你要解决的问题

| market_scope | 供给量 | S 档数 | S 档率 | Top30 占位 |
|---|---|---|---|---|
| us_stock | 658 | 1 | **0.15%** | 3 |
| kr_stock | 44 | 6 | **13.6%** | **6** |
| jp_stock | 51 | 1 | 2.0% | 1 |
| crypto | 948 | 2 | 0.2% | 4 |

韩股的 S 档率是美股的 **90 倍**；供给只有美股的 1/15，却占了 2 倍的 Top30 席位。

**根因在理解阶段的 prompt**：那句 `significance to ITS OWN market is the criterion`。
它当初是为了解决"非加密新闻被无差别打低分埋掉"——那个问题确实解决了，但**过度纠正**：
tier 变成相对「自己所在市场」判定的，而排序是全局的。
于是「韩国财长为一只杠杆 ETF 致歉」（对韩国是大事）能压过「影响全球风险偏好的美股常规新闻」（对美股是常规）。

## 2. 为什么不能靠"更聪明的因子"解决

实测两条 `kr_stock` / S 档事件：

| | 韩财长就 ETF 致歉 | KOSPI 跌超 8% 触发熔断 |
|---|---|---|
| market_scope | kr_stock | kr_stock |
| event_tier | S | S |
| breadth_level | market_index | market_index |
| 冲击力 I | 1.00 | 1.00 |
| 幅度 | 17%（正文提到大盘数字） | 11.89% |

**在所有既有因子上完全无法区分。** 市场内部找判据是死路，只能在「市场」这一层引入全局权重。

---

## 3. 上游：`market_scope` 的判定

这个字段由内容理解阶段的 LLM 产出。以下是可直接使用的 prompt 片段。

### 3.1 market_scope

```
## MARKET SCOPE (for `market_scope`) — which market does this story belong to?

Pick exactly ONE. This drives a global relevance multiplier in ranking, so pick the
market whose participants this story is ABOUT, not the market where it was published.

  us_stock       U.S. equities: single names, indices, earnings, Fed-driven equity moves
  crypto         Digital assets: tokens, exchanges, DeFi, on-chain, crypto ETFs
  macro_policy   Cross-border macro: central banks, rates, inflation prints, trade policy,
                 sovereign debt, commodities as a macro signal
  social_signal  Geopolitical conflict, natural disaster, social events — anything with a
                 plausible TRANSMISSION PATH to markets but no direct instrument
  hk_stock       Hong Kong equities
  jp_stock       Japanese equities
  kr_stock       Korean equities
  general        Genuinely does not fit the above. Use sparingly — `general` is discounted.

If a story spans two markets, pick the one it is PRIMARILY about, and let `breadth_level`
carry the spillover (see below). "Oil spike drags KOSPI down 7%" is kr_stock with
breadth_level = cross_market, NOT macro_policy.
```

> ⚠️ `social_signal` 的边界（老板确认）：**只收对市场有传导路径的**。
> 纯社会新闻（明星八卦、地方案件）不属于这一档，应落 `general` 或在前置过滤中丢弃。

### 3.2 breadth_level（判定规则见 skill-02）

跨市场豁免用的就是这个字段，但它的完整判定 prompt 与分值映射放在
[`skill-02-广度因子.md`](skill-02-广度因子.md)——**同一份规则不要在两处各写一遍**。
本项目已经因为"两处手写名单"咬过两次：改了一处、另一处静默漂移，而且不报错。

这里只需要记住一件事：`breadth_level == "cross_market"` 时市场倍率不打折（下限 1.00）。

---

## 4. 倍率表与豁免逻辑

```python
DEFAULT_MARKET_WEIGHTS = {
    "us_stock":      1.20,   # 全球用户真正关注的市场
    "crypto":        1.00,   # 主场业务，基准
    "macro_policy":  1.00,   # 跨国宏观，天然全球相关
    "social_signal": 0.85,   # 有市场传导路径但间接
    "general":       0.70,   # 归类不明确
    "hk_stock":      0.65,
    "jp_stock":      0.60,
    "kr_stock":      0.55,
}
DEFAULT_WEIGHT     = 0.70    # 未知/缺失 scope 的兜底：不认识的东西不该享受高权重，
                             # 但也不该被打到地板（可能只是新增分类还没进表）
MIN_WEIGHT, MAX_WEIGHT = 0.0, 2.0
CROSS_MARKET_FLOOR = 1.0
ENABLED = env("B9_MARKET_WEIGHT_ENABLED") != "false"   # 应急开关

def market_multiplier(event, weights=None):
    if not ENABLED:
        return 1.0
    weights = weights or DEFAULT_MARKET_WEIGHTS
    base = weights.get(event.get("market_scope"), DEFAULT_WEIGHT)
    if event.get("breadth_level") == "cross_market":
        return max(base, CROSS_MARKET_FLOOR)      # ← 必须是 max，不是赋值
    return base
```

**豁免的产品含义**（老板原话直接编码）：
> 「日韩是在剧烈波动和大事件（比如芯片暴跌，且这个也会比较大影响美国市场的）的时候，才会是大部分用户关心的新闻」

- 「油价飙升拖累韩国 KOSPI 跌 7%」→ `cross_market` → **不打折**
- 「韩财长就单一个股杠杆 ETF 致歉」→ `market_index` → ×0.55

---

## 5. 三个容易做错的地方

| 坑 | 后果 | 正确做法 |
|---|---|---|
| 豁免写成 `return CROSS_MARKET_FLOOR` | 美股的 1.20 会因为这条恰好跨市场被**压回** 1.00 | 用 `max(base, floor)`，豁免只做**下限保护** |
| 倍率写回 `importance_score` | "我们更关心哪个市场"是运营偏好，写进去就污染了"事件本身多重要"这个口径；且改一次权重要全库重算，实验室也没法实时调 | **只在查询时相乘** |
| 未知 scope 兜底给 1.0 或 0.0 | 给 1.0 = 新增分类白捡高权重；给 0.0 = 静默从排序中消失 | 兜底 0.70（= general 档） |

---

## 6. 验收断言

- [ ] `market_multiplier({"market_scope":"us_stock","breadth_level":"cross_market"}) == 1.20`（不是 1.00）
- [ ] `market_multiplier({"market_scope":"kr_stock","breadth_level":"cross_market"}) == 1.00`
- [ ] `market_multiplier({"market_scope":"kr_stock","breadth_level":"market_index"}) == 0.55`
- [ ] `market_multiplier({"market_scope":"不存在的分类"}) == 0.70`
- [ ] `B9_MARKET_WEIGHT_ENABLED=false` 时所有事件倍率 = 1.0，排序退回改造前
- [ ] 上线后 Top30 按 market_scope 分组，**韩股+日股占位数与各自供给量占比相称**（改造前是 2 倍超配）
- [ ] `explain()` 返回 `{market_scope, base_weight, cross_market_exempt, multiplier}`，实验室能展示"为什么这条被折价 / 为什么它没被折价"
