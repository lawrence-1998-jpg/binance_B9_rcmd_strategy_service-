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
  | 'local'     // 没开 Claude（没填 API Key），只做了本地整理
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
  /** 截图收进来的：压缩过的图（data URL）。能复制出去贴给别的 AI，开了 Claude 也拿它来读 */
  img?: string
}

/** 截图还没被 Claude 读出字时，raw 先放这个 */
export const IMG_PLACEHOLDER = '［截图］'

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
const DATE_RE = /(?:\d{4}\s?[-/.年]\s?\d{1,2}\s?[-/.月]\s?\d{1,2}\s?日?|\d{1,2}\s?月\s?\d{1,2}\s?[日号]|(?:今天|明天|后天|今晚|明早|明晚|下周[一二三四五六日天]|本周[一二三四五六日天]|周[一二三四五六日天]|星期[一二三四五六日天]))(?:\s*(?:上午|下午|晚上|中午|早上)?\s*\d{1,2}\s*(?:[:：]\s*\d{2}|点半?|点\s*\d{1,2}\s*分?))?|(?:上午|下午|晚上|中午|早上)\s*\d{1,2}\s*(?:[:：]\s*\d{2}|点半?)|\b\d{1,2}:\d{2}\b/g
/** 光一个「今天」「周五」、后面没跟钟点：只有在像是约时间、定期限的话里才算数 */
const BARE_DAY = /^(?:今天|明天|后天|今晚|明早|明晚|(?:下|本)?周.|星期.)$/
const SCHEDULING = /开会|会议|[的个场]会|约了?[时见吃聊]|见面|面试|截止|之前|前完成|到期|提交|交付|碰一下|聊一下|通电话|打电话|电话会|视频会|面谈|拜访|航班|高铁|接机|饭局|聚餐|见(?:[，。！!,.\s]|$)|deadline|due|call|meeting/i
const CODE_RE = /(?:验证码|校验码|动态码|code)[^\d]{0,6}(\d{4,8})/i
/** 「周五前」「月底之前」：截止时间 */
const DUE_RE = /(?:今天|明天|后天|今晚|(?:下|本)?周[一二三四五六日天]|星期[一二三四五六日天]|\d{1,2}月\d{1,2}[日号]|\d{1,2}[日号]|月底|月初|年底|下班)(?:之|以)?前/g
/** 只认明说了的地点：「地点还是国贸三期 B 座 1208」「地址：xx 路 88 号」 */
const PLACE_RE = /(?:地点|地址|位置)(?:还是|改为|改在|改到|定在|是|在)?\s*[:：]?\s*([^，。；;！!？?\n]{2,40})/
/** 让「我」去做的事：「记得带上…」「别忘了…」「麻烦…」 */
const TODO_CUE = /(?:记得|别忘了?|不要忘了?|务必|麻烦(?:你)?|请(?:你)?|帮我|需要|要去|得去|待办|TODO|to-?do)\s*[:：]?\s*/i
/** 「周五前把 PPT 发给王总」这种：有期限、有动作 */
const DUE_TASK = /(?:之|以)?前(?:要|得|需要)?(?:把|将)?.{0,24}?(?:发|交|提交|完成|给|做|准备|回复|确认|整理|写|改|订|约|联系|打电话|付|报|签|寄|填|传|预约)/
/** 清单的一行：「- [ ] 买牛奶」「1. xxx」「• xxx」 */
const LIST_LINE = /^\s*(?:[-*•·]\s*)?(?:\[( |x|X)\]|[-*•·]|\d{1,2}[.、)）])\s*(\S.*)$/
const IDEA_RE = /^(?:(?:今天|刚才|突然)?想到|想法|灵感|脑洞|idea)\s*[:：]\s*/i
const NOTE_HEAD = /纪要|笔记|总结|复盘|记录|要点|摘要/
/**
 * 聊天里复制出来的一句：「王总：…」「张经理：…」「Lily: …」。
 * 只认像人的：中文带称呼（总、经理、老师…），或者英文名。「报价：」「地点：」这种不算
 */
