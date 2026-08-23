---
name: prefer-company-api-for-heavy-compute
description: 能用公司LiteLLM网关API省Claude算力的场景（尤其subagent/批量处理），优先用公司API而不是烧Claude token
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-28T13:51:04.781Z
---

只要某个场景可以改用公司的 LiteLLM 网关 API 来做（尤其是 subagent、批量/重复性
调用这类吃 Claude token 算力的任务），就优先用公司 API，减少 Claude 本身的
消耗——这是 2026-07-28 用户明确给的指示。

**Why**：公司申请到的网关 key 有独立额度（$1000，见 [[b9-litellm-gateway-blocked]]），
用它做批量/重复性计算不占用 Claude 的 token 预算；反过来，Claude 自己（这个
assistant 本身）适合做分析/评测/复核/成文这类需要判断力的工作，不该为了省
一次 OpenAI 调用而把这类任务外包出去。

**How to apply**：
- 需要 spawn subagent 做大量重复性/批处理工作时，先看这类工作能不能改成
  直接调公司 API（网关可达的场景下，如本机 Mac 挂了 VPN）来做，而不是默认
  开一堆 Claude subagent。
- 与 [[prefer-claude-over-openai-api]] 不矛盾，是同一个"省钱"原则在不同任务
  类型上的两个方向：分析/评测/复核/成文 → 用 Claude 自己做，不调外部 API；
  批量计算/重复性处理/吃 subagent 预算的任务 → 优先公司 API，不烧 Claude token。
  判断依据是任务类型（需要判断力 vs 纯计算量），不是简单的"能不能调"。
- 注意网关可达性限制：GCP VM 连不上网关（内网专用），只有挂公司 VPN 的机器
  （如 Lawrence 的 Mac）能用，见 [[b9-litellm-gateway-blocked]]。判断要不要
  走公司 API 之前先确认当前执行环境是否连得通。
