/**
 * 一条「拾」回来的信息长什么样，以及三件纯逻辑：
 *
 *   quick(raw)        —— 本地先认一遍：链接、电话、邮箱、金额、时间。贴进来立刻就有东西看，
 *                         Claude 还在想的那几秒不是一片空白；没有 Claude 时它就是全部。
 *   aiPrompt(raw)     —— 交给 Claude 的整理指令。
 *   fromAi(json)      —— Claude 回来的 JSON 不可全信：逐字段校验、截断、丢掉编出来的空值。
 *   asText / asAi     —— 复制出去的两种样子：给人看的「整理版」，给 AI 的「带指令版」。
 *
 * 全是纯函数，test/unit.mjs 直接跑。
 */

export type Kind =
  | 'todo' | 'event' | 'contact' | 'link' | 'note' | 'idea'
  | 'data' | 'quote' | 'question' | 'code' | 'other'

export const KINDS: Record<Kind, string> = {
  todo: '待办', event: '日程', contact: '联系人', link: '链接', note: '笔记', idea: '想法',
  data: '数据', quote: '摘录', question: '问题', code: '代码', other: '其他',
}

export interface Field { label: string; value: string }
export interface Todo { text: string; done: boolean }

export type Status =
  | 'pending'   // 刚收下，Claude 在整理
  | 'done'      // Claude 整理好了
  | 'local'     // 没有 Claude 可用，只做了本地整理
  | 'failed'    // Claude 这次没整理成，可以再试

export interface Item {
  id: string
  raw: string
  createdAt: number
  updatedAt: number
  status: Status
  kind: Kind
  title: string
  summary: string
  fields: Field[]
  todos: Todo[]
  tags: string[]
  /** 下一步最可能拿去问 AI 的那句指令 */
  prompt: string
  pinned: boolean
  /** 整理失败时给人看的一句话 */
  note?: string
}

export const MAX_FIELDS = 8
const MAX_RAW_FOR_AI = 12_000

export function newId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8)
}

