# Skill 02 · 广度因子（breadth / B）

> **一句话**：「影响一个指数」和「影响一只股票」是完全不同的量级，
> 而改造前系统里**没有任何字段区分这件事**——这正是我们的内容质感与 CNBC 差距的直接来源。

---

## 1. 业务问题

对比同一时刻的首屏：

| | CNBC（友商参照） | 我们（改造前） |
|---|---|---|
| 首屏典型条目 | "Dow rallies 600 points" | "分析师比较联合太平洋与诺福克南方" |
| 事件量级 | **指数级 / 跨市场** | **单一个股级** |

两者在旧的五因子下**可能拿到相近的分**：一条个股研报如果时效新、信源多、权威高、写得清楚，
四个因子全占优，总分完全可以压过一条"道指大涨"。
系统里缺的不是权重，是**"这件事影响多宽"这个维度本身**。

对用户的直接后果：打开产品看到的是一堆看不懂、也与自己持仓无关的个股消息，
**读不到"今天市场整体发生了什么"**。这就是老板说的"热度感、氛围感和 CNBC 完全不同"。

---

## 2. 做法：枚举，不是让模型直接打分

由内容理解阶段的 LLM 输出 `breadth_level` 枚举，再映射成分值。

**为什么用枚举而不是让 LLM 直接给 0–1 分**：
模型在「这是板块级还是多标的级」上比在「这该给 0.55 还是 0.6」上**可靠得多**。
枚举把判断收敛到一个封闭集合，可复现、可断言、可人工抽查。

### 2.1 prompt 片段（可直接抄）

```
## BREADTH (for `breadth_level`) — how wide is the blast radius?

  cross_market   Spans markets or asset classes: Fed decisions, global bond selloff,
                 a war disrupting oil routes, a chip crash that also hits U.S. names
  market_index   One market's benchmark: Nikkei -4%, KOSPI circuit breaker, Dow +600
  sector         A sector moves together: chipmakers slump, DeFi broadly down
  multi_asset    2–5 named tickers: AMD / Micron / Nvidia falling together
  single_asset   One company or one token

Judge the blast radius of the EVENT, not the ambition of the headline. A single company's
earnings miss is single_asset even if the article speculates about the whole sector.
```

### 2.2 分值映射

| breadth_level | B 值 | 典型 |
|---|---|---|
| `cross_market` | **1.00** | 美联储决议、全球债市抛售、战争扰动油路 |
| `market_index` | **0.80** | 日经跌 4%、KOSPI 熔断、道指涨 600 点 |
| `sector` | **0.60** | 芯片股集体重挫、DeFi 普跌 |
| `multi_asset` | **0.35** | AMD / 美光 / 英伟达同步下跌 |
| `single_asset` | **0.15** | 单一公司 / 单一代币 |
| **缺失 / 无法判定** | **0.15** | 按 single_asset —— **拿不准就当窄的** |

权重：`B` 在七因子里占 **16%**（仅次于影响面 26%）。

> ⚠️ **缺失时的兜底方向是"往窄了算"，不是给中位数。** 给 0.5 等于让判不出来的内容
> 白捡一个中等广度分，噪音会被系统性抬上来。宁可漏推一条真大事，也不要放一堆判不清的东西上首屏。

---

## 3. 这个因子被复用在两个地方（改的时候要一起想）

`breadth_level` 不只是七因子里的一项，它还是**市场重要性跨市场豁免的判据**：

```python
if event.get("breadth_level") == "cross_market":
    return max(base_weight, 1.0)      # 跨市场事件不打折
```

见 [`skill-01-市场重要性.md`](skill-01-市场重要性.md)。
用现成的 `breadth_level` 而不是新增一个"是否跨市场"字段——
"已经外溢到多个市场"正是 `cross_market` 这一档的定义，**语义完全吻合，不需要让 LLM 多判一次**。

> 这意味着 `cross_market` 这一档的判定质量会**同时影响两处**：
> 判宽了，日韩小事会连带拿到不打折的待遇；判窄了，真正外溢的大事会被市场倍率压下去。
> 抽查时请重点看这一档。

---

## 4. 为什么广度不能被"影响面"吸收

有人会问：`score_market_impact`（影响面 M）不是已经在回答"这件事多重要"了吗？

不是同一个问题：

| | 问的是 | 例：某中型药企 FDA 获批 |
|---|---|---|
| **影响面 M** | 这件事**有多重要** | 对这家公司是生死大事 → 分高 |
| **广度 B** | 这件事**影响多宽** | 只影响一只股票 → `single_asset` → 0.15 |

M 由 LLM 相对**事件自身**判定，天然带"对当事人多重要"的视角；
B 问的是**覆盖多少市场参与者**。两者正交，缺一个就会出现"对少数人极重要的事占住多数人的首屏"。

---

## 5. 验收断言

- [ ] `breadth_level` 进 JSON schema 的 `required`，缺失让本次理解失败重试
- [ ] 五档枚举之外的值一律按 `single_asset` 处理（0.15），**不报错、不给中位数**
- [ ] "道指涨 600 点" → `market_index`；"某公司财报不及预期" → `single_asset`
- [ ] "芯片暴跌拖累美股与亚洲科技股" → `cross_market`（这条同时触发市场倍率豁免）
- [ ] 权重调 0 后排序可退回改造前，用于验证这个因子的真实贡献
- [ ] 上线后 Top20 的 `breadth_level` 分布中，`single_asset` 占比**显著低于**全库分布
      —— 这是这个因子有没有起作用最直接的度量
