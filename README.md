# B9 推荐策略服务 · Recommendation Strategy Hub

> Binance B9 内容推荐模块的**新闻数据底座**：从全网召回加密新闻 → LLM 结构化打标签 →
> 双层去重 → 真实性校验 → 五因子重要性打分 → 产出生产 API + 7-tab 工作台。
>
> 支撑两个推荐场景：**Macro Insight**（全市场重要性排序）与 **Sector Insight**（板块相关性推荐）。

**线上地址**

| 用途 | 地址 |
|---|---|
| 工作台（HTTPS，任何人可开） | `https://currencies-granted-delight-lou.trycloudflare.com` |
| 工作台 / API（HTTP 直连，地址固定） | `http://34.138.247.158:8080` |

> ⚠️ HTTPS 走 Cloudflare quick tunnel，**隧道进程重启后子域名会变**。取当前有效地址：
> `ssh manus-vm "sudo journalctl -u b9-https-tunnel | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1"`

**开发者接入**：仓库为内部私有。需要读代码、跑本地流水线或申请 API secret，
请直接联系 lawrence zhu 开权限（*if you are a developer, please reach out to lawrence zhu for code access*）。

---

## 一、它解决什么问题

推荐位需要"**已经去过重、验过真、排过序**的事件流"，而不是原始新闻列表。这套服务把中间
那段脏活做掉：

- **召回**：八类渠道并行（英文/中文 RSS、自建 RSSHub、HTML 直解析、X KOL 时间线、
  X 全网搜索、搜索引擎、行情异动、催化剂日历）+ **全球主流市场**（2026-07-28 新增：
  美股/港股/日股/韩股/宏观政策，CNBC/MarketWatch/Nikkei Asia/SCMP/Korea Herald +
  dxFeed 机构级实时新闻，**明确不接 A 股**）
- **理解**：LLM 结构化成标准事件（双语标题、分档长短摘要、板块相关度、币种、实体、情绪、
  影响时间尺度、事件三元组指纹、**市场归属** `market_scope`：crypto/美股/港股/日股/韩股/宏观政策）
- **去重**：稳定指纹 + 256 维 embedding 语义聚类（cosine ≥ 0.82，**实测标定，非文档默认值**）+ 跨轮归并
- **验真**：五个客观信号（独立信源交叉、信源分层、时间一致性、孤证否决、矛盾检测），**零 LLM 成本**
- **排序**：`Score = 0.35·M + 0.20·T + 0.15·H + 0.15·A + 0.15·Q`，叠加**大盘情绪对齐**的
  有界查询时重排（≤15%，不改动库内分数，见 `crawler/market_mood.py`）——币圈与主流资本
  新闻混排进同一个列表，服务同时关心大盘和币价的用户

**关键结果**（真实测量，非估算）：事件库 1300+ 条；去重从实测 48.7% 冗余修到跨轮零重复；
单事件 LLM 成本 $0.0146 → $0.0093（**-36.5%**）；单轮约 19 分钟，其中 LLM 结构化占 78%；
3 家以上媒体报道的事件 **100% 无漏**。

---

## 二、快速开始

```bash
curl -s "http://34.138.247.158:8080/health"
```

`/health` 无需鉴权，可直接用作存活探针。取事件列表：

```bash
curl -s "http://34.138.247.158:8080/api/news?limit=20&sort=importance" -H "Authorization: Bearer <你的token>"
```

鉴权支持两种方式：`Authorization: Bearer <token>` 请求头，或 `?token=<token>` 查询参数
（后者方便非技术同事直接在浏览器点开；代价是 token 会进浏览器历史与访问日志，仅限内网可信场景）。
共 7 个有效 token（1 个 legacy + 5 个可分发给不同人/团队，便于单独吊销 + 1 个
`web` token 供工作台页面自身取数用，不建议对外分发）。

**完整接口文档** → [`docs/api-integration-guide.md`](docs/api-integration-guide.md)
（工程师版）｜ [`docs/API快速上手-非技术版.md`](docs/API快速上手-非技术版.md)（非技术版）

---

## 三、工作台（7 个 tab）

顶部两层导航：深色品牌条 + 三组药丸 tab。

