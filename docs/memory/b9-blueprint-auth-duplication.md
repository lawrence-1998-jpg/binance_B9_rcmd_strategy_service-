---
name: b9-blueprint-auth-duplication
description: B9 项目每个 Flask blueprint 各自复制一份鉴权表——改 token 必须五处一起改，已经因此出过两次 401 故障
metadata: 
  node_type: memory
  type: project
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-26T19:04:13.778Z
---

`api/server.py`、`lab_tools.py`、`eval_tools.py`、`history_tools.py`、
`sector_insight.py`、`enrich_bridge.py`、`source_catalog.py` 各自都在文件顶部
复制了一份 `API_TOKENS` / `VALID_API_KEYS` / `require_api_key`，不是从一处
import。这是当初刻意的选择（多 agent 并行开发时零耦合），记在 README 的
「已知限制」里，不是我不知道的债。

**Why 这条要单独记**：已经真实咬过两次。第一次是给 eval_tools 加鉴权时漏了
其余文件；第二次是 2026-07-26 把页面 token 换成 `b9-web-*` 时只加了
`server.py`，lab/eval/history/sector/enrich 五个 blueprint 全部 401，
是 Lawrence 自己在浏览器里点出来的，不是我测出来的。

**How to apply**：以后任何一次改 `API_TOKENS`（新增 token、吊销 token、改
`require_api_key` 逻辑），必须：
1. `grep -rn "API_TOKENS\s*=" api/*.py` 确认改了几处、还剩几处没改
2. 全部改完后跑一遍 `scripts/qa_suite.py`（鉴权那一节会挨个打这些 blueprint）
3. 更理想是找个空窗期把它收敛成从 `server.py` 或独立 `auth.py` 里 import，
   但 Lawrence 没要求现在做，别自己顺手"顺便重构"了这条——那是主动违反
   "不要做没被要求的事" 的通用原则。

相关：[[b9-project-shape]]
