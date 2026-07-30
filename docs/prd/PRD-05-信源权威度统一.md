# PRD-05 · 信源权威度体系统一

**日期**：2026-07-31　**状态**：已实现（公式 v4）
**触发**：Hang Shang 问权威分怎么定的；核查暴露两表不同步（Benzinga 声明 5 分、LLM 实给 0.401）；Lawrence 裁决全面重修。

## 问题陈述

权威度存在两份互不同步的硬编码表（sources.py 声明分 / pipeline prompt 名单）。产量最大的几个源（Benzinga、金色、Followin、CryptoBriefing、YahooFinance）不在 prompt 名单里，被 LLM 按 aggregator 打分；CNBC 靠 v3 硬覆盖补丁（A=1.0 + 总分+0.05）绕过问题而非解决问题。X KOL 与一线媒体在权威共振因子里等价。

## 裁决（Lawrence 原话摘录）

- 「把 CNBC 的硬覆盖去除」
- Benzinga「给4分吧 或者你研究一下别那么高了」→ **4**
- KOL=CNBC「不合理，不要5分了区分度不够，赶紧全面修一下这套体系」
- 金色/CryptoBriefing 单独一档？「不用，**权威性看的是真权威，不是产量**……一定要像编辑一样好好地判断」

## 方案

1. **单一事实源** `crawler/authority_table.py`：频道表 + X 账号表 + Square 策略 + prompt 渲染器。每项带 note（定级依据），改分必须同时改 note。
2. **prompt 名单动态渲染**：SYSTEM_PROMPT 的 score_authority 判分行由表渲染注入（品牌跨档去重）。LLM 看到的名单 == 声明表，结构性消灭不同步。
3. **公式 v4**：移除 CNBC 硬覆盖两处（authority floor + 总分 +0.05）；权威共振因子排除社交/聚合/行情信号源（KOL≠机构媒体从公式层保证）。四处同步：scoring / rescore / QA SQL 镜像 / lab rank_pool。
4. **编辑式重校准**（真权威口径，逐源 note 见分级表）：Benzinga 5→4、cz_binance/heyibinance/WuBlockchain/bwenews/lookonchain 5→4、YahooFinance 4→3、Followin 4→3、Bloomberg-Politics 4→5；金色/CryptoBriefing 不动。
5. **QA 同步断言 ×5**：sources.py↔表、X 权重↔表、X 非官方号无 5 分、prompt 含渲染结果、benzinga 模块↔表。任何一处旁路改动直接红。
6. 全库重算走三护栏（预演→快照→写入，批次 20260731023623 可回滚）。

## 非目标

- 不动 time_trust 轴（source_trust.py 现状已工作）；web_search 52 域名白名单并入表列为 P1。
- 不做在线权威度判定（不确定性破坏 A/B 与一致性断言，已有共识）。
- 不做 RAG/向量检索（权威度是精确查表）。

## 验收

- [x] 预演影响面：8588 行覆盖 / 262 行数值变化 / Top20 换血 7 条（符合"仅 CNBC 系与社交共振事件回落"预期）
- [x] prompt 渲染注入且品牌唯一（BlockBeats 不再跨档重复）
- [ ] QA 全绿（同步断言 ×5 + 平价 + 公式一致性）
- [ ] 生产×实验室平价保持 ≥9/10

## 已知代价

改 prompt → hash 变化 → enrich 桥缓存整体失效，桥用公司额度重新预热（Lawrence 授权「多用公司 ai key」）；预热完成前的 pipeline 轮次会有部分个人账号成本。
