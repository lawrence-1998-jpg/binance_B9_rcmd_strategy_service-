# 截图材料说明

本目录存放 B9 推荐策略项目相关的全部截图与图片材料，供接手 Agent 快速理解产品背景和评测现状。

## 目录结构

### `app-ui/` — Binance App 线上界面截图

| 文件 | 内容 |
|---|---|
| `app_macro_insight_feed.webp` | **核心参考**：Macro Insight 信息流界面（手机截图），展示线上版的新闻列表样式、信源标注、时间戳格式 |
| `app_macro_insight_dedup_issue.png` | 去重问题标注截图：K25.ai 同一条新闻出现3次（MarsBit/ChainCatcher/PANews），红色箭头标注，是 Step 2 去重任务的直接需求来源 |
| `app_ui_latest.webp` | 最新版 App 截图（含 Sector Insight + Macro Insight 双 Tab） |
| `app_ui_02.webp` ~ `app_ui_17.webp` | 连续手机截图序列，展示完整的 Sector Insight 和 Macro Insight 浏览体验 |

### `strategy-docs/` — 策略文档截图（来自内部 Confluence）

| 文件 | 内容 |
|---|---|
| `scoring_formula.png` | **核心公式**：板块融合打分公式 `Score = Rel^1.5 × (0.25T + 0.25H + 0.20A + 0.30M)`，含前置硬门与后置去重规则 |
| `scoring_formula_v2.png` | 同一公式的另一版本截图（更清晰） |
| `workflow_5steps.png` | **完整工作流**：5步 Pipeline 表格（实体提取→标签生成→硬门+打分→超重去重→体验混排+召回≤Top3） |

### `evaluation/` — 评测与对比截图

| 文件 | 内容 |
|---|---|
| `three_col_comparison.png` | **三列对比评测**：线上版（时间倒序，79条）vs Skill v1（重要性打分+去重，52条有效）vs 核心差异，红圈标注泛科技内容（AMD CEO/Cognition/Anthropic）需要防火墙过滤 |
| `evaluation_02.png` | 评测截图 2 |
| `evaluation_03.png` | 评测截图 3 |
| `news_sample_01_trump_meme.png` | 新闻样本：特朗普加密伦理规则（TRUMP/WLFI meme 板块影响分析，红圈标注） |
| `news_sample_07_daily_digest.png` | 新闻样本：昨夜今晨汇总型资讯（bStocks 板块短线影响分析，红圈标注） |
| `news_sample_02.png` ~ `news_sample_12.png` | 其余新闻样本截图（含 LLM 分析注释，展示各类新闻的板块相关性判断） |

## 关键参考优先级

接手 Agent 应按以下顺序阅读：
1. `strategy-docs/scoring_formula.png` — 理解打分公式
2. `strategy-docs/workflow_5steps.png` — 理解完整 Pipeline
3. `app-ui/app_macro_insight_dedup_issue.png` — 理解去重问题
4. `evaluation/three_col_comparison.png` — 理解评测框架
5. `app-ui/app_macro_insight_feed.webp` — 理解目标产品形态
