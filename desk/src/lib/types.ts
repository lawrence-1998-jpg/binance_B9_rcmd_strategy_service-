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

export interface State {
  version: number
  seeded: boolean
  focus: Record<string, string>     // date -> 今天的重心
  tasks: Task[]
  notes: Note[]
  engagements: Engagement[]
  meetings: Meeting[]
  anniversaries: Anniversary[]
  wishes: Wish[]
  trip: Trip
  logs: DayLog[]
}
