import type { Intent, Kind, Target } from './shape'

/**
 * 只存在这台设备的 localStorage 里，不上传。
 *
 * 存三样：正在弄的这一条（切出去再回来还在）、最近复制过的 30 条
 * （同一段材料常常要换个用途再问一次）、两个偏好。
 * 读写全包 try：无痕模式、存储满了、被禁用，都不能让页面打不开。
 */
const KEY = 'suishou.v1'
const MAX_ITEMS = 30
/** 超过这么长的不进「最近」：一条就能把 localStorage 撑满 */
const MAX_ITEM_CHARS = 60_000

export interface Draft {
  material: string
  /** null = 用推荐的那个 */
  intent: Intent | null
  note: string
  /** 手改过的 Prompt；null = 没改过 */
  edited: string | null
}

export interface Item {
  id: string
  ts: number
  material: string
  intent: Intent
  note: string
  kind: Kind
}

export interface Saved {
  draft: Draft
  history: Item[]
  target: Target
  /** 贴进来就自动复制推荐的那一版 */
  auto: boolean
}

const EMPTY: Saved = {
  draft: { material: '', intent: null, note: '', edited: null },
  history: [],
  target: 'md',
  auto: true,
}

export function load(): Saved {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return structuredCloneSafe(EMPTY)
    const s = JSON.parse(raw) as Partial<Saved>
    return {
      draft: { ...EMPTY.draft, ...(s.draft ?? {}) },
      history: Array.isArray(s.history) ? s.history.filter(isItem).slice(0, MAX_ITEMS) : [],
      target: s.target === 'xml' ? 'xml' : 'md',
      auto: s.auto !== false,
    }
  } catch {
    return structuredCloneSafe(EMPTY)
  }
}

export function save(s: Saved): boolean {
  try {
    localStorage.setItem(KEY, JSON.stringify(s))
    return true
  } catch {
    // 满了：先丢掉一半旧记录再试一次，正在弄的那条最要紧
    try {
      localStorage.setItem(KEY, JSON.stringify({ ...s, history: s.history.slice(0, Math.floor(s.history.length / 2)) }))
      return true
    } catch {
      return false
    }
  }
}

/** 复制成功的那一刻记一笔。同一段材料只留一条，挪到最前面 */
export function remember(list: Item[], it: Omit<Item, 'id' | 'ts'>): Item[] {
  if (!it.material.trim() || it.material.length > MAX_ITEM_CHARS) return list
  const rest = list.filter((x) => x.material !== it.material)
  const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
  return [{ ...it, id, ts: Date.now() }, ...rest].slice(0, MAX_ITEMS)
}

function isItem(x: unknown): x is Item {
  const o = x as Item
  return !!o && typeof o.material === 'string' && typeof o.intent === 'string' && typeof o.ts === 'number'
}

function structuredCloneSafe(s: Saved): Saved {
  return { draft: { ...s.draft }, history: [], target: s.target, auto: s.auto }
}

/** 「3 分钟前」「昨天 14:20」「9月3日」 */
export function ago(ts: number, now = Date.now()): string {
  const d = Math.max(0, now - ts)
  if (d < 60_000) return '刚刚'
  if (d < 3_600_000) return `${Math.floor(d / 60_000)} 分钟前`
  const a = new Date(ts)
  const b = new Date(now)
  const hm = `${a.getHours()}:${String(a.getMinutes()).padStart(2, '0')}`
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const diff = Math.round((day(b) - day(a)) / 86_400_000)
  if (diff === 0) return `今天 ${hm}`
  if (diff === 1) return `昨天 ${hm}`
  return `${a.getMonth() + 1}月${a.getDate()}日`
}
