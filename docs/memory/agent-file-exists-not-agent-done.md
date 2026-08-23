---
name: agent-file-exists-not-agent-done
description: "用\"文件是否存在\"当子agent完成信号会踩中中途写入态；只有task-notification才是权威完成信号，file mtime/existence都不是"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-30T19:17:14.975Z
---

2026-07-31 用 `until [ -f appendix_final.md ]; do sleep; done` 等一个后台 agent
写终稿，文件一出现就立刻读取校验、装入仓库、发给用户。几分钟后收到该 agent
的真正 task-notification，才发现磁盘文件从 463 行涨到了 561→734 行（生成器
展开后）——**agent 在我判定"完成"时其实还在写**，我读到的是中途状态，
发给用户的文件缺了整节判例集(D-1到D-11，D.1-D.3却在引用它们)。

**Why**：`Write` 工具是可分批调用的，agent 可能先写一版骨架再追加内容，也
可能因内部多轮 continue 分次落盘。"文件路径存在"只证明"至少写过一次"，
不证明"不会再写"。真正的完成信号只有一个：这个 agent/workflow 的
task-notification 到达。

**How to apply**：
1. 等异步 agent 产出时，**只信 task-notification，不用文件存在性做完成判据**。
   需要提前感知进度可以 poll，但"读取并对外分发"必须卡在收到通知之后。
2. 万一已经基于中途状态做了下游动作（装库/发送），收到姗姗来迟的通知后
   **重新 diff 磁盘当前内容 vs 已分发内容**，不一致立刻按新内容重做，
   不能假设"反正内容差不多"。
3. 这次能发现全靠用户把系统通知转发回来、其文字摘要与我之前验证的行数对
   不上——纯运气。以后主动做法：凡是"文件出现即用"的场景，读完后再补一次
   "等待 5-10 秒或下一次工具调用间隙重新 diff"的自查，或者干脆用
   `Monitor`/等待真正的完成通知而不是轮询文件存在。
相关：[[human-eyeball-test-is-my-floor]]、[[verify-metric-matches-claim]]
