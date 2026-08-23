---
name: lab-prod-must-share-formula
description: 实验/调参工具必须与生产共用同一公式和同一取数轴，否则调参结论无效；每加一个排序因子要grep所有排序路径
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-30T06:04:11.253Z
---

2026-07-30 一天内两次踩同一类错：①给生产排序加了新鲜度衰减，策略实验室没同步
——同一套权重两个界面排名不同，实验室"调完即所见"的前提被破坏；②实验室按
入库时间取池、生产按事件日期过滤——两界面用不同时间轴取数，回填一来实验室
先崩。更早同型事故：情绪横幅的驱动因素全是韩股、排序却已美股优先（PRD-04
只修了排序层没修情绪层）。

**Why**: 排序公式的每个因子/取数口径其实有 N 个消费点（生产API、实验室
reweight、实验室compare、情绪聚合……）。改一处不改其余，产品的不同界面就
开始讲互相矛盾的故事——这类不一致不报错，只能靠人眼对比两个界面才能发现。

**How to apply**: 加/改任何排序因子或取数口径时，grep 所有调用点一次改齐
（B9 里是 api/server.py、api/lab_tools.py 的 rank_pool、crawler/market_mood.py）；
改完加一条 QA 断言钉住一致性（如"实验室池子必须含近24h事件"）。长期解法是
把公式收敛到单一模块，所有界面 import 同一份——配置化（strategy_config）
正是往这个方向走的第一步。
相关：[[human-eyeball-test-is-my-floor]]、[[backfill-three-traps]]
