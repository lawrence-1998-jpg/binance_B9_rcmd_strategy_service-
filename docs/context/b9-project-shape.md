---
name: b9-project-shape
description: B9 推荐策略服务到底在做什么、分几步走、各步现在到哪了
metadata: 
  node_type: memory
  type: project
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-25T20:06:39.161Z
---

B9 是 Binance App 里的内容推荐模块，下设两个 Tab：**Sector Insight**（按用户持仓板块推新闻，相关性优先、宁缺毋滥、最多 3 条）和 **Macro Insight**（全市场重要性排序、保底供给）。本项目是给这两个场景造**数据底座 + 排序策略 + API**。

线上原版的病根有两个，都在 `materials/screenshots/` 的截图里有实证：按发布时间强排（不重要的人事新闻排第一）、没有去重（K25.ai 融资一条新闻并列出现 3 次）。

**五步走**（截至 2026-07-26）：
1. 数据召回层 — ✅ 信源 9→35 个 + 32 个 X KOL
2. LLM 结构化 pipeline — ✅ gpt-5.4，五级事件分级 + 泛科技防火墙
3. 推荐策略设计 — ✅ 两份 skill 文档（Sector v5.1 / Macro v1）
4. **去重重构 + H 因子 + 数据清洗 — ✅ 2026-07-26 完成**（见 [[b9-dedup-gap]]）
5. 推荐策略 API 服务 — 🔄 基础查询接口已上线，Sector/Macro 两个推荐接口待开发

**当前重心**：Lawrence 明确说 Sector 的板块标签先不做，**先把数据源搞干净再对事件加标签**。他认为加密行情大变化和美股宏观类新闻欠召严重。

细节都在仓库里（`docs/background.md` 讲背景、`docs/task_describe.md` 讲任务分解、两份 skill 文档讲公式），不要在 memory 里重复抄。

相关：[[b9-vm-access]]、[[b9-dedup-gap]]、[[b9-x-api-capacity]]
