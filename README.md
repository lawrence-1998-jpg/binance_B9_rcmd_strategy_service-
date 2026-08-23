# B9 新闻事件推荐策略服务

把市场上发生的重要事，及时、准确、按对的顺序，送到会在意的人眼前。
这是 B9 推荐策略的**数据底座 + 排序策略 + API + 展示站**原型，供产品验证与研发交接。
线上化后的策略已落地币安产品三个位置：早午日报 / Macro Insight / Sector Insight。

> ⚠️ **当前为应急运行态（2026-08-23 起）**：原 GCP VM 整机丢失，服务临时跑在一台 Mac 上。
> 详情与重建方法：[docs/incidents/2026-08-23-vm-loss-and-mac-recovery.md](docs/incidents/2026-08-23-vm-loss-and-mac-recovery.md)。
> 接手的人**先读那份事故报告**，再回来看这里。

## 这个系统做什么

每 30 分钟一轮：30 个 RSS 信源 + dxFeed 机构快讯 + Benzinga →
向量去重（跨轮归并，阈值 0.82）→ LLM 结构化（中英标题/摘要、实体、事件三元组、情绪）→
多信源真实性交叉校验 → 可交易实体标注 + 市值分档 → 七因子加权打分入库 →
API 出口再套情绪/市场/新鲜度倍率 → 65 字段 JSON。

排序公式（v6）：`0.26·冲击面 + 0.16·广度 + 0.16·时效 + 0.14·冲击力 + 0.10·热度 + 0.10·权威 + 0.08·质量`
——本注释同款公式在 4 处镜像（scoring.py / rescore 脚本 / QA / lab_tools），改动必须四处同步。

## 从哪读起（按你是谁）

| 你是 | 读这些 |
|---|---|
| **接手运维/要把它跑起来** | 事故报告里的 Runbook → `config/env.example`（配出你的 .env）→ 本页「常用命令」 |
| **接手策略/产品** | `docs/HISTORY.md`（九个阶段的演化与教训）→ `docs/PROJECT_PLAN.md` → Confluence《B9 内容推荐策略 All in One》 |
| **接手研发/要接 API** | `docs/api-integration-guide.md` → `docs/prd/`（两份交接 PRD） |
| **接手数据分析** | `docs/spade-access-plan.md`（Spade 平台接入全记录）→ `docs/analysis/`（价格敏感度研究 + 指标体系） |
| **想知道踩过什么坑** | `docs/WORKLOG.md`（100+ 条带教训的流水）→ `docs/incidents/` |

## 目录结构

```
crawler/    抓取、去重、打分、校验、市值——数据生产全链路
api/        Flask API + 各业务 blueprint（server.py 是入口）
web/        展示站（index.html 单页，多 tab）
scripts/    enrich worker、QA 套件（135+ 断言）、密钥轮换、回填工具
config/     .env 模板、22 个数据库 migrations（幂等，按序执行）
docs/       全部文档；analysis/ 是研究报告；incidents/ 是事故档案
backups/    数据库备份（⚠️ 见事故报告：备份必须异地，别只放本机）
```

## 常用命令

```bash
# 起 API（先按事故报告 Runbook 配好 MySQL 与 .env）
./.venv-mac/bin/python api/server.py

# 跑一轮抓取管线（小批量）
B9_PIPELINE_BATCH=300 ./.venv-mac/bin/python run_pipeline.py

# enrich worker（吃掉抓取队列；API_BASE 指向当前 API 所在机器）
B9_API_BASE=http://127.0.0.1:8080 B9_API_TOKEN=<你的token> ./.venv-mac/bin/python scripts/local_enrich_worker.py

# QA 全量（135+ 断言，改核心逻辑后必跑）
./.venv-mac/bin/python scripts/qa_suite.py

# 查看新闻（数据老于5天必须带 max_age_days=0）
curl "http://127.0.0.1:8080/api/news?limit=5&max_age_days=0&token=<你的token>"
```

## 密钥清单（值不在库里，向 Lawrence 索取）

本仓库**公开**，任何密钥值一律不入库。运行所需：

| 密钥 | 位置（Lawrence 本机） | 用途 |
|---|---|---|
| `config/.env` 整份 | 仓库目录下（已 gitignore），模板见 `config/env.example` | MySQL 密码、7 档 API token、X Bearer 等 21 项 |
| 公司 LiteLLM key | `~/.b9/credentials.json`（`scripts/b9key.py` 管理） | LLM enrich（走公司网关，需 VPN devfdg zone） |
| Spade personal token | `~/.b9/spade_token` | 大数据平台取数（内网） |

历史上曾因公开化做过一次 git-filter-repo 全历史密钥清洗（2026-08-05），
`.githooks/pre-commit` 有密钥格式拦截——**不要绕过它提交**。

## 已知约束

- **数据缺口**：2026-07-26 → 08-22 的事件数据随 VM 丢失，不可恢复
- **LLM 网关**：`litellm.devfdg.net` 需公司 VPN 对应 zone；不通时抓取队列安全积压，通了自动消化
- **X 信源**：按条计费，默认关闭（`X_FETCH_ENABLED`）
- 时间口径全链路 UTC+8；`importance_score` 是持久化派生值，带 `scoring_version` 标记
