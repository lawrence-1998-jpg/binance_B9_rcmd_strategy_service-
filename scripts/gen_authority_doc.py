#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成《信源权威分级表》—— scripts/gen_authority_doc.py（2026-07-31）

docs/信源权威分级表.md 的**唯一生成入口**。此前是一次性 heredoc 生成的，
Lawrence 要求补附录后暴露问题：手工往生成物里加内容，下次重生成就会被冲掉。
现在拆成三段拼装：

    正文骨架（本文件内的 SKILL/CHANGELOG 常量）
  + 分级表（从 crawler/authority_table.py 实时渲染 —— doc==code）
  + 附录（docs/_authority_appendix.md 独立静态文件，深审 skill 细则）

改分 → 改 authority_table.py 后重跑本脚本；改判分方法论 → 改附录文件后重跑。
两边互不覆盖。用法：python3 scripts/gen_authority_doc.py
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "信源权威分级表.md"
APPENDIX = ROOT / "docs" / "_authority_appendix.md"

spec = importlib.util.spec_from_file_location(
    "authority_table", ROOT / "crawler" / "authority_table.py")
at = importlib.util.module_from_spec(spec)
spec.loader.exec_module(at)

HEADER = """# B9 信源权威分级表 · 判分逻辑

**维护人**：Lawrence Zhu（PM）　**文档生成**：`scripts/gen_authority_doc.py`（勿手改本文件）
**单一事实源**：`crawler/authority_table.py` —— 分级表由它自动渲染；改分只改那一个文件，
LLM prompt 名单、声明分、权威共振因子、QA 断言全部从同一份数据出（此前两表不同步导致
Benzinga 声明 5 分却被 LLM 按 aggregator 打 0.401，是本次重构的直接起因）。
判分方法论详则见文末附录（维护于 `docs/_authority_appendix.md`）。

---
"""

SKILL = """## 一、判分逻辑（编辑视角 Skill · 速查版）

**总原则：权威性看的是真权威，不是产量**（Lawrence 2026-07-31 裁决）。产量大、S/A 档
产出多，都不构成升档理由——那是覆盖面/召回问题，由别的因子负责。

### 1.1 五个判据（按顺序问）

| # | 判据 | 问法 | 权重 |
|---|---|---|---|
| 1 | **一手性** | 它是事件当事方/监管方/一手侦测方，还是转述者？ | 一手可直上 5 |
| 2 | **编辑体制** | 有独立编辑部、署名记者、公开更正制度吗？ | 无编辑体制封顶 4 |
| 3 | **独立采编比例** | 原创报道 vs 聚合/编译/通稿的占比？ | 聚合为主封顶 3 |
| 4 | **市场公认度** | 它的报道会被同行引用、会移动价格吗？ | 区分 5 与 4 |
| 5 | **历史准确率** | 有无重大误报记录？更正是否及时透明？ | 有劣迹降 1 档 |

### 1.2 档位定义

| 档 | 定义 | 例 |
|---|---|---|
| **5** | 一手权威：监管/交易所官方渠道；全球一线通讯社与旗舰财经媒体；加密垂类中具备同等编辑体制的头部 | Bloomberg、CNBC、SECGov 官号、CoinDesk、吴说 |
| **4** | 成熟二线：有真实编辑部与署名，但零售化风格明显 / 垂类深度有限 / 品牌影响力不及一线 | Benzinga、Forbes、金色财经 |
| **3** | 可用长尾：独立采编存在但浅，或聚合/转载占比高 | Yahoo Finance、Followin |
| **2** | 边缘：编辑质量勉强及格，仅作补充召回 | NewsBTC |
| **黑名单** | 内容农场：不打分，抓取阶段整条丢弃 | coinpedia、coingape 等 10 个域名 |

### 1.3 三条硬规则

1. **X/社交账号：媒体号与个人 KOL 一律 ≤4**。个人影响力 ≠ 机构编辑权威（cz_binance
   再大也没有编辑部和更正制度）。仅官方一手渠道可到 5：监管官号、交易所公告号、
   安全公司事件通报号——它们是当事方/一手侦测方，不是媒体。
2. **权威共振因子只统计机构媒体源**（RSS/API/爬虫直连），社交与聚合源一律不计——
   从公式层面保证「一个 5 分 KOL ≠ 一家一线媒体」，转推再多也不等于多家编辑室分别核实。
3. **权威度与时间可信度是两条正交轴**。财联社内容权威，但经 Google News 分发后时间戳
   不可信（分发时间≠发布时间）；Benzinga 反之——零售风格但时间戳一手且比 CNBC 快约 2 分钟。
   任何新源必须分别标注 `authority` 和 `time_trust`，混为一谈是 7/29 旧闻事故的根因。

### 1.4 新源接入流程

```
新源 → 按 1.1 五判据给初分（宁低勿高，未知默认 2）
     → 跑 2 周，人工抽 20 条比对同事件的一线媒体报道（准确性/时效/完整度）
     → 确认或调整档位，note 写明依据 → 进 authority_table.py（带 note，走 code review）
     → QA 同步断言自动生效
```

---
"""