const SPEAKER = /^((?:[\u4e00-\u9fa5]{1,3}(?:总|哥|姐|老师|经理|总监|老板|同学|主任|医生|律师|师傅|组长|主管|助理))|(?:[A-Z][a-z]+(?: [A-Z][a-z]+)?))\s*[:：]\s*(?=\S)/
const NOT_NAME = /^(?:Note|Notes|Todo|Re|Fwd|Subject|From|To|Date|Link|Links|Tip|Tips|Update|Summary|Step|Http|Https|Warning|Error|Info|Debug|Question|Answer|Price|Total)$/
/** 「改到周五」：改之前的那个时间不算 */
const MOVED = /(?:挪|改|推|延|换|提前)到/

/** 本地整理时，「复制给 AI」开头那一句：按类型给一句能直接用的 */
export const LOCAL_ASK: Record<Kind, string> = {
  event: '帮我把这件事整理成日程（时间、地点、参加的人、要准备什么），缺的信息或可能的冲突提醒我，再起草一句确认的回复。',
  todo: '帮我把这些事排个优先级，估一下各要多久，给我一个今天就能照着做的顺序。',
  contact: '帮我把这个人整理成通讯录格式（姓名、公司职位、电话、邮箱），再起草一句得体的初次联系消息。',
  link: '帮我看看这个链接讲了什么：三句话概括要点，再告诉我值不值得细读。',
  data: '帮我把这些数字整理成一张表，算出总额和关键差异，指出需要注意或可以谈的地方。',
  code: '帮我看看这段代码 / 报错：哪里出了问题、最可能的原因、怎么修，给出改好的代码。',
  question: '帮我回答这个问题：先给结论，再说理由和需要注意的地方。',
  quote: '帮我解读这段话：核心观点是什么，对我有什么启发。',
  idea: '帮我把这个想法展开：成立的前提是什么、有哪些风险、下一步怎么最快验证。',
  note: '帮我提炼这段内容的要点（不超过 5 条），并列出需要我跟进的事。',
  other: '请帮我理解这条信息，提炼要点，并告诉我接下来该做什么。',
}

export interface Ask { label: string; text: string }

/** 卡片上「换个问法」：按类型多给几种，点一下连同这条信息一起复制 */
export const MORE_ASKS: Record<Kind, Ask[]> = {
  event: [
    { label: '起草确认回复', text: '帮我起草一条回复，确认时间和地点，语气简洁客气。' },
    { label: '要准备什么', text: '这件事我需要提前准备什么？列一个清单，按先后排好。' },
  ],
  todo: [
    { label: '拆成小步骤', text: '把这些事拆成马上就能开始做的小步骤。' },
    { label: '写进度同步', text: '帮我写一段简短的进度同步，说明这些事的安排和时间点。' },
  ],
  contact: [
    { label: '写初次联系', text: '帮我给这个人写一条初次联系的消息：礼貌、简短，说明来意。' },
    { label: '沟通前了解', text: '和这个人沟通前，我应该先了解哪些背景？列出要点和可以聊的话题。' },
  ],
  link: [
    { label: '讲了什么', text: '帮我读这个链接，用三句话告诉我讲了什么。' },
    { label: '提炼行动点', text: '帮我读这个链接，提炼出对我有用、可以马上照做的几点。' },
  ],
  data: [
    { label: '做成表格', text: '把这些数字整理成一张 Markdown 表格，算出合计。' },
    { label: '谈价话术', text: '帮我想三种谈价 / 谈条件的说法，理由要站得住。' },
  ],
  code: [
    { label: '说人话', text: '用大白话解释这段代码 / 报错在说什么。' },
    { label: '直接给修复', text: '直接给出修好的代码，并说明改了哪里、为什么。' },
  ],
  question: [
    { label: '列出正反', text: '把这个问题的几种答案和各自的理由列出来，最后给我建议。' },
  ],
  quote: [
    { label: '改写成我的话', text: '把这段话改写成我自己的说法，意思不变，更口语一点。' },
  ],
  idea: [
    { label: '挑毛病', text: '挑挑这个想法的毛病：最可能失败的三个原因，以及怎么避开。' },
  ],
  note: [
    { label: '改写得更清楚', text: '把这段内容改写得更清楚、更有条理，意思不变。' },
    { label: '列出待办', text: '从这段内容里列出需要我跟进的事，带上时间。' },
  ],
  other: [],
}
const COMMON_ASKS: Ask[] = [
  { label: '一句话总结', text: '用一句话告诉我这条信息最重要的是什么。' },
  { label: '翻译成英文', text: '把这条信息翻译成自然、得体的英文，保留所有数字、人名和链接。' },
]

