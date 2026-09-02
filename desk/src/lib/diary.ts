import * as D from './date'
import { DOMAINS, type Domain, type State } from './types'

/**
 * 自动日记：从当天真实发生的事拼出三句草稿，你再改。
 *
 * 不调模型 —— 一是离线要能用，二是这三句话的价值在「准确」，
 * 而不是「文采」。写错比写得平淡糟糕得多。
 */
export function autoDraft(s: State, date: string): [string, string, string] {
  const tasks = s.tasks.filter((t) => t.date === date)
  const done = tasks.filter((t) => t.done)
  const notes = s.notes.filter((n) => D.key(new Date(n.createdAt)) === date)
  const moments = s.moments.filter((m) => D.key(new Date(m.createdAt)) === date)
  const photos = s.photos.filter((p) => p.date === date)

  // 第一句：干了什么
  let l1: string
  if (done.length === 0) {
    l1 = tasks.length ? `列了 ${tasks.length} 件，一件也没勾掉。` : '今天没列事。'
  } else {
    const names = done.map((t) => t.title)
    const head = names.slice(0, 2).join('、')
    l1 = names.length > 2 ? `做完了${head}，还有 ${names.length - 2} 件。` : `做完了${head}。`
  }

  // 第二句：这一天的分布 / 记了什么
  const byDomain = (['consult', 'byte', 'us', 'me'] as Domain[])
    .map((d) => ({ d, n: done.filter((t) => t.domain === d).length }))
    .filter((x) => x.n > 0)
    .sort((a, b) => b.n - a.n)
  let l2: string
  if (byDomain.length >= 2) {
    l2 = `力气主要花在${DOMAINS[byDomain[0].d].label}，也顾上了${DOMAINS[byDomain[1].d].label}。`
  } else if (byDomain.length === 1) {
    l2 = `一整天都在${DOMAINS[byDomain[0].d].label}上。`
  } else if (notes.length) {
    l2 = `没推动什么，但记了 ${notes.length} 条想法。`
  } else {
    l2 = ''
  }
  const extras: string[] = []
  if (moments.length) extras.push(`跟他说了${moments.length > 1 ? ` ${moments.length} 句` : '一句'}话`)
  if (photos.length) extras.push(`存了 ${photos.length} 张照片`)
  if (extras.length) l2 = (l2 ? l2 + ' ' : '') + extras.join('，') + '。'

  // 第三句：明天
  const t = D.parse(date)
  const tomorrow = D.key(new Date(t.getFullYear(), t.getMonth(), t.getDate() + 1))
  const next = s.tasks.filter((t) => t.date === tomorrow && !t.done)
  const l3 = next.length ? `明天先做「${next[0].title}」。` : '明天还没定。'

  return [l1, l2, l3]
}

export function isBlank(lines: string[]): boolean {
  return lines.every((l) => !l.trim())
}
