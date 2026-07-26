# 设计改版源材料（2026-07-26）

本目录保存的是**改版过程材料**，不参与线上运行，放这里是为了让下次改版能追溯
"当时依据什么做的"。

| 文件 | 说明 |
|---|---|
| `DESIGN_HANDOFF.md` | 设计师给的实施说明原件（Organic 设计系统 token、逐 tab 要求、性能红线） |
| `organic-styles.css` | 设计系统原始样式表，是 `web/assets/app.css` 里 token 取值的出处 |
| `_fragment_panel5_lab.html` | 策略实验室并入主站时的中间产物片段（已集成进 index.html，保留备查） |
| `_fragment_panel7_devnews.html` | 07 开发者资讯的中间产物片段（同上） |

线上真正生效的是 `web/assets/app.css` + `web/index.html`。**改样式请改那两个，
不要改这里的片段**——它们已经是历史快照，不会被再次集成。

`web/lab.html` 仍保留在仓库里但**已不再被路由**（`/lab` 现在 301 到 `/#tab5`），
作为并入前的参考版本留存；确认新版稳定运行一段时间后可以删除。
