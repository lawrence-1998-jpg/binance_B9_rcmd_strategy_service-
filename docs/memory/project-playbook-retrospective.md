---
name: project-playbook-retrospective
description: B9项目复盘沉淀的跨项目playbook——所有新项目开工前参考，降本增效12条checklist
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-26T12:11:27.313Z
---

用户明确要求：B9 项目的复盘要作为**后面所有项目**的参考。完整文档在 B9 仓库
`docs/PROJECT_RETROSPECTIVE.md`（github.com/lawrence-1998-jpg/binance_B9_rcmd_strategy_service-），
含全部真实出处。核心 12 条（可直接执行的形态）：

1. 算钱先于省钱：先接应用层用量追踪、跑真实负载拿成本分解，再谈优化（B9 实测 82% 在 output token，砍对一刀省 36.5%）
2. 贵操作前放便宜漏斗，分级依据是任务歧义度、不是来源权威度
3. output token 通常是大头：长文本按重要性分档限长，砍无消费方的字段
4. 闲置资源（本地算力/订阅额度）用 pull+缓存+hash口径闸门+完整兜底接入，永不成为依赖项
5. 抓取/计算/交付各自独立定频，别让最贵环节绑架全链路
6. 阈值必须实测标定，文档数字只是初始猜测（B9: 文档 0.65 vs 实测 0.82）
7. 需求进 TODO 才算存在，不分长短；原始 prompt 原文留痕
8. 交付即验证：真实数据 + 关键数字 + UI 截图，拒绝"应该没问题"
9. schema 三件套同 commit：迁移 + 写入代码 + 重启依赖服务
10. 静默兜底必须配告警日志，否则故障以"数据是0"的形态潜伏（B9 的死锁让成本数据静默归零几天）
11. 多 agent 并行按文件边界切分、热点文件中央收口、SSH 等连接资源必须复用
12. 数据反直觉时先怀疑测量方法，尤其是好消息（91.9%→29.9% 的教训）
13. **贵模型审便宜模型的产出**：执行用便宜的、审查用最强的。实测一次强模型 review
    查出 4 个生产级 HIGH，其中 3 个出自当天便宜模型写的、且通过了功能测试的代码——
    跨模块复合因果错误只有强推理看得见，而这类错误最贵（静默、损数据）
14. 兜底声明必须**故障注入**验证，"代码里有 try/except"不构成证据
15. 审查结论必须**对抗验证**（prompt 写"设法推翻它"而非"确认一下"），并给 agent
    写明排除项（如"禁止提安全加固"），实测可让噪音归零
16. 按量计费的第三方**先实证计费维度**（条/请求/层级）再设计限流，闸门落在
    计费维度上——B9 的 X 事故：闸门在请求数、计费按条数，两天烧穿额度

**How to apply**: 新项目开工时把这 16 条过一遍；遇到成本/并行/阈值/需求管理
决策时引用对应条目。相关：[[task-tracking-discipline]]、[[short-requests-need-tracking]]、
[[b9-dedup-gap]]、[[parallel-agents-ssh-limit]]、[[b9-estimates-good-enough]]
