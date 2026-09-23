/**
 * 随手的全部「脑子」：认出贴进来的是什么 → 推荐拿去做什么 → 拼成一段 Prompt。
 *
 * 纯函数，不碰 DOM、不出网，单测直接跑（test/unit.mjs）。
 *
 * 取舍：识别只用规则，不调任何模型。她贴进来的东西可能是客户的邮件、
 * 群里的聊天记录 —— 在「拿去问 AI」那一下之前，它不该离开这台设备。
 * 认错了也不要紧：用途是一排按钮，点一下就换。
 */

export type Kind =
  | 'url' | 'error' | 'code' | 'table' | 'chat' | 'email' | 'message'
  | 'notes' | 'questions' | 'ask' | 'list' | 'article' | 'short' | 'text'

export type Intent =
  | 'answer' | 'summary' | 'points' | 'reply' | 'todo' | 'research'
  | 'critique' | 'explain' | 'rewrite' | 'translate' | 'brainstorm'

/** md = 通用（ChatGPT / 豆包 / Kimi / DeepSeek 都吃）；xml = Claude 最吃这一套 */
export type Target = 'md' | 'xml'

export type Lang = 'zh' | 'en' | 'mixed'

export interface Detected {
  kind: Kind
  /** 给人看的名字：「群聊记录」「一封邮件」 */
  label: string
  /** 补充一句：「14 条 · 3 人」「Python」「1,280 字」 */
  meta: string
  /** 推荐的用途，第一个就是默认 */
  picks: Intent[]
  lang: Lang
  /** 聊天：最后一个说话的人 */
  last?: string
  /** 聊天：里面有「我」 */
  hasMe?: boolean
  /** 问题清单：一共几个 */
  count?: number
}

// ---------------------------------------------------------------- 清理

