# Skill 03 · 冲击力因子（punch / I）

> **一句话**：判断"标题里这个百分数是不是价格涨跌幅"是**语义问题，不是模式匹配问题**——
> 该让已经在读全文的 LLM 出一个结构化字段，规则只留作存量兜底。

> 🔴 **这是本轮最重要的一块。** 冲击力占权重 14%，而改造前**它一半以上的幅度信号是错的**。

---

## 1. 因子定义（第一版没定义清，这里重新定义）

老板的原始描述包含三个成分，逐一对照现有因子后**只保留两个**：

| 成分 | 处置 | 理由 |
|---|---|---|
| 数值幅度（跌 18% / 涨 600 点） | ✅ **真新增，是本因子核心** | 现有因子完全没捕获 |
| 多家权威媒体报道 | ⚠️ **部分覆盖，用"权威共振"子项补强** | 热度里有"信源数/8"但被社交互动稀释；权威只看单一最高值 |
| 对社会经济重大影响 | ❌ **刻意不做** | 已被 影响面 + 广度 覆盖两遍，再单列就是**三重计分** |

```
I = 0.65 × 幅度分 + 0.35 × 权威共振分
```

全部纯计算，**0 次额外 LLM 调用**（`price_move` 是在既有理解请求里顺带多输出一个字段）。

### 1.1 幅度分档

| 条件 | 分 |
|---|---|
| 命中极端词（熔断/崩盘/暴跌/暴涨/涨停/跌停/闪崩/归零 · circuit breaker/crash/plunge/collapse/rout） | **1.00**（不看百分比——它们的语义本身就是极端） |
| pct ≥ 15% | 1.00 |
| pct ≥ 8% | 0.75 |
| pct ≥ 4% | 0.55 |
| pct ≥ 2% | 0.35 |
| 其余 / 无幅度 | 0.10 |

### 1.2 权威共振分档

**只数机构媒体 / 通讯社 / 一手 API。社交（social）、网页搜索、行情信号、日历一律不计。**

| 条件 | 分 |
|---|---|
| ≥ 3 家 authority ≥ 4 的独立机构 | 1.00 |
| = 2 家 | 0.65 |
| 有 1 家 authority ≥ 5 | 0.45 |
| 其余 | 0.15 |

> ⚠️ 排除社交源是老板裁决的。此前一个 5 分的 X KOL（cz_binance）和 CNBC 在这里**完全等价**。
> **个人影响力 ≠ 机构编辑权威**：转推一条消息的 KOL 再多，也不构成"多家独立编辑室分别核实过"这个信号。

---

## 2. 我们踩了什么坑（读完再动手，能省你四轮）

改造前的做法是：**默认标题里的百分数就是涨跌幅，除非它附近命中排除词**。
排除词表连补四轮，每轮都在漏：

| 轮次 | 补的词 | 触发案例 | 后果 |
|---|---|---|---|
| v1 | 关税/税率/征税/利率/占比/概率/收益率 | 「征收 **100%** 二级关税」 | 被读成 100% 暴涨，冲击力顶满，排到首屏 **#5** |
| v2 | 同比/环比/购金/增持/持仓/净流入 | 「央行二季度购金增 **62%**（同比）」 | 单源快讯冲到首屏 **#4** |
| v3 | 税（裸字）/覆盖/超预期/目标价/收窄 | 「关税重启覆盖 **99%** 进口」「EPS 超预期 **30.67%**」「目标价上调 **5.1%**」 | 抽样 5 条误读 5 条 |
| v4 | 口径反转成 opt-in（数字附近**必须**有价格变动指示词） | —— | 仍然漏「Upbit 份额**升至** 67.4%」「比特币市占率**升破** 58%」 |

### 2.1 为什么规则必然输

1. **"百分比能表示什么"是无穷集合**——支持率、市占率、覆盖率、税率、收益率、波动率、整合率、持有率、市值占 GDP 比、门票处理量、协议投票阈值……排除表永远追不完。反过来做 opt-in 也只解决一半。
2. **涨跌动词不是判据。**「份额**升**至」「支持率**降**至」「渗透率**涨**到」——升降涨跌可以修饰**任何**指标。要问的是这个数字**度量什么**，那是语义不是模式。
3. **每加一个词都要重新验证不误伤真实案例。**（加 `share` 会撞 "Tesla shares surge 12%"；加 `target` 会撞 Target Corp。）维护成本随词表长度**超线性**增长。
4. **双语系统里每条规则要写两遍，漏一边等于没写。** 我们中文补完英文没补，首屏那两条照样没修好——`dominance` / `share rises` 从英文标题绕了过去。

