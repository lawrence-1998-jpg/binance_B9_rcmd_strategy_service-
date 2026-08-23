---
name: b9-project-shape
description: B9 推荐策略服务到底在做什么、分几步走、各步现在到哪了
metadata: 
  node_type: memory
  type: project
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-26T19:03:58.896Z
---

B9 是 Binance App 里的内容推荐模块，下设两个 Tab：**Sector Insight**（按用户持仓板块推新闻，相关性优先、宁缺毋滥、最多 3 条）和 **Macro Insight**（全市场重要性排序、保底供给）。本项目是给这两个场景造**数据底座 + 排序策略 + API + 前端展示网站**。

线上原版的病根有两个，都在 `materials/screenshots/` 的截图里有实证：按发布时间强排（不重要的人事新闻排第一）、没有去重（K25.ai 融资一条新闻并列出现 3 次）。

**原始任务四步走**（`docs/PROJECT_PLAN.md` 有 reframe 版本，`docs/REQUIREMENTS_LOG.md` 有原始 prompt 全文）：
1. 数据源梳理 + 抓取 skill — ✅ 信源 9→47+ 个 + 32 个 X KOL + X全网搜索 + 搜索引擎 + 行情信号模块；`docs/skill-data-source-strategy.md`
2. Pipeline 结构化 + 去重 + 真实性校验 — ✅ 去重重构（见 [[b9-dedup-gap]]）+ `crawler/verification.py`（客观信号、零LLM成本）+ 内容理解标签（`sector_tags`真相关才打/entities/sentiment）+ 市值标签（`crawler/market_cap.py`）
3. 部署 + 定时 + MySQL + API — ✅ 主pipeline 12h/次（原4h降本），高频源另有 2h/次存档cron 解耦（`crawler/staging.py`）
4. 前端展示网站 — ✅ 设计改版已上线：Organic 设计系统（赤陶/鼠尾草配色）+ 顶部分组 tab（侧边栏已移除）+ 7 个 tab 合并进同一个 `web/index.html`（策略实验室、评测工具、开发者资讯全部并入，`lab.html`/`eval.html` 不再独立路由）

**当前状态（2026-07-27）**：核心功能 + 视觉改版均已完备。事件库 1300+ 条。
API 有 HTTPS（Cloudflare quick tunnel，子域名会变）+ 7 个 token（1 legacy + 5
可分发 + 1 内部 web token）。时区已真正统一到 UTC+8（代码写入口径 + 存量数据
都已改，不只是系统时区）。新增「信源统计」子 tab 和 `/api/source-catalog`、
`/api/run-nodes` 两个端点。全站做过一轮隐私处理（demo 站不可反推雇主/个人），
但联系人具名与 GitHub 仓库直达链接后来又按 Lawrence 要求恢复了。

**未决事项集中在** `docs/OPEN_QUESTIONS.md`（内容理解标签+30%成本是否接受、Sector Insight 相关性因子仍是简化版二元判断等），不要在 memory 里重复抄，那份文档才是权威来源。

细节都在仓库里，不要在 memory 里重复抄：`docs/background.md`（产品背景）、`docs/PROJECT_PLAN.md`（规划）、`docs/WORKLOG.md`（跟进状态）、`docs/REQUIREMENTS_LOG.md`（原始需求）、`docs/OPEN_QUESTIONS.md`（待决策点）、两份 skill 文档（打分公式）。

相关：[[b9-vm-access]]、[[b9-dedup-gap]]、[[b9-x-api-capacity]]、[[flask-blueprint-syspath-gotcha]]、[[b9-blueprint-auth-duplication]]