/** 贴进来的东西常带着各种脏字符：Windows 换行、零宽空格、不换行空格、行尾空格 */
export function clean(s: string): string {
  return s
    .replace(/\r\n?/g, '\n')
    .replace(/[\u200B-\u200D\u2060\uFEFF]/g, '')
    .replace(/\u00A0/g, ' ')
    .replace(/[ \t]+$/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    // 只去掉开头的空行，不动第一行的缩进（代码的缩进是有意义的）
    .replace(/^(?:[ \t]*\n)+/, '')
    .replace(/\s+$/, '')
}

// ---------------------------------------------------------------- 语言

const CJK = /[\u3400-\u9fff\uf900-\ufaff]/g
const LATIN = /[A-Za-z]/g

export function langOf(s: string): Lang {
  const c = (s.match(CJK) ?? []).length
  const l = (s.match(LATIN) ?? []).length
  if (c + l === 0) return 'zh'
  // 一个英文单词好几个字母，一个汉字就是一个字。按 2:1 折算，
  // 否则「我们要做 GMV 增长」会因为 3 个字母被算成混合
  const zh = c / (c + l / 2)
  if (zh >= 0.5) return 'zh'
  if (zh <= 0.15) return 'en'
  return 'mixed'
}

/** 字数：中文按字，英文按词 —— 跟人数字数的方式一致 */
export function sizeOf(s: string): { n: number; unit: '字' | '词' } {
  if (langOf(s) === 'en') return { n: (s.match(/[A-Za-z0-9'’-]+/g) ?? []).length, unit: '词' }
  return { n: s.replace(/\s/g, '').length, unit: '字' }
}

const fmt = (n: number) => n.toLocaleString('en-US')

// ---------------------------------------------------------------- 识别

const URL_RE = /^https?:\/\/[^\s]+$/i

const ERROR_STRONG: RegExp[] = [
  /Traceback \(most recent call last\)/,
  /^\s*File ".+", line \d+/m,
  /\b[A-Z][A-Za-z]*(?:Error|Exception)\b(?::|\s+at\b|$)/m,
  /\bnpm ERR!/,
  /^panic: /m,
  /\bSegmentation fault\b/,
  /\bUncaught\b/,
  /Cannot read propert(?:y|ies) of (?:undefined|null)/,
  /\bis not (?:a function|defined)\b/,
]
const ERROR_WEAK: RegExp[] = [
  /^\s*(?:ERROR|FATAL|CRITICAL|E\d{4}|error(?:\[\w+\])?)[\s:[\]]/m,
  /\bexit(?:ed with)? (?:code|status) [1-9]\d*/i,
  /\b(?:4\d\d|5\d\d) (?:Bad Request|Unauthorized|Forbidden|Not Found|Internal Server Error|Bad Gateway|Service Unavailable|Gateway Timeout)\b/i,
  /\b(?:failed|failure)\b.*$/im,
  /报错|错误码|异常退出|崩溃了/,
]
/** Java / JS 的栈帧行 */
const STACK_LINE = /^\s*at\s+\S.*(?:\(.*:\d+(?::\d+)?\)|:\d+:\d+)\s*$/

const CODE_LINE = new RegExp([
  String.raw`[;{}]\s*$`,
  String.raw`^\s*(?:def|class|import|from\s+\S+\s+import|export|const|let|var|function|return|async|await|public|private|protected|package|func|fn|impl|struct|#include|using|namespace)\b`,
  String.raw`^\s*(?:if|for|while|switch|elif|else|try|catch|except)\b.*[:{(]\s*$`,
  String.raw`^\s*(?:SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|FROM|WHERE|GROUP BY|ORDER BY|JOIN|LEFT JOIN|WITH)\b`,
  String.raw`^\s*</?[a-z][\w-]*(?:\s[^>]*)?>`,
  String.raw`=>`,
  String.raw`^\s*(?:@\w+|#\s*\w+.*|//.*)$`,
].join('|'))

function codeLang(s: string): string {
  if (/^\s*[[{]/.test(s)) { try { JSON.parse(s); return 'JSON' } catch { /* 不是 JSON */ } }
  if (/^\s*(?:SELECT|INSERT|UPDATE|DELETE|CREATE|WITH)\b/im.test(s) && /\bFROM\b|\bTABLE\b|\bINTO\b/i.test(s)) return 'SQL'
  if (/^\s*(?:def |class \w+.*:|import \w+|from \S+ import)/m.test(s) && !/[;{}]\s*$/m.test(s)) return 'Python'
  if (/^\s*(?:package \w+|func \w+\()/m.test(s)) return 'Go'
  if (/^\s*(?:fn |impl |use \w+::|let mut )/m.test(s)) return 'Rust'
  if (/^\s*(?:public|private|protected)\s+(?:static\s+)?[\w<>[\]]+\s+\w+\s*\(/m.test(s)) return 'Java'
  if (/^\s*<(?:!doctype|html|div|template|span|section)\b/im.test(s)) return 'HTML'
  if (/^\s*[.#]?[\w-]+\s*\{[^}]*:[^}]*\}?/m.test(s) && /:\s*[^;]+;/.test(s) && !/\bfunction\b|=>/.test(s)) return 'CSS'
  if (/\b(?:interface|type)\s+\w+\s*[={<]|:\s*(?:string|number|boolean)\b/.test(s)) return 'TypeScript'
  if (/\b(?:const|let|function|=>|console\.)/.test(s)) return 'JavaScript'
  if (/^\s*(?:\$ |sudo |npm |pip |git |cd |ls |curl |docker |kubectl )/m.test(s)) return 'Shell'
  return ''
}

function errorLang(s: string): string {
  if (/Traceback \(most recent|File ".+\.py", line/.test(s)) return 'Python'
  if (/\bnpm ERR!/.test(s)) return 'npm'
  if (/\.(?:[jt]sx?|mjs|vue):\d+/.test(s) || /\bUncaught\b/.test(s)) return 'JavaScript'
  if (/\.java:\d+|\bat (?:java|org|com)\./.test(s)) return 'Java'
  if (/^panic: |\.go:\d+/m.test(s)) return 'Go'
  return codeLang(s)
}

/**
 * 看起来像「名字：内容」，其实是文档里的标签。
 * 会议纪要、需求文档里满是「背景：」「结论：」，不能被当成两个人在聊天
 */
const NOT_A_NAME = new Set((
  '问题 结论 注意 时间 地点 背景 目标 备注 原因 方案 结果 说明 主题 日期 会议 参会 参会人 与会 议题 议程 ' +
  '摘要 总结 待办 负责人 截止 状态 进展 风险 下一步 优先级 需求 描述 标题 链接 地址 电话 邮箱 价格 数量 金额 ' +
  '来源 作者 版本 步骤 示例 例如 比如 答 问 注 补充 附件 现状 影响 建议 决定 决策 输入 输出 预期 实际 ' +
  '收件人 发件人 抄送 发送时间 主送 ' +
  'q a note subject to from cc bcc date re fwd title summary todo owner status action example step ' +
  'question answer reason result goal background tips tip warning error http https input output expected actual ' +
  'pros cons update decision decisions agenda attendees'
).split(' '))

interface ChatScan { lines: number; speakers: Map<string, number>; last?: string }

function scanChat(lines: string[]): ChatScan {
  const speakers = new Map<string, number>()
  let n = 0
  let last: string | undefined
  // 「张三：好的」「[10:23] 张三: 好的」「2024-05-01 10:23 张三：好的」
  const inline = /^\s*(?:\[[^\]\n]{3,25}\]\s*|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?\s+|\d{1,2}:\d{2}(?::\d{2})?\s+)?([^\s:：\][]{1,16})\s*[:：]\s*\S/
  // 微信多选复制的格式：名字 + 时间 单独一行，内容在下一行
  const header = /^\s*([^\s:：]{1,16}?)\s+(?:\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?\s+)?(?:昨天\s+|星期.\s+)?\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp][Mm])?\s*$/
  for (const raw of lines) {
    const m = raw.match(header) ?? raw.match(inline)
    if (!m) continue
    const name = m[1].replace(/^[@＠]/, '')
    if (NOT_A_NAME.has(name.toLowerCase())) continue
    if (/^\d+$/.test(name) || /^https?$/i.test(name)) continue
    speakers.set(name, (speakers.get(name) ?? 0) + 1)
    last = name
    n++
  }
  return { lines: n, speakers, last }
}

const BULLET = /^\s*(?:[-*•·●○▪◦]\s+|\d{1,2}[.、)）]\s*|[（(]\d{1,2}[)）]\s*|[一二三四五六七八九十]{1,3}[、.．]\s*|\[[ xX]\]\s*)/
const TODO_WORDS = /待办|TODO|to-?do|跟进|负责|deadline|截止|DDL|本周|下周|明天|今天之内|前完成|action item|需要.{0,6}(?:完成|提交|确认|对齐|推进)|@\S+/i
const NOTES_WORDS = /会议纪要|会议记录|纪要|参会人?|与会|议程|议题|action items?|meeting notes|attendees|agenda|周会|例会|复盘会|同步会|1[:：]1/i
const QUESTION_LINE = /[?？]\s*$|^\s*(?:\d{1,2}[.、)）]\s*)?(?:怎么|如何|为什么|为啥|是否|能否|能不能|可不可以|有没有|哪些|哪个|什么是|what|how|why|when|where|which|who|should|can|is there|are there|do we|does)\b/i
const ASK_START = /^(?:请问|想问|怎么|如何|为什么|为啥|是否|能不能|能否|可以|可不可以|有没有|哪|什么|帮我|求|what|how|why|when|where|which|who|can|could|should|would|is|are|do|does)/i

export const KIND_LABEL: Record<Kind, string> = {
  url: '一个链接', error: '一段报错', code: '一段代码', table: '一张表',
  chat: '聊天记录', email: '一封邮件', message: '一条消息', notes: '会议纪要',
  questions: '一串问题', ask: '一个问题', list: '一份清单', article: '一篇长文',
  short: '一句话', text: '一段文字',
}

/** 放进句子里用的：「帮我总结下面这段聊天记录」—— 量词跟着种类走 */
const THIS: Record<Kind, string> = {
  url: '这个链接', error: '这段报错', code: '这段代码', table: '这张表',
  chat: '这段聊天记录', email: '这封邮件', message: '这条消息', notes: '这份会议纪要',
  questions: '这些问题', ask: '这个问题', list: '这份清单', article: '这篇文章',
  short: '这句话', text: '这段文字',
}

const PICKS: Record<Kind, Intent[]> = {
  url:       ['summary', 'research', 'critique', 'points'],
  error:     ['explain', 'answer', 'research'],
  code:      ['explain', 'critique', 'rewrite', 'answer'],
  table:     ['points', 'summary', 'critique', 'brainstorm'],
  chat:      ['summary', 'reply', 'todo', 'points'],
  email:     ['reply', 'summary', 'todo', 'translate'],
  message:   ['reply', 'summary', 'rewrite', 'translate'],
  notes:     ['todo', 'summary', 'points', 'critique'],
  questions: ['research', 'answer', 'brainstorm'],
  ask:       ['answer', 'research', 'brainstorm'],
  list:      ['points', 'todo', 'critique', 'brainstorm'],
  article:   ['summary', 'points', 'critique', 'research'],
  short:     ['rewrite', 'brainstorm', 'answer', 'translate'],
  text:      ['summary', 'points', 'rewrite', 'critique'],
}

function kindOf(s: string): { kind: Kind; meta: string; extra?: Partial<Detected> } {
  const lines = s.split('\n')
  const body = lines.filter((l) => l.trim())
  const nl = body.length
  const size = sizeOf(s)
  const sizeMeta = `${fmt(size.n)} ${size.unit}`

  // 链接：整段就是一个（或几个）网址
  if (nl > 0 && nl <= 5 && body.every((l) => URL_RE.test(l.trim()))) {
    if (nl > 1) return { kind: 'url', meta: `${nl} 个` }
    let host = ''
    try { host = new URL(body[0].trim()).hostname.replace(/^www\./, '') } catch { /* 坏链接也照样当链接 */ }
    return { kind: 'url', meta: host }
  }

  // 报错。放在代码前面：栈里满是像代码的行，但她要的是「排查」不是「讲解」
  const stack = lines.filter((l) => STACK_LINE.test(l)).length
  const strong = ERROR_STRONG.some((r) => r.test(s)) || stack >= 2
  const weak = ERROR_WEAK.filter((r) => r.test(s)).length
  if ((strong && (s.length < 8000 || stack >= 2)) || weak >= 2) {
    return { kind: 'error', meta: errorLang(s) }
  }

  // 表格：制表符分隔（从 Excel / 飞书表格复制出来就是这样）或 Markdown 表
  if (nl >= 3) {
    const tabs = body.map((l) => (l.match(/\t/g) ?? []).length)
    const mode = modeOf(tabs)
    if (mode >= 1 && tabs.filter((t) => t === mode).length / nl >= 0.7) {
      return { kind: 'table', meta: `${nl} 行 × ${mode + 1} 列` }
    }
    const pipes = body.filter((l) => /^\s*\|.*\|\s*$/.test(l))
    if (pipes.length >= 3 && pipes.some((l) => /^\s*\|[\s:|-]+\|\s*$/.test(l))) {
      const cols = pipes[0].split('|').length - 2
      return { kind: 'table', meta: `${pipes.length - 1} 行 × ${cols} 列` }
    }
    const commas = body.map((l) => (l.match(/,/g) ?? []).length)
    const cm = modeOf(commas)
    if (cm >= 2 && commas.filter((c) => c === cm).length / nl >= 0.8 && langOf(s) !== 'zh' && !/[.!?]\s/.test(s)) {
      return { kind: 'table', meta: `${nl} 行 × ${cm + 1} 列（CSV）` }
    }
  }

  // 代码
  if (/^\s*```/m.test(s) && /```\s*$/m.test(s)) return { kind: 'code', meta: codeLang(s.replace(/```\w*/g, '')) }
  if (/^\s*[[{]/.test(s) && codeLang(s) === 'JSON') return { kind: 'code', meta: 'JSON' }
  if (nl >= 2) {
    const lang = codeLang(s)
    const codey = body.filter((l) => CODE_LINE.test(l)).length
    const indented = body.filter((l) => /^(?: {2,}|\t)\S/.test(l)).length
    if ((codey / nl >= 0.35 && nl >= 3) || (codey / nl >= 0.5 && lang) || (lang && indented / nl >= 0.3 && codey >= 1)) {
      return { kind: 'code', meta: lang }
    }
  }

  // 邮件：带信头
  const heads = lines.filter((l) => /^\s*(?:From|To|Subject|Cc|Date|Sent|发件人|收件人|主题|抄送|发送时间|日期)\s*[:：]/i.test(l)).length
  if (heads >= 2) return { kind: 'email', meta: sizeMeta }

  // 聊天记录
  const chat = scanChat(lines)
  const who = chat.speakers.size
  const repeat = [...chat.speakers.values()].some((c) => c >= 2)
  if (chat.lines >= 3 && who >= 2 && repeat && chat.lines / nl >= 0.25) {
    const hasMe = [...chat.speakers.keys()].some((k) => /^(?:我|me|I)$/i.test(k))
    return { kind: 'chat', meta: `${chat.lines} 条 · ${who} 人`, extra: { last: chat.last, hasMe } }
  }

  // 会议纪要
  if (NOTES_WORDS.test(s) && nl >= 3) return { kind: 'notes', meta: sizeMeta }

  // 问题：一串，或者就一个
  const qs = body.filter((l) => QUESTION_LINE.test(l.trim())).length
  if (qs >= 2 && qs / nl >= 0.5) return { kind: 'questions', meta: `${qs} 个`, extra: { count: qs } }
  const t = s.trim()
  if (nl <= 4 && t.length <= 300 && (/[?？]\s*$/.test(t) || /吗\s*$/.test(t) || ASK_START.test(t))) {
    return { kind: 'ask', meta: '' }
  }

  // 清单
  const bullets = body.filter((l) => BULLET.test(l)).length
  if (bullets >= 3 && bullets / nl >= 0.5) {
    return { kind: 'list', meta: `${bullets} 条`, extra: TODO_WORDS.test(s) ? { picks: ['todo', 'points', 'critique', 'brainstorm'] } : undefined }
  }

  // 消息：有称呼或落款，不太长
  const head = body[0]?.trim() ?? ''
  const tail = body.slice(-3).join('\n')
  const greets = /^(?:hi|hello|hey|dear|你好|您好|哈喽|嗨|各位|亲爱的|[^\s，,]{1,8}(?:老师|总|哥|姐|同学)[，,:：\s])/i.test(head) || /^@\S+/.test(head)
  const signs = /(?:thanks|thank you|best|regards|cheers|谢谢|感谢|辛苦了?|多谢|盼复|期待(?:你|您)的回复)[\s,，!！.。~～]*$/im.test(tail)
  if ((greets || signs) && s.length <= 4000) return { kind: 'message', meta: sizeMeta }

  if ((size.unit === '字' && size.n >= 400) || (size.unit === '词' && size.n >= 150)) return { kind: 'article', meta: sizeMeta }
  if (nl === 1 && t.length <= 60) return { kind: 'short', meta: '' }
  return { kind: 'text', meta: sizeMeta }
}

function modeOf(xs: number[]): number {
  const c = new Map<number, number>()
  for (const x of xs) c.set(x, (c.get(x) ?? 0) + 1)
  let best = 0, bestN = 0
  for (const [x, n] of c) if (n > bestN || (n === bestN && x > best)) { best = x; bestN = n }
  return best
}

export function detect(input: string): Detected {
  const s = clean(input)
  const { kind, meta, extra } = kindOf(s)
  const lang = langOf(s)
  let picks = [...(extra?.picks ?? PICKS[kind])]
  // 整段是英文的邮件 / 文章，她多半想先看懂 —— 翻译提到第二个
  if (lang === 'en' && ['email', 'message', 'article', 'text', 'short', 'url'].includes(kind)) {
    picks = [picks[0], 'translate', ...picks.slice(1).filter((p) => p !== 'translate')]
  }
  return { kind, label: KIND_LABEL[kind], meta, picks, lang, ...extra }
}

// ---------------------------------------------------------------- 用途

export interface IntentInfo {
  id: Intent
  label: string
  /** 选中之后在下面说一句它会干什么 */
  hint: string
  /** 「补一句」的提示 */
  note: string
}

const INFO: Record<Intent, Omit<IntentInfo, 'id'>> = {
  answer:     { label: '回答', hint: '先给直接答案，再给理由；有歧义先说按哪种理解', note: '比如：我是新手 / 只要结论 / 我用的是 Mac' },
  summary:    { label: '总结', hint: '一句话结论 + 关键信息 + 跟我有什么关系', note: '比如：给老板看的，突出风险' },
  points:     { label: '提要点', hint: '5–8 条要点，数字原样保留，标出要拍板的', note: '比如：只要跟预算有关的' },
  reply:      { label: '帮我回', hint: '读懂对方要什么，给简短 / 周到两版回复', note: '比如：婉拒但留余地 / 语气热情点' },
  todo:       { label: '拆待办', hint: '谁、做什么、何时 —— 列成表，没说的标「未定」', note: '比如：只列我自己要做的' },
  research:   { label: '调研', hint: '逐条查清楚，分清事实和推断，不许编来源', note: '比如：重点看国内市场 / 2025 年以后的' },
  critique:   { label: '挑毛病', hint: '按严重程度列问题，每条给改法', note: '比如：站在投资人的角度' },
  explain:    { label: '讲明白', hint: '大白话讲清楚，术语逐个解释', note: '比如：我不懂技术' },
  rewrite:    { label: '改写', hint: '更清楚、更短、更有力，事实一个不改', note: '比如：更正式 / 发朋友圈用' },
  translate:  { label: '翻译', hint: '地道的译文，专有名词保留', note: '比如：给美国同事看的' },
  brainstorm: { label: '出主意', hint: '稳妥 / 大胆 / 反常识三组，挑两个最推荐的', note: '比如：预算只有 5 万' },
}

const ORDER: Intent[] = ['summary', 'reply', 'points', 'todo', 'answer', 'explain', 'research', 'critique', 'rewrite', 'translate', 'brainstorm']

/** 「回答」只对本身就是问题的东西有意义；对一篇文章点「回答」，AI 不知道要回答什么 */
const ANSWERABLE: Kind[] = ['ask', 'questions', 'short', 'error', 'code']

export function intentInfo(id: Intent, det?: Pick<Detected, 'kind'>): IntentInfo {
  const i = { id, ...INFO[id] }
  if (id === 'explain' && det?.kind === 'error') return { ...i, label: '排查', hint: '最可能的原因、怎么验证、怎么修', note: '比如：本地好好的，上线才报' }
  if (id === 'explain' && det?.kind === 'code') return { ...i, hint: '它干什么、按执行顺序讲、有什么坑', note: '比如：我只会一点 Python' }
  if (id === 'answer' && det?.kind === 'questions') return { ...i, hint: '逐个回答，先结论后理由' }
  return i
}

/** 这份材料能用的全部用途：推荐的在前，其余按固定顺序 */
export function intentsFor(det: Detected): IntentInfo[] {
  const rest = ORDER.filter((x) => !det.picks.includes(x) && (x !== 'answer' || ANSWERABLE.includes(det.kind)))
  return [...det.picks, ...rest].map((x) => intentInfo(x, det))
}

// ---------------------------------------------------------------- 拼 Prompt

interface Spec {
  role: string
  lead: string
  steps: string[]
  output: string[]
  rules: string[]
}

const GROUNDED = '只根据材料说话；材料里没有的，写「材料未提及」，不要自己补。'
const NO_FLUFF = '不要客套开场，直接给结果。'
const ZH_OUT = '用中文回答（专有名词、代码、数字保留原文）。'

function spec(intent: Intent, det: Detected, material: string, hasNote: boolean): Spec {
  const k = det.kind
  const T = THIS[k]
  const isUrl = k === 'url'
  const urlStep = isUrl ? ['先打开并读完这个链接；打不开就直接说「打不开」，不要根据网址猜内容。'] : []
  const toZh = det.lang === 'zh' ? [] : [ZH_OUT]

  switch (intent) {
    case 'summary': {
      const steps =
        k === 'chat' ? ['一句话说清：这段聊天在聊什么、最后落在哪。', '各方的立场和诉求（谁 → 要什么）。', '已经定下来的事，和还没解决的分歧。', '需要我接着做或回应的地方。']
        : k === 'email' || k === 'message' ? ['一句话说清：对方找我是为了什么。', '对方明确要的东西、时间点、数字。', '需要我做什么、什么时候之前。', '字面之外的意思（如果有）。']
        : k === 'notes' ? ['一句话：这次会定了什么。', '决定了的事。', '待办：谁、做什么、什么时候。', '悬而未决的问题。']
        : k === 'table' ? ['这张表在描述什么（每一行、每一列分别是什么）。', '最重要的 3 个发现：趋势、极值、异常，都带上具体的数。', '看这张表时容易误读的地方。']
        : k === 'code' ? ['一句话：这段代码是干什么的。', '主要流程，按执行顺序。', '输入、输出和副作用。']
        : k === 'error' ? ['一句话：出了什么问题。', '报错发生在哪一步、哪个文件或模块。', '关键的错误信息原文。']
        : [...urlStep, '一句话结论：它到底在说什么（40 字以内）。', '3–5 个核心观点，每个带上它的依据。', '关键的数字、人名、时间，原样保留。', '值得存疑、或者没说清楚的地方。']
      return {
        role: '一位擅长抓重点的编辑',
        lead: `帮我把下面${T}总结清楚。`,
        steps,
        output: ['第一行单独写「一句话结论」。', '然后按上面的顺序分点，每点一两句。', '总长度不超过原文的三分之一，最多 400 字。'],
        rules: [...(isUrl ? [] : [GROUNDED]), ...toZh, NO_FLUFF],
      }
    }

    case 'points':
      return {
        role: '一位做事干脆的分析师',
        lead: `从下面${T}里提炼要点。`,
        steps: k === 'table'
          ? ['列出 5–8 条从数据里能读出的结论，按重要性排序。', '每条都带上具体的数（引用表里的值），不要只说「增长明显」。', '指出异常值和可能的原因（标明是推测）。', '数据本身撑不起的结论，不要写。']
          : [...urlStep, '列出 5–8 条最重要的信息，按重要性排序。', '每条先写结论，再用「——」接一句依据（引用原文的关键词）。', '数字、日期、人名、专有名词原样保留，不要换算或意译。', '需要拍板的标【决策】，有风险的标【风险】。'],
        output: ['编号列表，每条一行，不超过 50 字。', '最后一行写「最值得关注的是第 N 条」，加一句理由。'],
        rules: [...(isUrl ? [] : [GROUNDED]), ...toZh, NO_FLUFF],
      }

    case 'reply': {
      const who = k === 'chat' && det.last && !/^(?:我|me|I)$/i.test(det.last) ? `（尤其是最后说话的「${det.last}」）` : ''
      return {
        role: '我的沟通助理，替我拟回复',
        lead: `帮我回复下面${T}。`,
        steps: [
          k === 'chat' ? `先读懂对方${who}真正要什么 —— 明说的和没明说的。` : '先读懂对方找我要什么 —— 明说的和没明说的。',
          '列出所有需要我回应的点，一个都别漏。',
          '再写回复。',
        ],
        output: [
          '第一行写「对方要的是：……」。',
          '然后给两个版本：【简短版】两三句，直接；【周到版】每个点都照顾到。',
          k === 'email' ? '邮件格式：称呼、正文、落款齐全。' : k === 'chat' ? '聊天的语气：口语、短句，像我平时说话。' : '语气贴合原来的渠道：聊天就口语，邮件就正式。',
          '用对方的语言回（原文是英文就回英文）。',
        ],
        rules: [
          ...(det.hasMe ? ['聊天记录里的「我」就是我本人，用我的口吻写。'] : []),
          '凡是需要我拍板的 —— 时间、价格、承诺、名字 —— 不要替我编，用【待定：……】占位。',
          NO_FLUFF,
        ],
      }
    }

    case 'todo':
      return {
        role: '一位靠谱的项目经理',
        lead: `把下面${T}里所有要做的事拆出来。`,
        steps: [
          '找出每一件需要有人去做的事，包括顺口提到的。',
          '每件写清：做什么（动词开头）、谁负责、什么时候之前、原文依据。',
          '没写负责人或时间的，标「未定」，不要猜。',
          '最后单列两组：「我要做的」和「等别人的」。',
        ],
        output: ['用表格：| 事项 | 负责人 | 截止 | 原文依据 |', '按截止时间排，「未定」的放最后。', '表格后面列出「开工前还要确认的问题」（没有就不写）。'],
        rules: [...(det.hasMe ? ['记录里的「我」就是我本人。'] : []), GROUNDED, ...toZh],
      }

    case 'research': {
      if (k === 'questions') {
        return {
          role: '一位严谨的研究员',
          lead: det.count ? `帮我逐条调研下面这 ${det.count} 个问题。` : '帮我逐条调研下面这些问题。',
          steps: [
            `逐条回答，保持我的顺序${det.count ? `，${det.count} 个一个都不要漏` : ''}。`,
            '每条先给结论（一两句），再给依据和来源。',
            '标出把握程度：高 / 中 / 低，并说一句为什么。',
            '答不了或信息不够的，直接写「不确定」，并说明要查什么才能确定。',
          ],
          output: ['每个问题一个小标题（带上原来的编号或原句）。', '最后加一节「总体结论」，3 句话以内。'],
          rules: RESEARCH_RULES,
        }
      }
      return {
        role: '一位严谨的研究员',
        lead: isUrl ? '帮我围绕这个链接的内容做一次调研。' : `帮我围绕下面${T}做一次深入调研。`,
        steps: [...urlStep, '背景：这件事的来龙去脉，一段话。', '事实核查：材料里的关键说法，哪些站得住、哪些存疑。', '相关的人或机构，和他们各自的立场、利益。', '不同的观点或反例。', '我接下来最该追问的 3 个问题。'],
        output: ['按上面几部分用小标题组织。', '结尾给一个「一句话判断」。'],
        rules: RESEARCH_RULES,
      }
    }

    case 'critique':
      return {
        role: '一位挑剔但有建设性的评审（想象成最难搞的那位老板）',
        lead: `帮我挑下面${T}的毛病。`,
        steps: k === 'code'
          ? ['bug 和边界情况（空值、并发、异常路径）。', '安全问题。', '可读性和命名。', '性能隐患（只说真会有影响的）。']
          : [...urlStep, '逻辑：推理有没有跳步，结论站不站得住。', '证据：哪些说法缺数据或来源。', '表达：哪里含糊、啰嗦、容易被误读。', '遗漏：没考虑到的风险，反方会怎么反驳。'],
        output: ['按严重程度排序，每条：问题 → 为什么是问题 → 怎么改（给出改后的写法）。', '最多 8 条，抓大放小。', '最后一行：「最该先改的一处是：……」'],
        rules: ['不要客套，不要先夸。', '只挑真问题，没问题的地方不用硬挑。', ...toZh],
      }

    case 'explain':
      if (k === 'error') {
        return {
          role: '一位经验丰富、擅长排查问题的工程师',
          lead: '帮我排查下面这个报错。',
          steps: ['用一句大白话说：这个报错在说什么。', '最可能的 3 个原因，按可能性从高到低排。', '每个原因给一个验证办法：具体的命令、要看的配置或日志位置。', '对应的修法，能给代码就给代码。'],
          output: ['先给结论：「最可能是……」。', '然后按原因分节。', '如果需要更多信息才能判断，最后列出要我补充什么（哪段代码、什么版本、什么环境）。'],
          rules: ['不要泛泛地说「检查一下配置」—— 说清楚查哪个、看什么。', ZH_OUT],
        }
      }
      if (k === 'code') {
        return {
          role: '一位耐心的资深工程师',
          lead: `帮我讲明白下面这段${det.meta ? ` ${det.meta} ` : ''}代码。`,
          steps: ['一句话：它是干什么的。', '按执行顺序分块讲：每块在做什么、为什么这么写。', '用到的不常见的语法或库，顺手解释。', '值得注意的坑，或者隐含的假设。'],
          output: ['先一句话总结，再分块讲。', '引用代码时只摘关键的几行。'],
          rules: [ZH_OUT, NO_FLUFF],
        }
      }
      return {
        role: '一位很会讲课的老师',
        lead: `帮我把下面${T}讲明白 —— 我是聪明的外行。`,
        steps: [...urlStep, '先用一句大白话说清楚它在讲什么。', '里面的术语和缩写，逐个用一句话解释。', '背景：为什么会有这件事、这个说法。', '举一个具体的例子或类比。', '它对我可能意味着什么。'],
        output: ['先一句话，再分点。', '别堆术语；非用不可的，第一次出现就解释。'],
        rules: [ZH_OUT, NO_FLUFF],
      }

    case 'rewrite':
      return {
        role: '一位文字功底很好的编辑',
        lead: `帮我改写下面${T}。`,
        steps: [
          '原意和所有事实、数字都保留，信息不增不减。',
          '改得更清楚、更短、更有力：删废话，换掉含糊的词，理顺先后顺序。',
          '语气专业、自然，像一个靠谱的人写的，不要 AI 腔。',
          ...(k === 'short' ? ['给 3 个不同风格的版本：稳妥 / 简洁 / 有力。'] : []),
        ],
        output: [k === 'short' ? '直接给 3 个版本，编号。' : '先给改好的完整版本。', '然后用 3 条以内说明主要改了什么、为什么。', '用原文的语言。'],
        rules: ['不要加原文没有的承诺或信息。', '不要用「赋能、抓手、闭环、打通」这类空词，除非原文就有。'],
      }

    case 'translate': {
      // 混着的：中文占到三成五以上，就当是中文要翻成英文
      const zhish = det.lang === 'zh' || (det.lang === 'mixed' && zhShare(material) >= 0.35)
      const to = zhish ? '英文' : '中文'
      return {
        role: '一位两种语言都地道的译者',
        lead: `把下面${T}翻译成${to}。`,
        steps: [
          '意思准确第一，其次读起来像母语的人写的，不要翻译腔。',
          '专有名词、产品名、人名、数字、代码保持原样；有通用译名的，第一次出现时写成「译名（原文）」。',
          '保留原来的段落、列表和格式。',
          // 只有往外发的才需要照顾对方的职场习惯；翻进来给自己看的，准确就行
          ...(zhish && (k === 'email' || k === 'message' || k === 'short') ? ['这是要发给人看的，语气要符合英文职场的习惯。'] : []),
        ],
        output: ['先给完整译文，前后不加任何说明。', '译文后空一行，写「译注」：最多 3 处值得我留意的用词选择（没有就不写）。'],
        rules: [],
      }
    }

    case 'brainstorm':
      return {
        role: '一位点子多、也懂落地的搭档',
        lead: `围绕下面${T}，帮我出主意。`,
        steps: ['先用一句话复述你理解的问题或目标（我看一眼就知道你理解得对不对）。', '给 10 个想法，分三组：稳妥的、大胆的、反常识的。', '每个想法一句话，加上为什么可能行。'],
        output: ['按三组分节，编号。', '最后挑出你最推荐的 2 个，说清楚第一步具体做什么。'],
        rules: ['不要正确的废话。', '可以用材料以外的知识。', ...toZh],
      }

    case 'answer':
      return {
        role: '一位懂行、说话直接的专家',
        lead: k === 'questions' ? '逐个回答下面这些问题。' : k === 'error' ? '帮我解决下面这个问题。' : k === 'code' ? (hasNote ? '关于下面这段代码，回答我在「我的补充」里的问题。' : '看看下面这段代码最可能在哪儿出问题，该怎么改。') : '回答下面这个问题。',
        steps: ['先给直接答案，一两句话。', '再给理由或步骤。', '问题有歧义的话，先说你按哪种理解来答。', '答案取决于我的具体情况的，告诉我需要补充什么。'],
        output: ['先结论，后展开。', '能用列表就不用大段文字。'],
        rules: [...toZh, NO_FLUFF],
      }
  }
}

const RESEARCH_RULES = [
  '分清三种东西：材料里说的、公认的事实、你的推断。',
  '不许编造数字、引语和出处；引用要写清是哪里的，找不到就说找不到。',
  '有时效性的信息，注明截至什么时候。',
  ZH_OUT,
]

function zhShare(s: string): number {
  const c = (s.match(CJK) ?? []).length
  const l = (s.match(LATIN) ?? []).length
  return c + l === 0 ? 1 : c / (c + l / 2)
}

/** 围栏要比材料里最长的一串反引号还长，否则材料里的代码块会把围栏提前关掉 */
export function fenceFor(material: string): string {
  const runs = material.match(/`+/g) ?? []
  const longest = runs.reduce((m, r) => Math.max(m, r.length), 0)
  return '`'.repeat(Math.max(3, longest + 1))
}

/** XML 标签名不能被材料本身关掉 */
function tagFor(material: string): string {
  for (const t of ['material', 'source', 'source_text', 'pasted_material']) {
    if (!material.includes(`</${t}`)) return t
  }
  return 'pasted_material_' + material.length
}

export interface BuildInput {
  material: string
  intent: Intent
  note?: string
  target: Target
  det?: Detected
}

export function build({ material: raw, intent, note = '', target, det: given }: BuildInput): string {
  const material = clean(raw)
  if (!material) return ''
  const det = given ?? detect(material)
  const sp = spec(intent, det, material, !!note.trim())
  const n = note.trim()
  const what = det.label + (det.meta ? ` · ${det.meta}` : '')
  const noteRule = n ? ['「我的补充」优先级最高，跟上面的要求冲突时，以它为准。'] : []
  const rules = [...sp.rules, ...noteRule]

  if (target === 'xml') {
    const tag = tagFor(material)
    const kindAttr = what.replace(/"/g, '')
    const parts = [
      `<${tag} type="${kindAttr}">\n${material}\n</${tag}>`,
      `<task>\n你是${sp.role}。${sp.lead}\n${numbered(sp.steps)}\n</task>`,
      n ? `<my_note>\n${n}\n</my_note>` : '',
      `<output_format>\n${bulleted(sp.output)}\n</output_format>`,
      rules.length ? `<rules>\n${bulleted(rules)}\n</rules>` : '',
    ]
    return parts.filter(Boolean).join('\n\n')
  }

  const f = fenceFor(material)
  const parts = [
    `你是${sp.role}。${sp.lead}`,
    `## 材料（${what}）\n${f}\n${material}\n${f}`,
    `## 要做的事\n${numbered(sp.steps)}`,
    n ? `## 我的补充\n${n}` : '',
    `## 输出要求\n${bulleted(sp.output)}`,
    rules.length ? `## 注意\n${bulleted(rules)}` : '',
  ]
  return parts.filter(Boolean).join('\n\n')
}

const numbered = (xs: string[]) => xs.map((x, i) => `${i + 1}. ${x}`).join('\n')
const bulleted = (xs: string[]) => xs.map((x) => `- ${x}`).join('\n')