> **信号**：当你发现"第三轮还在补词表"时就该停下来问：这是模式匹配问题还是语义问题？
> 语义问题就加 LLM 字段，别再补第四轮。

---

## 3. 正确做法：让 LLM 出一个结构化字段

在**已经在读全文**的理解请求里，多输出一个字段。零额外调用。

### 3.1 JSON Schema

```json
"price_move": {
  "type": "object",
  "properties": {
    "is_price_move": {"type": "boolean"},
    "move_pct":      {"type": ["number", "null"]},
    "move_horizon":  {"type": "string",
                      "enum": ["intraday", "multi_day", "long_term", "none"]}
  },
  "required": ["is_price_move", "move_pct", "move_horizon"],
  "additionalProperties": false
}
```

**字段设计三原则**（可复用到其它语义字段）：

1. **布尔判断单独拆出来** —— 便于 QA 断言与人工抽查
2. **量值只在布尔为真时有意义** —— 显式允许 null，不要用 0 表示"没有"
3. **能区分"周期/尺度"的话一并要** —— 日内暴跌 vs 年内累计涨幅是两回事

### 3.2 完整 prompt（可直接抄，这一段是逐字实测过的）

```
## PRICE MOVE (for `price_move`) — is a number in this story an actual PRICE change?

This exists because percentages in financial text mean many different things, and only ONE of
them belongs in an impact score. Ask: **did the market price of a tradable asset actually move
by this much?**

`is_price_move: true` ONLY when the number is how much an asset's PRICE (or an index level)
actually moved:
  "Bitcoin fell 8%" · "Nikkei -4.2%" · "AVAX up 8.24% in 24h" · "ASTEROID down 52% in 20 min"
  "Tesla shares surge 12%" · "gold hits record, +3% today"

`is_price_move: false` for EVERYTHING else, even though a move verb is often right next to it:
  · market share / dominance   "Upbit share RISES to 67.4%", "Bitcoin dominance RISES above 58%"
  · ratios and rates           tax rate 20%, interest rate, approval rating 33%, volatility 60%,
                               AI adoption rate 75%, staking ratio, unemployment rate
  · coverage / proportion      "tariffs COVER 99% of imports", "72% of institutional volume"
  · earnings vs expectations   "EPS BEAT estimates by 30.67%", "revenue 10.95% above forecast"
  · analyst targets            "price target RAISED 5.1%" (the target moved, not the price)
  · statistics and history     "August's best month, +65% in 2017", "median return", seasonality
  · flows and quantities       "$18B of oil sold", "central banks bought 62% more gold",
                               "TVL fell 38% over six months" (that's a half-year aggregate)
  · protocol / governance      "BIP-110 signalling at 100%", "97% of nodes upgraded"

The trap to avoid: **a rise/fall verb next to a number does NOT make it a price move.**
Market share rises, approval ratings fall, adoption rates climb — none of those are prices.
Ask what the number MEASURES, not what verb sits beside it.

`move_pct`: **how much the price CHANGED**, as a positive number (8.24 for both +8.24% and
-8.24%; direction lives in `sentiment`). Null when `is_price_move` is false.

Two traps on `move_pct` specifically:
  · A LEVEL is not a CHANGE. "30-year Treasury yield rose TO 5.26%" — 5.26 is where the yield
    now sits, not how far it moved; move_pct is null here. Same for "BTC dominance at 58%",
    "funding rate at 0.01%". Only "rose BY x%" gives you a move_pct.
  · If the story clearly describes a price move but never states its size ("TLT fell to a
    10-month low", "gold hit a record"), keep `is_price_move: true` but set `move_pct: null`.
    Never borrow an unrelated number from elsewhere in the text to fill it.

`move_horizon`: over what period did the price move?
  · intraday   — today / last 24h / "in 20 minutes" (this is what real impact looks like)
  · multi_day  — over a few days or this week
  · long_term  — year-to-date, since launch, over six months (narrative recap, NOT impact)
  · none       — when `is_price_move` is false

If several assets moved, report the one the headline is actually about (usually the largest).
```