| 分组 | Tab | 内容 |
|---|---|---|
| **新闻策略数据服务** | 01 生成流程 | 全链路流程图（步骤胶囊+实时耗时）、最近调度监控横条、八步流水线、打分模型、真实耗时标注 |
| | 02 数据展示 | **大盘情绪横幅**（近48小时重要性加权情绪，标注驱动因素）+ 事件表格 + 筛选（观测时间按生产轮次单选、**市场归属**筛选）+ 行展开详情（五因子/校验/内容理解标签/X 原贴）+ App 模拟器 + **信源统计**（380+ 信源的接入方式/校验分层/产出量，可筛选） |
| | 03 API 接入 | 端点清单、字段格式、案例数据、多语言示例、**页内直接试跑** |
| **策略产品工作台** | 04 评测工具 | Duplicate Tester（截图判重）· LLM 评测室（多 Agent 评测）· AB 对比（重合度/GSB）· **Persona 管理**（人设增删改查/文件导入/版本回滚/校准闭环）· **批量评测**（N 条 × M Agent 矩阵）· **评测历史**（自动留档/人工标注/外部效度） |
| | 05 策略实验室 | 因子权重实时调节重排 + 两版本对比（换手率/升降 case/规则总结） |
| **其它** | 06 历史数据 | 评测/实验结果的保存与检索 |
| | 07 开发者资讯 | 仓库入口、Dev Bill 成本预估、Built by 协作链路 |

全站带埋点统计；右下角 **Tell Lawrence More** 可提交反馈/需求/bad case（支持截图附件，
配置 SMTP 后自动推送邮件）。

---

## 四、目录结构

```
crawler/          数据流水线（召回 → 结构化 → 去重 → 校验 → 打分 → 入库）
  main.py           七类渠道的 fetch_*
  pipeline.py       编排 + LLM 结构化（prompt 与 schema 都在这里）
  dedup.py          指纹 + embedding 聚类（阈值 0.82 的标定过程见文件头）
  scoring.py        五因子打分
  verification.py   真实性校验（零 LLM）
  sector_relevance.py  Sector Insight 相关性（两层：便宜预筛 → LLM 精判）
  market_cap.py     币种市值 / BTC 倍数标签（ticker 消歧五道闸）
  staging.py        抓取与 LLM 处理的频率解耦
  storage.py        MySQL 读写 + 跨轮归并
api/              Flask 服务（每个 blueprint 自包含，便于多人并行开发）
  server.py         主入口与新闻端点
  lab_tools.py      策略实验室  ·  eval_tools.py    评测工具
  sector_insight.py Sector 推荐 ·  history_tools.py 历史/埋点/反馈
  enrich_bridge.py  本地预处理桥  ·  notify.py  邮件通知
  persona_store.py  评测 Agent 数据层（无 Flask 依赖，被下面两个 blueprint 共用）
  persona_tools.py  Agent 管理 / 校准闭环 / 评测历史 / 外部效度分析
web/              前端（纯 HTML，无构建）
  index.html        7-tab 工作台   ·  assets/app.css  共享设计系统
  lab.html          并入前的旧独立页（已不再路由，留档备查）
scripts/          qa_suite.py（交付门禁）· local_enrich_worker.py（Mac 侧）
                  stage_fetch.py · usage_monitor.py · backfill_*.py
config/           schema.sql · migrations/（12 个，全部幂等）· env.example
docs/             文档（见下）· design_source/（设计改版源材料）
```

---

## 五、文档索引

**产品与交付**
- [`docs/QA_REPORT.md`](docs/QA_REPORT.md) — **交付验收报告（no-bug 门禁结果）**
- [`docs/api-integration-guide.md`](docs/api-integration-guide.md) — 下游接入文档
- [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) — 待决策点与已知取舍（**每条都附倾向性判断**）

**工程与复盘**
- [`docs/PROJECT_RETROSPECTIVE.md`](docs/PROJECT_RETROSPECTIVE.md) — **跨项目 playbook**：
  13 条方法论 + 21 条踩坑 + 18 条降本增效 checklist
- [`docs/WORKLOG.md`](docs/WORKLOG.md) — 全部需求的跟进状态与实测证据
- [`docs/REQUIREMENTS_LOG.md`](docs/REQUIREMENTS_LOG.md) — 原始需求原文留痕（倒序）

