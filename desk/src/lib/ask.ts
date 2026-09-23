import { KINDS, IMG_PLACEHOLDER, matches, today, type Item } from './card'

/**
 * 「问一问」：拿她自己收的东西回答她的问题 ——「Lily 的电话？」「这周有哪些会？」「那个报价多少钱？」
 *
 * Claude 每次调用什么都不记得，所以要把卡片塞进提示里。塞不下全部时，
 * 先塞跟问题沾边的（按搜索命中），再按新到旧补满。每张卡带一个编号，
 * 让 Claude 用 [编号] 标出处，页面再把编号变回可以点开的卡片。
 */

/** 提示最多 64 KiB（UTF-8），中文一个字 3 字节；留出指令和问题的余量 */
const BUDGET_BYTES = 48_000

const bytes = (s: string) => new TextEncoder().encode(s).length

function line(it: Item, n: number): string {
  const d = new Date(it.createdAt)
  const parts = [
    `[${n}] ${KINDS[it.kind]}｜${it.title}｜${d.getMonth() + 1}月${d.getDate()}日收`,
    it.summary && `要点：${it.summary}`,
    it.fields.length ? it.fields.map((f) => `${f.label}：${f.value}`).join('；') : '',
    it.todos.length ? `待办：${it.todos.map((t) => (t.done ? '（已做）' : '') + t.text).join('；')}` : '',
    it.raw && it.raw !== IMG_PLACEHOLDER ? `原文：${it.raw.replace(/\s+/g, ' ').slice(0, 240)}` : '',
  ]
  return parts.filter(Boolean).join('\n    ')
}

/** 挑出要塞给 Claude 的卡片（有序），和对应的编号表 */
export function pick(q: string, items: Item[]): Item[] {
  const words = q.replace(/[？?，。,.!！、]/g, ' ').split(/\s+/).filter((w) => w.length >= 1)
  const hit = items.filter((it) => words.some((w) => matches(it, w)))
  const rest = items.filter((it) => !hit.includes(it))
  const out: Item[] = []
  let used = 0
  for (const it of [...hit, ...rest]) {
    const b = bytes(line(it, out.length + 1)) + 1
    if (used + b > BUDGET_BYTES) break
    out.push(it)
    used += b
  }
  return out
}

export function askPrompt(q: string, chosen: Item[], now = new Date()): string {
  return `下面是我平时随手收进来的信息卡片（今天是 ${today(now)}）。请只根据这些卡片回答我的问题。

规则：
- 用中文，先给直接答案，再补必要的细节；能一两句说完就别展开。
- 每用到一张卡，就在那句话后面标上它的编号，写成 [3] 这样。
- 电话、金额、时间、地址、链接照卡片原样写出来，方便我直接复制。
- 卡片里找不到答案就直说「你收的东西里没有这个」，不要编，也不要用卡片以外的知识补。

卡片（共 ${chosen.length} 张）：
${chosen.map((it, i) => line(it, i + 1)).join('\n')}

我的问题：${q.trim()}`
}

export type Piece = { text: string } | { ref: number }

/** 把回答切成文字和 [编号]，编号超出范围的当普通文字 */
export function pieces(answer: string, n: number): Piece[] {
  const out: Piece[] = []
  const re = /\[(\d{1,3})\]/g
  let last = 0
  for (let m = re.exec(answer); m; m = re.exec(answer)) {
    const k = Number(m[1])
    if (k < 1 || k > n) continue
    if (m.index > last) out.push({ text: answer.slice(last, m.index) })
    out.push({ ref: k })
    last = m.index + m[0].length
  }
  if (last < answer.length) out.push({ text: answer.slice(last) })
  return out
}

/** 复制回答时，把 [3] 换成卡片标题，贴出去别人也看得懂 */
export function plainAnswer(answer: string, chosen: Item[]): string {
  return answer.replace(/\s*\[(\d{1,3})\]/g, (m, k) => {
    const it = chosen[Number(k) - 1]
    return it ? `（${it.title}）` : m
  })
}
