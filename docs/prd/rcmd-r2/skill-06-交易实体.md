# Skill 05 · 交易实体识别与加成（tradable）

> **一句话**：老板要"刺激标的物交易的感觉"，而根因不是缺加分项，
> 是**占池一半的内容根本没有标的物这个字段**——而数据其实一直有，一直在被丢掉。

---

## 1. 问题

`coins` 字段按设计只抓加密 ticker（prompt 明写 `bitcoin→btc`）。实测近 5 天覆盖率：

| market_scope | 条数 | 有标的 | 覆盖率 |
|---|---|---|---|
| us_stock | 4163（50%） | 32 | **0.8%** |
| crypto | 1210 | 642 | 53%（币安可交易 47.9%） |
| 其余 | 2986 | ~0 | ~0% |
| **全池** | | | **7.5%** |

而 **Benzinga 编辑部自己标注的真实 ticker 一直躺在 `raw_items_staging.matched_symbols` 里**
（覆盖率 **98.1%**，dxFeed **95%**），只被拿去做优先级路由，**从没进过事件表**。

> 🔴 **接一个已有字段的收益，远大于让 LLM 多抽一次。**
> 做任何"数据不够"的判断之前，先把上游已经采到的字段盘一遍。

---

## 2. 三级取数阶梯（先免费后付费）

| 级 | 来源 | 成本 | 覆盖 |
|---|---|---|---|
| ① | `staging.matched_symbols` 直通 | **零成本、零 prompt 改动** | Benzinga / dxFeed（约占美股供给的绝大部分） |
| ② | `coin_metrics[].binance_spot` 校验 | 零成本（已有字段） | 加密侧 |
| ③ | 标题品牌名匹配（中英双语） | 零成本 | 长尾补充 |
| ④ | **LLM 抽取** | 改 prompt → 理解缓存整体失效 | 长尾 RSS / 搜索 —— **本轮不做，单独排期** |

**实现要点**：
- `matched_symbols` 要从 staging 一路透传到事件表，**去重合并时要 union 整个簇的 symbols**（同一件事的不同报道各自带着不同 ticker）
- ③ 的英文品牌名要在 **中文标题和英文标题两边都扫**（只扫一边等于没做——冲击力那边就是这么漏的）

---

## 3. 「能买到」的硬判据

> 这是需求的硬约束，**必须可验证，不能拍脑袋**。

| 资产类别 | 判据 |
|---|---|
| 加密 | `coin_metrics[].binance_spot == true`（币安现货在架） |
| 美股 | ticker ∈ **大盘蓝筹白名单**（约 130 支，按 staging 真实出现频次筛出） |
| 指数 ETF | ∈ INDEX_ETF：SPY / QQQ / DIA / IWM / VIX / SOXX / XLK / XLF / XLE / USO / GLD / ARKK / SMH / IBIT / FBTC / ETHA |
| 指数本身 | SPX / DJI / IXIC / RUT → **识别用于展示映射，但 `tradable = false`**（买不了 SPX，只能买 SPY） |
| 日 / 韩 / 港股 | **一律 `tradable = false`** —— 币安用户买不到，标了是噪音 |

**白名单的意义**：Benzinga 一条新闻最多挂 12 个 ticker，其中不少是边缘小盘股。
只展示用户**真买得到、且认得出**的标的，避免首页变成 ticker 刷屏。
（老板裁决原话：只标用户认得出的。）

---

## 4. 加成必须分档

```python
TRADABLE_BONUS_FOCUSED   = 0.06     # 1–4 个可交易标的：指向明确
TRADABLE_BONUS_BROAD     = 0.02     # ≥5 个：宽泛市场评论，给一点但不多
TRADABLE_BROAD_THRESHOLD = 5

def tradable_bonus(event, k_focused=0.06, k_broad=0.02):
    n = int(event.get("tradable_count") or 0)
    if n <= 0:
        return 0.0                  # ← 没有标的物：加 0，不惩罚
    return k_broad if n >= TRADABLE_BROAD_THRESHOLD else k_focused
```

> 🔴 **不分档会与需求意图正好相反。**
> 实测 Benzinga 的「盘前综述」一条挂 7 个 ticker（DJI, IXIC, SPX, SPY, QQQ, IWM, MSFT）——
> 那恰恰是**最没有交易指向性**的内容；真正刺激交易的是"NVDA 财报炸了"这种单一主标的事件。
> 不分档会把泛泛的大盘综述**系统性顶上去**。

**没有标的物 → 加 0，不惩罚。** 一条重大宏观政策新闻本来就落不到具体标的上，
它不该因此被打压，只是不额外加分。

---

## 5. 展示

事件标题后以 **tag** 形式展示（本轮**纯展示不可点**，老板裁决"先这样"）。

字段：

```json
"tradable_entities": [
  {"symbol": "NVDA", "name_zh": "英伟达", "type": "us_stock", "tradable": true},
  {"symbol": "BTC",  "name_zh": "比特币", "type": "crypto",   "tradable": true},
  {"symbol": "SPX",  "name_zh": "标普500", "type": "index",   "tradable": false}
],
"tradable_count": 2
```

`tradable_count` 冗余存储，便于 SQL 直接过滤与统计（不用每次解 JSON）。

---

## 6. ⚠️ 报覆盖率时必须同时报首屏命中数

我们报过一次「美股实体覆盖涨 18 倍」，而**首屏 0/10 有标签**。

**聚合覆盖率会掩盖首屏。** 全库覆盖率是分母很大的平均数，
而用户只看得到前 10 条——那 10 条恰好都没命中是完全可能的。

**规定动作**：任何覆盖率数字，必须与 **Top10 实际命中数**成对出现。

---

## 7. 验收断言

- [ ] `matched_symbols` 从 staging 透传到事件表，去重合并时 **union 整个簇**
- [ ] 全池覆盖率从 7.5% → **≥ 40%**
- [ ] **同时报 Top10 实际命中数**，不能只报聚合覆盖率
- [ ] 日 / 韩 / 港股 ticker → `tradable = false`
- [ ] SPX / DJI / IXIC → 能识别出中文名，但 `tradable = false`
- [ ] 加密标的必须过 `binance_spot == true`，未上架的币 `tradable = false`
- [ ] 挂 7 个 ticker 的盘前综述，加成 = 0.02（不是 0.06）
- [ ] 无标的事件加成 = 0（**不是负数**）
- [ ] 英文品牌名在 `title_zh` 和 `title_en` **两边都扫**
- [ ] 卡片响应里 `tradable_entities` 与 `tradable_count` 都在字段白名单里
      （⚠️ 取数 SQL / 计算 / 请求解析 / 响应序列化 / 界面渲染是**五个独立环节，漏哪处都不报错**）
