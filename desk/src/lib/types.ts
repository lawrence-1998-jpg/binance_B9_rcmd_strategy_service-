/** 四条人生线。领域色只用于标识条 / 小圆点 / chip，不做卡片底色。 */
export type Domain = 'consult' | 'byte' | 'us' | 'me'

export type Status = 'ok' | 'warn' | 'bad'

export interface DomainMeta {
  key: Domain
  label: string
  short: string
  color: string
  tint: string
  deep: string
}

export const DOMAINS: Record<Domain, DomainMeta> = {
  consult: { key: 'consult', label: '咨询顾问', short: '咨询', color: 'var(--consult)', tint: 'var(--consult-tint)', deep: 'var(--consult-deep)' },
  byte:    { key: 'byte',    label: '字节产品', short: '字节', color: 'var(--byte)',    tint: 'var(--byte-tint)',    deep: 'var(--byte-deep)' },
  us:      { key: 'us',      label: '我们俩',   short: '我们', color: 'var(--us)',      tint: 'var(--us-tint)',      deep: 'var(--us-deep)' },
  me:      { key: 'me',      label: '我自己',   short: '自己', color: 'var(--me)',      tint: 'var(--me-tint)',      deep: 'var(--me-deep)' },
}

export interface Task {
  id: string
  title: string
  domain: Domain
  est?: number          // 预估分钟
  done: boolean
  date: string          // YYYY-MM-DD
  note?: string
}

export type NoteKind = 'idea' | 'todo' | 'lesson' | 'us' | 'prompt'

export const NOTE_KINDS: { key: NoteKind; label: string; mark: string }[] = [
  { key: 'idea',   label: '想法',   mark: '◇' },
  { key: 'todo',   label: '待办',   mark: '✓' },
  { key: 'lesson', label: '教训',   mark: '⚑' },
  { key: 'us',     label: '给老公', mark: '♡' },
  { key: 'prompt', label: '素材',   mark: '⌘' },
]

export interface Note {
  id: string
  text: string
  kind: NoteKind | null   // null = 还没归类，这是刻意允许的：捕捉与整理分离
  createdAt: number
  handled: boolean
}

/** 一件正在推进的事：咨询是客户项目，字节是需求。 */
export interface Engagement {
  id: string
  name: string
  domain: 'consult' | 'byte'
  client?: string        // 咨询：客户名；字节：所属方向
  stage: string          // 当前阶段
  blocker: string        // 卡在哪 —— 这是手机上真正想看的东西，空字符串表示不卡
  status: Status
  progress: number       // 0–100
  next: string           // 下一个动作
  nextDate?: string      // YYYY-MM-DD
  updatedAt: number
  archived?: boolean
}

/**
 * 一条调研线 —— 这套东西的核心对象。
 *
 * 之前 engagement 只有状态（阶段、卡点、手填的百分比），没有内容：
 * 「提纲 → Prompt」生成完把 prompt 扔进剪贴板就消失了，
 * 研究结果没有地方回来，进度是拍脑袋填的。四个格子各装各的，中间没有线。
 *
 * 一条 inquiry 就是流水线上的一件在制品，四站往下走，每站的产出留在原地：
 *
 *   ① question   提纲里的一条问题
 *   ② prompt     照四条硬约束生成，存下来（不再只丢剪贴板）
 *   ③ findings   AI 给的结果，原样贴回来
 *   ④ conclusion 你自己提炼的一句话 —— 只有这句是你的，前面都是材料
 *
 * 状态由内容推导，不手填：填到哪一步就是哪一步。
 * engagement 的进度 = 有结论的条数 / 总条数，这个数才是真的。
 */
export interface Inquiry {
  id: string
  engagementId: string
  question: string
  prompt?: string
  findings?: string
  conclusion?: string
  createdAt: number
  updatedAt: number
}

/** 一条调研线走到哪儿了。顺序即流水线顺序。 */
export type Stage = 'ask' | 'prompted' | 'found' | 'concluded'

export const STAGES: { key: Stage; label: string; short: string }[] = [
  { key: 'ask',       label: '待查',      short: '问' },
  { key: 'prompted',  label: 'Prompt 已备', short: '备' },
  { key: 'found',     label: '有材料',    short: '料' },
  { key: 'concluded', label: '有结论',    short: '结' },
]

export function stageOf(q: Inquiry): Stage {
  if (q.conclusion?.trim()) return 'concluded'
  if (q.findings?.trim()) return 'found'
  if (q.prompt?.trim()) return 'prompted'
  return 'ask'
}

export interface Meeting {
  id: string
  title: string
  date: string           // YYYY-MM-DD
  start: string          // HH:MM
  end?: string
  domain: Domain
  note?: string
}

export interface Anniversary {
  id: string
  label: string
  date: string           // YYYY-MM-DD（起始日）
  recurring: boolean     // true = 每年过；false = 一次性倒数
  countUp?: boolean      // true = 数「已经多少天」而不是倒数
}

export interface Wish {
  id: string
  text: string
  who: 'him' | 'me' | 'both'
  done: boolean
  createdAt: number
}

export interface TripTodo {
  id: string
  text: string
  kind: 'book' | 'plan' | 'pack'
  owner: 'me' | 'him' | 'both'
  done: boolean
}

export interface TripDay {
  id: string
  date: string           // YYYY-MM-DD
  title: string
  detail: string
}

export interface Trip {
  title: string
  start: string
  end: string
  budget: number
  days: TripDay[]
  todos: TripTodo[]
}

export interface DayLog {
  date: string
  text: string
  doneCount: number
}

/** 提纲 → Prompt 工具的草稿，存下来免得每次重打 */
export interface PromptDraft {
  outline: string
  subject: string
  context: string
  target: 'tooled' | 'plain'
  depth: 'quick' | 'deep'
}

/** 照片本体在 IndexedDB，这里只留 id 和文字 */
export interface Photo {
  id: string
  caption: string
  date: string
  createdAt: number
  /** 旋转后自增，用来让 object URL 重新取一次 */
  rev?: number
}

/** 想对他说的话 */
export interface Moment {
  id: string
  text: string
  createdAt: number
}

/** 一天三句话。auto=true 表示还是自动草稿，没被改过 */
export interface DayEntry {
  date: string
  lines: [string, string, string]
  auto: boolean
  updatedAt: number
}

/** 自己加的 prompt（内置那批从仓库 md 构建期生成，不存这里） */
export interface MyPrompt {
  id: string
  title: string
  body: string
  createdAt: number
}

export interface State {
  version: number
  seeded: boolean
  focus: Record<string, string>     // date -> 今天的重心
  tasks: Task[]
  notes: Note[]
  engagements: Engagement[]
  inquiries: Inquiry[]
  meetings: Meeting[]
  anniversaries: Anniversary[]
  wishes: Wish[]
  trip: Trip
  logs: DayLog[]
  promptDraft: PromptDraft
  photos: Photo[]
  moments: Moment[]
  entries: DayEntry[]
  myPrompts: MyPrompt[]
  promptUses: Record<string, number>
}