/** 一张卡能换的问法：按类型的 + 通用的 + 她自己存的；跟卡上那句一样的不重复 */
export function asksFor(it: Item, mine: Ask[] = []): Ask[] {
  const seen = new Set([it.prompt])
  return [...MORE_ASKS[it.kind], ...COMMON_ASKS, ...mine].filter((a) => a.text && !seen.has(a.text) && seen.add(a.text))
}

/** 她自己存的问法：按钮上显示的名字从那句话里取 */
export function askLabel(text: string): string {
  return clip(text.trim().replace(/^(?:请你?|麻烦你?|帮我|帮忙)\s*/, '').replace(/^把(?:这条|它|这段)\s*/, ''), 8) || '我的问法'
}

/** 换个问法复制出去：跟「复制给 AI」一样的格式，只是开头那句换掉 */
export function asAiWith(it: Item, ask: string): string {
  return asAi({ ...it, prompt: ask })
}

function uniq(xs: string[]): string[] {
  const seen = new Set<string>()
  return xs.map((x) => x.trim()).filter((x) => x && !seen.has(x) && seen.add(x))
}

/** 从原文里找出要「我」去做的事 */
function findTodos(raw: string): { todos: Todo[]; list: boolean } {
  const lines = raw.split('\n')
  const listed = lines.map((l) => l.match(LIST_LINE)).filter((m): m is RegExpMatchArray => !!m && [...m[2]].length <= 60)
  // 打了勾框的，或者明说是清单 / 待办 / 要买的：每一行就是一件事
  const boxes = listed.some((m) => m[1] !== undefined)
  if (listed.length >= 2 && (boxes || /待办|to-?do|清单|要做|要买|任务/i.test(raw))) {
    return { todos: listed.slice(0, 8).map((m) => ({ text: clip(m[2], 40), done: /x/i.test(m[1] ?? '') })), list: true }
  }
  const out: string[] = []
  for (const line of raw.split(/[。！!；;\n]+/)) {
    const sent = line.match(LIST_LINE)?.[2] ?? line
    const cue = sent.match(TODO_CUE)
    if (cue && cue.index !== undefined) {
      const what = sent.slice(cue.index + cue[0].length).split(/[，,]/)[0].trim()
      if ([...what].length >= 2) out.push(clip(what, 40))
    } else if (DUE_TASK.test(sent) && [...sent.trim()].length <= 60) {
      // 「合同我明天发你，你周五前签好寄回来」：要做的是有期限的那一小句，不是整句
      // 那一小句太短（「月底前给初版」）就带上前一句（「Linda 负责数据看板」），不然看不出是什么事
      const parts = sent.replace(SPEAKER, '').split(/[，,]/)
      const i = Math.max(0, parts.findIndex((c) => DUE_TASK.test(c)))
      const part = [...parts[i].trim()].length < 8 && i > 0 ? `${parts[i - 1].trim()}，${parts[i].trim()}` : parts[i]
      out.push(clip(part.trim().replace(/^(?:你|您|我|咱们|我们)(?=\S)/, ''), 40))
    }
  }
  return { todos: uniq(out).slice(0, 5).map((text) => ({ text, done: false })), list: false }
}