> 🔴 **那句 "a rise/fall verb next to a number does NOT make it a price move" 必须写。**
> 第一版没写这句时，LLM 把"收益率**升至** 5.26%"这个**水平值**当成了变动幅度。

### 3.3 消费侧

```python
def compute_punch(event):
    pm = event.get("price_move")
    if isinstance(pm, str):
        pm = json.loads(pm)                       # 库里是 JSON 字符串
    if isinstance(pm, dict) and "is_price_move" in pm:
        if not pm.get("is_price_move"):
            pct = None
        else:
            pct = abs(float(pm["move_pct"])) if pm.get("move_pct") is not None else None
            if pct is not None and pm.get("move_horizon") == "long_term":
                pct = None                        # 年内累计不是冲击力
        return {"score": 0.65*_magnitude(pct, text) + 0.35*_resonance(event),
                "magnitude_pct": pct, "magnitude_source": "llm"}

    # ── 没有语义字段的存量数据走正则兜底（保留，不要删）──
    ...
```

> ⚠️ **兜底不能删。** 存量数据没有新字段，删了会让它们的冲击力**集体归零**——
> 那是一次**无声的全库降级**：分仍然是 [0,1] 的浮点数、仍然能排序、页面照常渲染、不报错不告警。
> 请加 QA 断言把"有字段用字段、无字段用兜底"两条路都钉住。

---

## 4. 实测结果

### 真实模型验证（走真实网关，不是假设它会做对）

拿踩过的坑当用例：

| 用例 | 期望 | 结果 |
|---|---|---|
| 市场份额 / 市占率 / 协议投票阈值 / 覆盖率 / 财报超预期 / 支持率 | false | ✅ 全对 |
| 收益率**升至** 5.26%（水平 ≠ 变动） | true 但 pct=null | ✅ |
| "TLT 跌至 10 个月低点"（有跌无幅度） | true 但 pct=null | ✅ |
| Tesla shares surge 12%（与 share 撞车） | true, 12 | ✅ |
| 日内暴跌 / 真跌带关税干扰词 / 指数暴跌 | true, 对应值 | ✅ |

**12/12。** 其中"收益率水平"与"有跌无幅度"两条是第一轮测出问题后补进 prompt 的。

### 存量回填

**LLM 判定 400 条抽样中 243 条原本被误判为涨跌幅 —— 60%**，与用规则独立估算的 54% 相互印证。
误判样例清一色是"目标价上调 / 评级 / 不及预期"这类。
全量回填 986 条后重算，648 条分数变化，**首屏换血 4/20**。

---

## 5. 落地时会遇到的三件事

| 事 | 说明 |
|---|---|
| **改 prompt 会让理解缓存整体失效** | 需要一次全量重跑。这个代价要如实预告，但**别把它当成不做正确事情的借口**——我们就是先入为主以为额度不稳定，拖了一轮才做 |
| **加列后必须做写入-读回往返验证** | 我们加列时占位符少写一个（41 个 `%s` 对 42 列），写库**全部失败但不抛异常**（异常被 catch、只打 warning、返回 0），表现是 `wrote/updated 0/4`——**不盯着这个数字就会被当成"本轮没新事件"混过去** |
| **改公式必须 `SCORING_VERSION` +1 并重算存量** | 否则库里会同时存在多个公式算出的分，前端按同一个字段排序，等于把三个公式的分放在一起比大小 |

---

## 6. 验收断言

- [ ] `price_move` 三个子字段都进 schema 的 `required`，缺失让本次理解失败重试
- [ ] 走真实模型跑第 3.2 节 prompt 里的**全部 false 示例**，通过率 **100%**
- [ ] "收益率升至 5.26%" → `is_price_move=true, move_pct=null`
- [ ] "TLT 跌至 10 个月低点" → `is_price_move=true, move_pct=null`
- [ ] "Tesla shares surge 12%" → `is_price_move=true, move_pct=12`
- [ ] `move_horizon=long_term` 的条目，幅度分按"无幅度"处理（0.10）
- [ ] **无 `price_move` 字段的存量行，冲击力 ≠ 0**（走兜底）
- [ ] 权威共振：3 个 social 类型信源 → 共振分 0.15（不是 1.00）
- [ ] 上线后 Top20 逐条人工核验 `punch_magnitude_pct`，**可疑误读 0 条**