CHANGELOG = """---

## 三、校准变更记录（2026-07-31，公式 v4）

| 变更 | 前→后 | 理由 |
|---|---|---|
| CNBC 硬覆盖（A=1.0 + 总分+0.05） | **移除** | 那是两表不同步的补丁；prompt 名单改为从本表渲染后，病根已除（Lawrence：『把CNBC的硬覆盖去除』） |
| Benzinga | 5→**4** | 真实编辑部+一手时效，但零售风格/AI辅助成稿；5 分曾让 3408 条快讯整体上浮 |
| cz_binance / heyibinance | 5→**4** | 个人 KOL 封顶 4（『与 CNBC 等价不合理』） |
| WuBlockchain / bwenews / lookonchain | 5→**4** | 媒体镜像号/分析号封顶 4，主品牌权威计在 RSS 主渠道 |
| YahooFinance | 4→**3** | 聚合分发 Reuters/AP 稿为主，原创少 |
| Followin快讯 | 4→**3** | 聚合转载为主 |
| Bloomberg-Politics | 4→**5** | 编辑权威=Bloomberg 整体；此前混淆了频道相关性与编辑权威 |
| 金色财经 / CryptoBriefing | **不变**（4/3） | S/A 产出高是产量效应，权威性不看产量 |
| 权威共振因子 | 排除社交/聚合源 | 公式层保证 KOL≠机构媒体 |

---
"""


def render_tables() -> str:
    L = []
    A = L.append
    A("## 二、分级表（新闻源 → 权威打分 → 备注）")
    A("")
    A("### 2.1 RSS / HTML / API 频道")
    A("")
    A("| 信源 | 分 | 备注（定级依据） |")
    A("|---|---|---|")
    for name, (a, brand, note) in sorted(at.CHANNELS.items(),
                                         key=lambda x: (-x[1][0], x[1][1])):
        A(f"| {name} | **{a}** | {note} |")
    A("")
    A("### 2.2 X 账号（%d 个）" % len(at.X_ACCOUNTS))
    A("")
    A("| 账号 | 分 | 类型 | 备注 |")
    A("|---|---|---|---|")
    for h, (a, cat, note) in sorted(at.X_ACCOUNTS.items(),
                                    key=lambda x: (-x[1][0], x[1][1])):
        A(f"| @{h} | **{a}** | {cat} | {note} |")
    A("")
    A("### 2.3 Binance Square 媒体号")
    A("")
    A(f"当前**整体停用**（无发布时间字段，曾是陈旧新闻事故源头）。若恢复：平台号默认 "
      f"**{at.SQUARE_POLICY['default_authority']}** 分、有独立采编的头部入驻号封顶 "
      f"**{at.SQUARE_POLICY['cap']}**，时间可信度一律按聚合器处理（`time_trust="
      f"{at.SQUARE_POLICY['time_trust']}`，平台分发时间≠原文发布时间）。详细判定"
      f"细则见附录 B。")
    A("")
    A("### 2.4 搜索召回域名与黑名单")
    A("")
    A("搜索引擎召回的长尾域名走 `crawler/web_search.py` 的 52 域名白名单（同一套 5/4/3 档），")
    A("未命中默认 2；10 个内容农场域名黑名单**硬过滤**（不打分，LLM 之前整条丢弃）。")
    A("")
    return "\n".join(L)


def main() -> int:
    appendix = APPENDIX.read_text() if APPENDIX.exists() else "（附录缺失：docs/_authority_appendix.md 不存在）\n"
    doc = HEADER + "\n" + SKILL + "\n" + render_tables() + "\n" + CHANGELOG + "\n" + appendix
    OUT.write_text(doc)
    print(f"已生成 {OUT}（{len(doc.splitlines())} 行；频道 {len(at.CHANNELS)}、X {len(at.X_ACCOUNTS)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
