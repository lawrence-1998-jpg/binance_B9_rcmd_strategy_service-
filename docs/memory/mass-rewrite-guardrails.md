---
name: mass-rewrite-guardrails
description: 全库批量改写的三护栏——默认预演+写前快照+差异门+互斥锁；以及UPDATE rowcount只计变更行、备份表collation必须与主表一致两个实测坑
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-30T08:57:47.317Z
---

2026-07-30 一天内把 6800+ 行的 importance_score 全库裸覆盖了 4 次（公式迭代），
用户明确画线："不能再犯把整个页面的库改乱、覆盖掉这种恐怖事件"。当天把
rescore 脚本改成带护栏版本，护栏自测又当场抓出 3 个 bug。

**三护栏（任何全库 UPDATE 类脚本的标配）**：
1. **默认预演**：裸跑只计算不写，打印"覆盖 N 行/数值变化 M 行/首屏 Top20
   换血 K 条"，看过再 `--apply`——和删除类脚本的 dry-run 约定统一。
2. **写前快照**：--apply 自动把要动的列备份进 backup 表（带批次号），
   `--restore <批次>` 一条命令整批还原。备份不是"以防万一"，是"敢改的前提"。
3. **互斥锁**：检测生产写者（pipeline lock）持有时拒绝跑——两个写者并发
   覆盖同批行，结果取决于毫秒时序，事后无法解释。

**Why**: 全库改写的恐怖之处在于错了也不报错——错的分仍是合法浮点数，页面
照常渲染。没有预演对比就没人知道改了什么，没有快照就没有退路。

**How to apply**: 写这类脚本先抄这套骨架再填业务逻辑。另两个实测坑：
① 备份表 CREATE 必须显式 COLLATE 与主表一致，否则 restore 的 JOIN 直接报
Illegal mix of collations；② 验证 restore 别看 UPDATE rowcount（只计"值有
变化"的行，值相同=0，看着像失败），要用"快照→改坏一行→还原→比对"实证。
最后防线：每日 mysqldump 保 7 天（周备份对"当天改乱"来不及）。
相关：[[backfill-three-traps]]、[[verify-formula-version-consistency]]