/** 贴进来的东西常带着 Windows 换行、零宽空格、不换行空格、行尾空格 */
export function tidy(s: string): string {
  return s
    .replace(/\r\n?/g, '\n')
    .replace(/[\u200B-\u200D\u2060\uFEFF]/g, '')
    .replace(/\u00A0/g, ' ')
    .replace(/[ \t]+$/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

// ---------------------------------------------------------------- 本地先认一遍

const URL_RE = /https?:\/\/[^\s<>"'，。；、）)】]+/gi
const EMAIL_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g
// 大陆手机号、带区号的座机、+86 / 国际号码
const PHONE_RE = /(?:\+?\d{1,3}[ -]?)?(?:1[3-9]\d[ -]?\d{4}[ -]?\d{4}|0\d{2,3}[ -]?\d{7,8})(?!\d)/g
const MONEY_RE = /(?:[¥￥$€£]\s?\d[\d,]*(?:\.\d+)?\s?(?:万|亿|千|k|K|w|W)?|\d[\d,]*(?:\.\d+)?\s?(?:万元|亿元|元|块|万|美元|美金|USD|RMB|CNY|USDT))/g
const DATE_RE = /(?:\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?|\d{1,2}月\d{1,2}[日号]|(?:今天|明天|后天|今晚|明早|明晚|下周[一二三四五六日天]|本周[一二三四五六日天]|周[一二三四五六日天]|星期[一二三四五六日天]))(?:\s*(?:上午|下午|晚上|中午|早上)?\s*\d{1,2}\s*(?:[:：]\s*\d{2}|点半?|点\s*\d{1,2}\s*分?))?|(?:上午|下午|晚上|中午|早上)\s*\d{1,2}\s*(?:[:：]\s*\d{2}|点半?)|\b\d{1,2}:\d{2}\b/g
/** 光一个「今天」「周五」、后面没跟钟点：只有在像是约时间、定期限的话里才算数 */
const BARE_DAY = /^(?:今天|明天|后天|今晚|明早|明晚|(?:下|本)?周.|星期.)$/
const SCHEDULING = /开会|会议|[的个场]会|约了?[时见吃聊]|见面|面试|截止|之前|前完成|到期|提交|交付|碰一下|聊一下|deadline|due|call|meeting/i
const CODE_RE = /(?:验证码|校验码|动态码|code)[^\d]{0,6}(\d{4,8})/i

function uniq(xs: string[]): string[] {
  const seen = new Set<string>()
  return xs.map((x) => x.trim()).filter((x) => x && !seen.has(x) && seen.add(x))
}

export function quick(input: string): Pick<Item, 'kind' | 'title' | 'summary' | 'fields' | 'todos' | 'tags' | 'prompt'> {
  const raw = tidy(input)
  const urls = uniq(raw.match(URL_RE) ?? [])
  const emails = uniq(raw.match(EMAIL_RE) ?? [])
  const phones = uniq((raw.replace(URL_RE, ' ').match(PHONE_RE) ?? []).map((p) => p.trim()))
    .filter((p) => p.replace(/\D/g, '').length >= 7)
  const money = uniq(raw.replace(URL_RE, ' ').match(MONEY_RE) ?? [])
  const dates = uniq(raw.match(DATE_RE) ?? []).filter((d) => !BARE_DAY.test(d) || SCHEDULING.test(raw))
  const code = raw.match(CODE_RE)?.[1]

  const fields: Field[] = []
  if (code) fields.push({ label: '验证码', value: code })
  dates.slice(0, 2).forEach((d) => fields.push({ label: '时间', value: d }))
  phones.slice(0, 2).forEach((p) => fields.push({ label: '电话', value: p }))
  emails.slice(0, 2).forEach((e) => fields.push({ label: '邮箱', value: e }))
  money.slice(0, 2).forEach((m) => fields.push({ label: '金额', value: m }))
  urls.slice(0, 3).forEach((u) => fields.push({ label: '链接', value: u }))

  const bare = raw.replace(URL_RE, '').trim()
  const kind: Kind =
    code ? 'data'
    : urls.length && bare.length < 30 ? 'link'
    : dates.length && SCHEDULING.test(raw) ? 'event'
    : (phones.length || emails.length) && raw.length < 200 ? 'contact'
    : /^\s*(?:Traceback|at |Error|Exception|npm ERR!)/m.test(raw) || /[;{}]\s*$/m.test(raw) ? 'code'
    : /[?？]\s*$/.test(raw) && raw.length < 200 ? 'question'
    : money.length ? 'data'
    : 'note'

  // 只有一个链接的时候，拿域名当标题，比一串网址好认
  const first = bare.split('\n').find((l) => l.trim()) ?? ''
  const title = clip(first.replace(/^[#>*\-\s•·]+/, ''), 18) || (urls[0] ? hostOf(urls[0]) : clip(raw, 18) || '一条信息')
  return { kind, title, summary: '', fields: fields.slice(0, MAX_FIELDS), todos: [], tags: [], prompt: '' }
}

function hostOf(u: string): string {
  try { return new URL(u).hostname.replace(/^www\./, '') } catch { return u.slice(0, 18) }
}

/** 按「字」截断：一个汉字算一个，别把 emoji 劈成两半 */
export function clip(s: string, n: number): string {
  const cs = [...s.trim()]
  return cs.length <= n ? cs.join('') : cs.slice(0, n).join('') + '…'
}

// ---------------------------------------------------------------- 交给 Claude

const WEEK = '日一二三四五六'

export function today(now = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}（星期${WEEK[now.getDay()]}）`
}

export function aiPrompt(input: string, now = new Date()): string {
  const raw = tidy(input).slice(0, MAX_RAW_FOR_AI)
  return `你是一个信息整理助手。用户随手复制了一段内容，请把它整理成一张结构化的信息卡片，方便他以后查找、以及直接复制去用。

今天是 ${today(now)}。

规则：
1. 只根据原文，不编造原文没有的信息。数字、金额、电话、链接、人名、地名、代码一字不改。
2. 相对时间（明天、下周三、今晚八点）换算成具体日期，写成「9月25日（周四）15:00」这种格式；原文没说年份就不写年份。
3. kind 选一个最贴切的：todo 待办、event 日程或会议、contact 联系人或名片、link 链接或文章、note 笔记或纪要、idea 想法、data 数据或报价、quote 摘录、question 问题、code 代码或报错、other 其他。
4. title：12 个字以内，一眼能认出是哪条。summary：一句话讲清这条信息的要点，40 字以内。
5. fields：把关键信息拆成「标签 → 值」，最多 8 个。标签 2 到 4 个字（时间、地点、联系人、电话、金额、截止、链接、来源、账号……），值要能直接复制去用。没有就给空数组。
6. todos：原文里需要「我」去做的事，动词开头，最多 5 条；没有就给空数组。
7. tags：1 到 3 个简短的主题词。
8. prompt：想一想用户下一步最可能拿这条信息去问 AI 做什么（起草回复、排查报错、提炼要点、比较方案……），用「我」的口吻写一句能直接发给 AI 的指令，60 字以内。
9. 用中文写 title、summary、todos、tags、prompt；原文是外语时，fields 的值保留原文。

只回复一个 JSON 对象，不要任何别的文字：
{"kind":"event","title":"…","summary":"…","fields":[{"label":"时间","value":"…"}],"todos":["…"],"tags":["…"],"prompt":"…"}

原文：
<<<
${raw}
>>>`
}

const str = (x: unknown) => (typeof x === 'string' ? x.trim() : typeof x === 'number' ? String(x) : '')

/**
 * Claude 回来的东西逐项核一遍。它偶尔会：少字段、kind 写成中文、fields 写成对象、
 * 塞一堆「无」「未提及」进来。宁可少一格，不要一格假的。
 */
export function fromAi(x: unknown): Pick<Item, 'kind' | 'title' | 'summary' | 'fields' | 'todos' | 'tags' | 'prompt'> | null {
  if (!x || typeof x !== 'object' || Array.isArray(x)) return null
  const o = x as Record<string, unknown>
  const empty = /^(?:无|暂无|未提及|未知|不详|n\/?a|none|null|-|—)$/i

  let kind = str(o.kind).toLowerCase() as Kind
  if (!(kind in KINDS)) {
    const byName = (Object.keys(KINDS) as Kind[]).find((k) => KINDS[k] === str(o.kind))
    kind = byName ?? 'other'
  }

  let rawFields: unknown[] = []
  if (Array.isArray(o.fields)) rawFields = o.fields
  else if (o.fields && typeof o.fields === 'object') {
    rawFields = Object.entries(o.fields as Record<string, unknown>).map(([label, value]) => ({ label, value }))
  }
  const fields = rawFields
    .map((f) => {
      const r = (f ?? {}) as Record<string, unknown>
      return { label: clip(str(r.label ?? r.key ?? r.name), 8), value: str(r.value ?? r.val) }
    })
    .filter((f) => f.label && f.value && !empty.test(f.value))
    .slice(0, MAX_FIELDS)

  const list = (v: unknown, n: number, len: number) =>
    (Array.isArray(v) ? v : typeof v === 'string' && v ? [v] : [])
      .map((t) => clip(str(typeof t === 'object' && t ? (t as Record<string, unknown>).text : t), len))
      .filter((t) => t && !empty.test(t))
      .slice(0, n)

  const title = clip(str(o.title), 24)
  if (!title) return null
  return {
    kind,
    title,
    summary: clip(str(o.summary), 80),
    fields,
    todos: list(o.todos, 5, 60).map((text) => ({ text, done: false })),
    tags: list(o.tags, 3, 10).map((t) => t.replace(/^#/, '')),
    prompt: clip(str(o.prompt), 120),
  }
}

// ---------------------------------------------------------------- 复制出去的样子

/** 整理版：发给人、贴进备忘录、贴进日历都顺手的纯文本 */
export function asText(it: Item): string {
  const lines = [it.title]
  if (it.summary) lines.push(it.summary)
  if (it.fields.length) lines.push('', ...it.fields.map((f) => `${f.label}：${f.value}`))
  const open = it.todos.filter((t) => !t.done)
  if (open.length) lines.push('', '待办：', ...open.map((t) => `· ${t.text}`))
  return lines.join('\n')
}

/** 给 AI：一句指令 + 整理好的背景 + 原文。贴进任何一家 AI 都能直接用 */
export function asAi(it: Item): string {
  const ask = it.prompt || '请帮我理解这条信息，提炼要点，并告诉我接下来该做什么。'
  return `${ask}\n\n【整理好的信息】\n${asText(it)}\n\n【原文】\n"""\n${it.raw}\n"""`
}

/** 多条一起：给人看的合集 */
export function manyText(items: Item[]): string {
  return items.map((it, i) => `${i + 1}. ${asText(it).replace(/\n/g, '\n   ')}`).join('\n\n')
}

/** 多条一起喂给 AI */
export function manyAi(items: Item[]): string {
  const blocks = items.map((it, i) =>
    `## ${i + 1}. ${it.title}（${KINDS[it.kind]}）\n${asText(it).split('\n').slice(1).join('\n').trim() || '（见原文）'}\n原文：\n"""\n${it.raw}\n"""`)
  return `下面是我收集的 ${items.length} 条信息。请帮我：\n1. 按主题归类，每类一句话说清楚；\n2. 列出需要我跟进的事和时间点（有冲突就指出来）；\n3. 指出信息之间的矛盾或缺口。\n\n${blocks.join('\n\n')}`
}

export function matches(it: Item, q: string): boolean {
  const s = q.trim().toLowerCase()
  if (!s) return true
  const hay = [it.title, it.summary, it.raw, it.prompt, ...it.tags, ...it.fields.flatMap((f) => [f.label, f.value]), ...it.todos.map((t) => t.text)]
    .join('\n').toLowerCase()
  return s.split(/\s+/).every((w) => hay.includes(w))
}

// ---------------------------------------------------------------- 时间

export function dayGroup(ts: number, now = Date.now()): string {
  const d = new Date(ts), n = new Date(now)
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const diff = Math.round((start(n) - start(d)) / 86_400_000)
  if (diff <= 0) return '今天'
  if (diff === 1) return '昨天'
  if (diff < 7) return '这周早些时候'
  if (d.getFullYear() === n.getFullYear()) return `${d.getMonth() + 1} 月`
  return `${d.getFullYear()} 年 ${d.getMonth() + 1} 月`
}

export function stamp(ts: number, now = Date.now()): string {
  const d = new Date(ts)
  const hm = `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
  const g = dayGroup(ts, now)
  if (g === '今天') return now - ts < 60_000 ? '刚刚' : hm
  if (g === '昨天') return `昨天 ${hm}`
  return `${d.getMonth() + 1}/${d.getDate()}`
}