export function quick(input: string): Pick<Item, 'kind' | 'title' | 'summary' | 'fields' | 'todos' | 'tags' | 'prompt'> {
  const raw = tidy(input)
  const urls = uniq(raw.match(URL_RE) ?? [])
  const emails = uniq(raw.match(EMAIL_RE) ?? [])
  const phones = uniq((raw.replace(URL_RE, ' ').match(PHONE_RE) ?? []).map((p) => p.trim()))
    .filter((p) => p.replace(/\D/g, '').length >= 7)
  const money = uniq(raw.replace(URL_RE, ' ').match(MONEY_RE) ?? [])
  const isCode = /^\s*(?:Traceback|at |Error|Exception|\w*Error:|npm ERR!)/m.test(raw) || /[;{}]\s*$/m.test(raw)
  // 报错里的「App.tsx:42:13」不是钟点
  const moved = raw.search(MOVED)
  const dates = isCode ? [] : uniq(raw.match(DATE_RE) ?? [])
    .filter((d) => !BARE_DAY.test(d) || SCHEDULING.test(raw))
    .filter((d) => moved < 0 || raw.indexOf(d) > moved || !raw.slice(moved).match(DATE_RE))
  const due = uniq(raw.match(DUE_RE) ?? [])
  const place = raw.match(PLACE_RE)?.[1]?.trim()
  const code = raw.match(CODE_RE)?.[1]
  const { todos, list } = code ? { todos: [], list: false } : findTodos(raw)
  const who = isCode ? undefined : raw.match(SPEAKER)?.[1]
  const speaker = who && !NOT_NAME.test(who) ? who : undefined

  const fields: Field[] = []
  if (code) fields.push({ label: '验证码', value: code })
  if (speaker) fields.push({ label: '来自', value: speaker })
  // 「有效期至 10 月 15 日」「截止 3 月 1 日」：是期限，不是约的时间
  const dueish = (d: string) => /(?:截止|有效期|到期|deadline|due)[^，。；\n]{0,4}$/i.test(raw.slice(0, raw.indexOf(d)))
  dates.slice(0, 2).forEach((d) => fields.push({ label: dueish(d) ? '截止' : '时间', value: d }))
  if (due[0] && !dates.some((d) => due[0].startsWith(d))) fields.push({ label: '截止', value: due[0] })
  if (place) fields.push({ label: '地点', value: place })
  phones.slice(0, 2).forEach((p) => fields.push({ label: '电话', value: p }))
  emails.slice(0, 2).forEach((e) => fields.push({ label: '邮箱', value: e }))
  money.slice(0, 2).forEach((m) => fields.push({ label: '金额', value: m }))
  urls.slice(0, 3).forEach((u) => fields.push({ label: '链接', value: u }))

  // 说话的人已经拎成「来自」了，标题和要点从他说的话开始
  const bare = raw.replace(URL_RE, '').replace(speaker ? SPEAKER : /$^/, '').trim()
  const kind: Kind =
    code ? 'data'
    : urls.length && bare.length < 30 ? 'link'
    : list ? 'todo'
    : dates.length && SCHEDULING.test(raw) ? 'event'
    : (phones.length || emails.length) && raw.length < 200 ? 'contact'
    : isCode ? 'code'
    : raw.includes('\n') && [...raw.split('\n')[0]].length <= 12 && NOTE_HEAD.test(raw.split('\n')[0]) ? 'note'
    : todos.length && !raw.includes('\n') && [...raw].length <= 60 ? 'todo'
    : /[?？]\s*$/.test(raw) && raw.length < 200 ? 'question'
    : IDEA_RE.test(raw) ? 'idea'
    : money.length ? 'data'
    : 'note'

  // 标题：第一行。太长就取第一句（6 到 18 个字的话）；只有一个链接时拿域名，比一串网址好认
  const lines = bare.split('\n').map((l) => l.trim()).filter(Boolean)
  const first = (lines[0] ?? '').replace(IDEA_RE, '').replace(/^[#>*\-\s•·]+/, '').replace(/[:：]$/, '').trim()
  const clause = [...first].length > 18 ? first.match(/^(.{6,18}?)[，。！？!?；]/)?.[1] : undefined
  const head =
    list && LIST_LINE.test(lines[0] ?? '') ? `${todos[0].text} 等 ${todos.length} 件`
    : clause ?? first
  const title = clip(head, 18) || (urls[0] ? hostOf(urls[0]) : clip(raw, 18) || '一条信息')

  // 要点：标题没说完的往下露一段，收起来的卡上也认得出是哪条。
  // 标题被截断的，从下一句（或下一个逗号后）开始，别从半个词开始
  const flat = (x: string) => x.replace(/\s+/g, ' ').trim()
  const body = flat(bare.replace(IDEA_RE, ''))
  let rest = ''
  if (!clause && [...head].length <= 18) rest = body.slice(flat(head).length)
  else {
    const cut = body.slice(clause ? flat(clause).length : [...title].length - 1)
    const next = cut.search(/[。！？!?；\n]/)
    rest = next >= 0 && cut.slice(next + 1).trim() ? cut.slice(next + 1) : cut.slice(Math.max(0, cut.search(/[，,]/)) + 1)
  }
  rest = rest.replace(/^[\s，。！？!?；;,.：:、|｜]+/, '')
  const summary = ['contact', 'link', 'data', 'code'].includes(kind) || list ? '' : clip(rest, 48)

  return {
    kind, title, summary,
    fields: fields.slice(0, MAX_FIELDS),
    todos,
    tags: [],
    prompt: code ? '' : LOCAL_ASK[kind],
  }
}

function hostOf(u: string): string {
  try { return new URL(u).hostname.replace(/^www\./, '') } catch { return u.slice(0, 18) }
}

/** 按「字」截断：一个汉字算一个，别把 emoji 劈成两半 */
export function clip(s: string, n: number): string {
  const cs = [...s.trim()]
  if (cs.length <= n) return cs.join('')
  // 别把「10」「Linda」这种劈成两半：往回退到词的边上（最多退 6 个）
  const w = /[A-Za-z0-9]/
  let k = n
  while (k > n - 6 && w.test(cs[k - 1]) && w.test(cs[k])) k--
  if (k === n - 6 && w.test(cs[k - 1])) k = n
  return cs.slice(0, k).join('').trimEnd() + '…'
}

// ---------------------------------------------------------------- 交给 Claude

const WEEK = '日一二三四五六'

export function today(now = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}（星期${WEEK[now.getDay()]}）`
}

export function aiPrompt(input: string, now = new Date(), image = false): string {
  const raw = tidy(input).slice(0, MAX_RAW_FOR_AI)
  const lead = image
    ? `你是一个信息整理助手。用户随手截了一张图（聊天截图、海报、名片、网页……），请先读图，再把它整理成一张结构化的信息卡片，方便他以后查找、以及直接复制去用。

第 0 步：把图里的文字按阅读顺序原样转写，放进 raw 字段，保留换行。聊天截图写成一行一条「名字：内容」；看不清的字用□代替，不要猜。图里没有字，就用一两句话描述图的内容。
`
    : `你是一个信息整理助手。用户随手复制了一段内容，请把它整理成一张结构化的信息卡片，方便他以后查找、以及直接复制去用。
`
  return `${lead}
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
${image
    ? '{"raw":"图里的文字……","kind":"event","title":"…","summary":"…","fields":[{"label":"时间","value":"…"}],"todos":["…"],"tags":["…"],"prompt":"…"}'
    : '{"kind":"event","title":"…","summary":"…","fields":[{"label":"时间","value":"…"}],"todos":["…"],"tags":["…"],"prompt":"…"}'}
${image ? '' : `
原文：
<<<
${raw}
>>>`}`.trimEnd()
}

const str = (x: unknown) => (typeof x === 'string' ? x.trim() : typeof x === 'number' ? String(x) : '')

/**
 * Claude 回来的东西逐项核一遍。它偶尔会：少字段、kind 写成中文、fields 写成对象、
 * 塞一堆「无」「未提及」进来。宁可少一格，不要一格假的。
 */
export function fromAi(x: unknown): (Pick<Item, 'kind' | 'title' | 'summary' | 'fields' | 'todos' | 'tags' | 'prompt'> & { raw?: string }) | null {
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
    // 只有读截图时 Claude 才回 raw（图里的字）；读文字时不许它改原文
    ...(str(o.raw) ? { raw: tidy(str(o.raw)).slice(0, 20_000) } : {}),
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
