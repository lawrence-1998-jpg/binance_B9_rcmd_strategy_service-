---
name: parallelize-when-possible
description: 用户明确要求——能并行的工作就并行做，节省时间，这是通用工作方式偏好不限于B9项目
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-26T06:23:26.628Z
---

用户原话："能并行作业的就并行。节省时间。"

**Why**: 用户对时间效率敏感（本项目里多次体现：整晚连续推进、要求后台 agent
并发跑、关心 pipeline 单轮耗时）。串行等待没有依赖关系的任务是明显的浪费。

**How to apply**: 遇到多个互相独立、不共享同一批文件/资源的任务时，默认开多个
后台 agent 或并行工具调用去做，而不是一个个排队做完再做下一个。唯一的例外是
会产生真实冲突的场景——多个 agent 并发写同一批热点文件（这个项目里踩过真实的
坑，见 [[parallel-agents-ssh-limit]] 和这次 index.html/eval_tools.py 的教训）：
这种情况下要么把工作合并进一个 agent 的任务范围里一次做完，要么把有冲突的部分
串行化，只让真正独立的部分并行，不能为了"并行"而制造并发写冲突。
