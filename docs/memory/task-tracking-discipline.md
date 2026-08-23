---
name: task-tracking-discipline
description: Lawrence 对任务跟踪、原始需求留痕、决策点记录、memory提取的四条通用工作要求
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-26T19:05:19.854Z
---

2026-07-26，Lawrence 提出四条通用工作原则（不限于当前项目，所有工作都要遵守）：

1. **所有提到过的任务都要落 TODO 表，详细检查，及时更新状态，保障不漏。**
   Why: 长会话里任务来自多轮对话、多个 agent 报告，容易散落漏项。
   How to apply: 用 TaskCreate/TaskUpdate 持续维护任务列表；每次用户提新需求或
   agent 报告发现新问题，立刻建任务；定期通读全部任务核对状态是否属实（不能
   只看自己记忆，要跟实际产出对照）。

2. **用户的原始 prompt，尤其是大段长文字的，要按原始情况写入一个文档保存，按时间倒序整理。**
   Why: 原始需求的完整措辞比事后转述更可靠，方便回溯"当时到底是怎么说的"。
   How to apply: 建一个 REQUIREMENTS_LOG 类文档，把用户发过的大段需求原文（不
   是我的转述/总结）逐条摘录，最新的放最前面（倒序）。

3. **需要讨论的点、权衡决策点、模糊不清的地方、优化建议——要努力思考后记录到
   一个文档里，提醒用户回头 review 和下判断。**
   Why: 执行过程中会遇到很多"我觉得该这样但不确定/需要用户拍板"的地方，不能
   自己悄悄定了就算，也不能一直打断用户。
   How to apply: 建一个 OPEN_QUESTIONS / DECISIONS 类文档，遇到这类点先自己
   认真思考给出倾向性判断，再记录下来（而不是只抛问题），供用户之后集中 review。

4. **一段时间后（比如 context window 占用很长了）要主动做 memory 提取**：踩坑
   点、关键注意点、待办、待 check 项、todolist 记录，避免遗忘。
   Why: 长会话上下文会被摘要/压缩，不主动提炼的细节会真的丢失。
   How to apply: 不用等用户提醒，感觉上下文已经很长、或者一个阶段性工作告一
   段落时，主动停下来做一次 memory 整理（存文件 + 更新 MEMORY.md 索引），
   同时刷新项目内的 TODO/决策文档。

**2026-07-27 复发实例**：一整轮会话（10 项工作：时区故障排查、信源统计新功能、
补齐设计稿差异、首屏改版等）全部只在对话和 git commit message 里交代，
`WORKLOG.md`/`REQUIREMENTS_LOG.md` 一次没碰，直到 Lawrence 主动问"文件都push了吗，
doc改好了吗"才发现落后了一整轮。事后他说"以后记得哦，不要再忘了"。

根因：把"写了详细的 git commit message"和"更新了跟踪文档"混为一谈了——
commit message 只有我看得到（或者要专门去翻 git log），WORKLOG/REQUIREMENTS_LOG
是给 Lawrence 看的项目状态入口，两者不能互相替代。

**收紧 How to apply**：不要等"一段时间后"这种模糊时机——**每次 git commit 之前**，
问自己一句"这次改动要不要在 WORKLOG.md 补一行、REQUIREMENTS_LOG.md 摘一段原始
prompt"。多个小改动可以攒到一次 commit 再一起补文档，但不能攒过一次 commit
还不补。换句话说：commit 和文档更新应该同频，而不是"阶段性"才做一次。

相关：[[b9-project-shape]]
