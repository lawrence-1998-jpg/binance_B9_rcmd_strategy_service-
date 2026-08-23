---
name: verify-write-not-just-return-code
description: "给表加列后必须做写入-读回往返验证：INSERT 占位符与列数不匹配会让写库全部失败却只打 warning，表现是'本轮没新数据'而不是报错"
metadata:
  type: feedback
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
---

2026-08-02 B9 给 news_events 加 `price_move` 列。改了三处：列名清单、
`ON DUPLICATE KEY UPDATE` 子句、参数元组——**唯独忘了在 VALUES 的占位符串里
补一个 `%s`**，41 个占位符对 42 列。

后果不是报错，是 `MySQL: wrote/updated 0/4 events`：`write_events` 把异常
catch 住只打了一行 warning、返回 0。日志上看就像"这一轮没有新事件"，
而那恰好是成本闸关闭期间的常见正常状态——**两种情况长得一模一样**。
是我盯着 `0/4` 这个比值觉得不对才查出来的。

**Why**：加列这个动作要同时改 4 个地方（列名/占位符/参数/更新子句），
少改任何一处都不会在语法检查、import、单测里暴露，只在**真实写库那一刻**
失败；而写库路径普遍有 try/except 保护（为了单行坏数据不搞垮整批），
于是失败被降级成一行 warning。

**How to apply**：
1. 加列后**必须做一次写入-读回往返**（构造一行、写、读出来比对内容、删掉），
   不能只看函数返回值或"跑通了没报错"。
2. 跑真实一轮时**盯 `wrote/updated X/Y` 的比值**，X<Y 就是有行写失败了。
   这个数字是这类故障唯一的可见信号。
3. 加列还会打破按 `SELECT *` 复制的备份脚本（见 [[schema-drift-breaks-star-select]]），
   一次加列要顺手跑一遍周边脚本。
相关：[[definition-of-done-user-surface]]、[[verify-metric-matches-claim]]
