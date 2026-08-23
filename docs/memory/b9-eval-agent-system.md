---
name: b9-eval-agent-system
description: B9 评测 Agent 系统的两个关键设计取舍——人设拆五要素防漂移、校准两段式生效
metadata: 
  node_type: memory
  type: project
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-28T01:38:30.905Z
---

2026-07-28 建的评测 Agent 子系统（`api/persona_store.py` + `persona_tools.py`，
migration 012），有两个设计取舍是踩过推理才定下来的，改动前要理解：

**1. 人设拆成五个字段（人格/故事/偏好/记忆/心情）而不是一整段 prompt。**
原因是校准闭环需要明确的作用靶点：让 LLM 改写整段 prompt 时，它每次都会顺手润色
不该动的地方，几轮下来人设必然漂移。这是 LLM 改写文本的固有行为，靠 prompt 约束
不住，只能靠把可改区域切小。所以 `apply-calibration` 只允许改 personality 和
preferences 两列——story 和 memory 是这个人的既成事实，不该因为"判得不准"被改写。

**2. 校准两段式生效：提交即进 calib_memory（零成本，下次评测就带上），攒够再
一次性 LLM 归纳。** 不做成"每提交一条就调一次 LLM 重写人设"——既贵又加剧漂移。
calib_memory 有 3000 字上限，超了丢最老的：它每次评测都进 prompt。

**评测结果表冗余存 persona_version 是必需的**，没有它人设改过之后历史结果会被
误当成新人设的表现，"校准前 vs 校准后"永远说不清。同理 human_score（人工标注分）
是校准闭环的目标函数——没有它，"校准有没有效"就是玄学。

相关：[[b9-project-shape]]、[[definition-of-done-user-surface]]
