---
name: config-must-render-into-prompt
description: "声明式配置表与LLM prompt里的名单是两份表就必然漂移——prompt必须由配置表渲染注入，并用QA断言\"渲染结果in SYSTEM_PROMPT\"钉死"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-30T18:54:13.801Z
---

2026-07-31 B9 权威度事故：sources.py 声明 Benzinga=5 分，但 LLM prompt 里的
媒体名单是另一份手写文本、没有它——LLM 按 aggregator 给 0.401（5 天 3408 条
均值），而且这几个"名单外"的源恰恰是产量最大的。此前的应对是给 CNBC 开
硬覆盖后门（A=1.0+总分+0.05），补丁对抗病根。

**Why**: 只要"配置表"和"prompt 里的同一份知识"是两处手写，就必然漂移，
且漂移不报错——LLM 拿到过时名单照样输出合法分数。这是 lab-prod 公式分叉
的同族问题，但更隐蔽：漂移藏在自然语言里，grep 都难查。

**How to apply**: 任何"LLM 需要知道的枚举/名单/档位"必须：①单一事实源
（数据文件/表，每项带定级 note）；②prompt 中该段由渲染函数生成注入；
③QA 断言 `render() in SYSTEM_PROMPT` + 各消费方==表；④渲染注意跨档去重
（B9 实测 BlockBeats 快讯5/文章4 按档各自去重会两档都出现，LLM 无所适从）。
代价要预告：改表→prompt hash 变→预处理缓存整体失效，批量改低频改。
**成本窗口实操**（2026-07-31 实测）：hash 切换后到"便宜预处理器在新 hash 下
缓存追平"之间是纯付费窗口。部署时序应为：改完立刻重启 API（让预处理器拉到
新 prompt）→ 确认预处理器开始按新 hash 产出缓存 → 才允许下一轮消费跑。
实测桥 5 分钟唤醒一次，一批 200+ 条，积压 282 条在下一轮 cron 前基本追平，
窗口成本≈0；若改完不重启 API，桥会继续在旧 hash 下白干一整批。
相关：[[lab-prod-must-share-formula]]、[[keyword-blocklist-unreliable]]
