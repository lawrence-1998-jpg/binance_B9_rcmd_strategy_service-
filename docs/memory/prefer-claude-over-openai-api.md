---
name: prefer-claude-over-openai-api
description: 能用本机/会话内 Claude 直接完成的工作，一律不调用 OpenAI API——降本优先的标准工作方式
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-26T19:37:23.159Z
---

2026-07-27，Lawrence 明确要求："后续所有的工作只要能用本地 claude 完成的，就坚决不用
openai 的 api 来保障降本。"

**Why**：这条是在一次真实评测任务后提出的——那次任务本可以用 OpenAI 模型做全部的匹配
判断、分级复核和报告撰写，但改为只在"生成 82 条标题的 embedding"这类无法绕开的步骤上
用一次 OpenAI API，其余的相似度判断、假阳性剔除、案例复核、成文全部由 Claude 直接完成。
用户对这个做法明确认可，并要求把它变成以后所有任务的默认方式，不是这一次的特例。

**How to apply**：
- 任何分析、评估、判断、写作、复核类工作，默认让 Claude（我自己）直接做，不要因为
  "调 GPT 更省事/更快"就调用 OpenAI API。
- 只有在技术上必须用 OpenAI 的具体环节（比如 embedding 向量生成——因为 B9 项目已有的
  存量数据全部是 OpenAI text-embedding-3-small 生成的，要对比就必须用同一模型/维度，
  换成别的 embedding 模型向量空间不兼容）才调用 OpenAI，且要在交付时明确报告"这一步
  为什么必须用 OpenAI、其余步骤为什么没有再调用"，让降本的取舍对用户可见。
  [[b9-x-api-capacity]] 记录过 B9 主 pipeline 结构化抽取本身已经在往本地 Claude 迁移
  （[[b9-enrich-bridge]]），这条是把同样的降本原则扩展到"我自己（Claude Code）临时做
  的分析/评测/报告类任务"上，不限于 B9 主 pipeline。
- 不要仅因为"这是我平时的做法"就默认调用外部模型 API 来完成本可以自己做的判断工作——
  这条与 [[b9-estimates-good-enough]]（估算类工作不用太较真）是互补的两条降本原则：
  一条管"精度要求"，这条管"该不该额外花钱调用别的模型"。

相关：[[b9-enrich-bridge]]、[[b9-x-api-capacity]]、[[b9-estimates-good-enough]]
