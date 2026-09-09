/**
 * 这东西到底在帮你，还是在收你的税。
 *
 * 让个人工作台死掉的头号原因是维护成本，业内的经验阈值是**每周维护超过
 * 30 分钟这个系统就太重了**。而案头到现在为止，对这个阈值**没有任何数据
 * 可以对照** —— 我在建议里写「先量出来」而不是「照这个数去优化」，
 * 就是因为那个 30 分钟本身也只是一位从业者的判断，没有原始研究。
 *
 * 所以这里只做一件事：把「你这周实际动了多少」摆出来。不打分、不催、
 * 不画曲线、不设目标。判断留给你。
 *
 * ## 为什么不记「打开了多少次」
 *
 * 调研报告里我原本写的是「这周你打开了 11 次，动了 4 天」。实现的时候
 * 改了主意，理由有两条：
 *
 * ① 打开次数要**新加一个计数器，每次开 App 都写一次存储** —— 而这个
 *    App 从头到尾的取舍就是「能推出来的就不要存」。
 * ② 它衡量的东西还很差：点开看一眼就退，跟坐下来记半小时数据，
 *    都算「一次」。
 *
 * 下面这些**一个字节都不用新存**，全从已有的时间戳推：8 个集合带
 * createdAt/updatedAt，focus / tasks / entries 本来就按日期存。
 * 而且它衡量的是真投入，不是开关次数。
 */

import type { State } from './types'
import * as D from './date'

export interface Upkeep {
  /** 这几天里，有动作的那几天（按你本地时区的自然日算） */
  days: number
  /** 这几天里新添的条目数 */
  added: number
  /** 统计跨度 */
  window: number
}

export function upkeep(s: State, window = 7, now = Date.now()): Upkeep {
  // 全部先换算成「哪一天」，再按天比。
  //
  // 第一版是时间戳按毫秒比、日期字段按字符串比 —— 两套规则，
  // 而且 `now - 7天` 到今天**含头含尾是 8 个日历天**，
  // 于是真的印出过「这 7 天你动了 8 天」。截图才看见的。
  // 现在窗口就是「含今天在内的最近 window 天」，只有一套规则。
  const floor = D.key(new Date(now - (window - 1) * 86400000))
  const ceil = D.key(new Date(now))
  const inWindow = (day: string) => day >= floor && day <= ceil
  const created: number[] = []
  const touched: number[] = []

  for (const n of s.notes) created.push(n.createdAt)
  for (const w of s.wishes) created.push(w.createdAt)
  for (const p of s.photos) created.push(p.createdAt)
  for (const m of s.moments) created.push(m.createdAt)
  for (const p of s.myPrompts) created.push(p.createdAt)
  for (const q of s.inquiries) { created.push(q.createdAt); touched.push(q.updatedAt) }
  for (const e of s.engagements) touched.push(e.updatedAt)
  for (const e of s.entries) touched.push(e.updatedAt)

  // 按日期存的那几样：日期本身就是「那天动过」的证据
  const dated = new Set<string>()
  for (const [date, v] of Object.entries(s.focus)) if (v.trim()) dated.add(date)
  for (const t of s.tasks) dated.add(t.date)
  for (const e of s.entries) dated.add(e.date)

  const days = new Set<string>()
  for (const t of [...created, ...touched]) {
    const day = D.key(new Date(t))
    if (inWindow(day)) days.add(day)
  }
  for (const d of dated) if (inWindow(d)) days.add(d)

  return {
    // 兜底：报出来的天数永远不该超过窗口。真超了说明上面某处又算错了，
    // 与其印一个「7 天里动了 8 天」这种一眼假的数，不如夹住
    days: Math.min(days.size, window),
    added: created.filter((t) => inWindow(D.key(new Date(t)))).length,
    window,
  }
}

/**
 * 一句话。
 *
 * 措辞上有意避开「才」「只」「已经」这类带评判的字 —— 报出来的是事实，
 * 不是成绩。她自己会判断这个数值不值。
 */
export function upkeepLine(u: Upkeep): string {
  if (u.days === 0 && u.added === 0) return `这 ${u.window} 天你没在这儿留下什么`
  const bits = [`这 ${u.window} 天你动了 ${u.days} 天`]
  if (u.added > 0) bits.push(`新添了 ${u.added} 条`)
  return bits.join('，')
}