**策略与方法论**
- [`docs/skill-macro-news-recommendation-v1.md`](docs/skill-macro-news-recommendation-v1.md) — Macro Insight 排序方案
- [`docs/skill-sector-news-recommendation-v5.md`](docs/skill-sector-news-recommendation-v5.md) — Sector Insight v5.1
- [`docs/skill-data-source-strategy.md`](docs/skill-data-source-strategy.md) — 数据源接入与评估
- [`docs/coverage-test-report-20260726.md`](docs/coverage-test-report-20260726.md) — 覆盖率交叉验证

**设计**
- [`docs/design_source/`](docs/design_source/) — 设计改版源材料：交付说明、设计系统样式表、
  高保真原型、原始 zip 包

---

## 六、运维

**调度**（全部 UTC+8，VM 系统/MySQL/cron 已统一切换）

| 任务 | 频率 |
|---|---|
| 主流水线 `run_pipeline.py` | **每小时整点**（2026-07-28 起；此前每 2 天 1 轮，扩召回接入主流市场新闻后必须提频，否则一条 CNBC 头条最长要等 48 小时才变成可见事件）。单轮上限 400 条（`B9_PIPELINE_BATCH`），带 flock 单实例锁防叠跑 |
| 免费信源高频存档 `stage_fetch.py` | **每小时 :30**（纯抓取不调 LLM，零成本；CNBC-TopNews 这类高频源 RSS 窗口只有 30 条约 2 小时的量，原来 2 小时一次正好卡在滚屏丢失边缘） |
| 数据库备份 | 每周日 11:00（保留 60 天） |

> **X API 已暂停**：`config/.env` 的 `X_FETCH_ENABLED=false`，主流水线本轮跳过 KOL 时间线与全网搜索两条腿，只处理 RSS/HTML/搜索引擎/行情/日历几类免费信源。这是**暂停不是移除**——改回 `true`（或删掉这一行）即可恢复，无需改代码。策略产品工作台（04/05 tab 的按需调用）不受影响，走的是 OpenAI，不经过这个开关。

**交付门禁**——改完任何东西，上线前必须跑到全绿：

```bash
ssh manus-vm "cd ~/crypto-news-crawler && set -a && source config/.env && set +a && python3 scripts/qa_suite.py"
```

97 条用例覆盖服务/鉴权/接口/写入链路/数据不变量/交互工具/评测 Agent 与校准闭环/全球市场扩召回与大盘情绪。退出码非 0 即**不得交付**。
用例只断言不变量（鉴权必须拦住、指纹不能重复、相关性必须连续……），可无脑重跑；
写库用例自清理；`--no-paid` 跳过唯一一条会花钱的用例。

**成本**（详见工作台 07 tab）：云主机 $3/天 + OpenAI + X API。X 按**拉回推文条数**计费
（$0.0021/条），成本旋钮是 `crawler/x_search.py` 的 `X_SEARCH_POST_BUDGET`。
本地预处理桥（`api/enrich_bridge.py` + `scripts/local_enrich_worker.py`）命中缓存
的条目不消耗 VM 侧 OpenAI 直连账号额度；2026-07-28 起结构化后端从本地 `claude` CLI
改为公司 LiteLLM 网关（Mac 挂公司 VPN 才连得通，VM 连不通，见下方"已知限制"），
费用走网关账户而非本机 Claude 订阅。**Mac 离线/网关不可达时全部 miss、自动回落
VM 的 OpenAI 直连账号，服务行为不受影响**（已用故障注入实测）。

---

## 七、已知限制（刻意接受，非缺陷）

1. HTTP + 静态 token —— 内部工具定位，**仓库必须保持 private**
2. 单实例无高可用 —— 靠每周备份 + 本地副本兜底
3. 切时区前的历史行时间戳仍为 UTC（比北京时间早 8 小时），刻意不回填：
   回填会污染 72h 归并窗与新鲜度过滤的比较基准，随数据老化自然淘汰
4. 各 blueprint 各自复制鉴权代码 —— 换取多 agent 并行开发时零耦合，属已知技术债
5. X 通道受 credit 余额约束：余额耗尽时返回 402，其余六类信源不受影响

---

## 八、Built by

| 环节 | 承担方 |
|---|---|
| Demand Planning & DevOps | **Manus**（Manus 1.6）— cloud computer & more |
| Engineering | **Claude Code**（Opus / Fable 5） |
| AI Processor API | **OpenAI**（GPT-5.4 / 5.4-nano） |
| Designer | **Claude Design**（Fable 5） |
