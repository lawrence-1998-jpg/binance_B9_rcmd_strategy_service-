import { useSyncExternalStore } from 'react'
import type { State } from './types'
import { seed, empty } from './seed'

const KEY = 'deskside.v1'

/**
 * 全部外部数据只经过这一个文件，界面只跟它打交道。
 * 以后要换成后端 API，只改这里，五个屏一行不用动。
 */
function load(): State {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return seed()
    const parsed = JSON.parse(raw) as Partial<State>
    if (parsed && typeof parsed === 'object' && (parsed.version ?? 0) >= 1) return merge(parsed)
  } catch {
    /* 存储被清了、或在隐私模式下读不到 —— 回到种子数据，不崩 */
  }
  return seed()
}

/**
 * 把存下来的数据合回当前形状。
 *
 * 顶层浅合并（`{...seed(), ...parsed}`）只补得了新增的顶层字段：
 * 老数据里已经存在的 `trip` / `promptDraft` 是整个对象被原样带过来的，
 * 里面新加的字段不会被补上，读到就是 undefined。trip 尤其致命——
 * 少一个 todos 数组，`.map` 直接把屏幕打崩。
 * 所以这两个嵌套对象单独再合一层，数组字段逐个兜底成数组。
 */
function merge(p: Partial<State>): State {
  const base = seed()
  const arr = <T>(v: unknown, fallback: T[]): T[] => (Array.isArray(v) ? (v as T[]) : fallback)
  const obj = (v: unknown): Record<string, unknown> =>
    v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
  return {
    ...base,
    ...p,
    version: 1,
    focus: obj(p.focus) as Record<string, string>,
    tasks: arr(p.tasks, base.tasks),
    notes: arr(p.notes, base.notes),
    engagements: arr(p.engagements, base.engagements),
    meetings: arr(p.meetings, base.meetings),
    anniversaries: arr(p.anniversaries, base.anniversaries),
    wishes: arr(p.wishes, base.wishes),
    trip: { ...base.trip, ...obj(p.trip), days: arr(obj(p.trip).days, base.trip.days), todos: arr(obj(p.trip).todos, base.trip.todos) },
    logs: arr(p.logs, base.logs),
    promptDraft: { ...base.promptDraft, ...obj(p.promptDraft) },
    photos: arr(p.photos, []),
    moments: arr(p.moments, []),
    entries: arr(p.entries, []),
    myPrompts: arr(p.myPrompts, []),
    promptUses: obj(p.promptUses) as Record<string, number>,
  }
}

let state: State = load()
const subs = new Set<() => void>()

/**
 * 写盘失败的处理。
 *
 * 以前这里是 try/catch 直接吞掉的，那是个很坏的默认：这是本日记，
 * 用户敲完字看到界面更新了就以为记下了，实际一个字都没落盘，
 * 关掉页面就全没。配额写满（照片元数据攒多了）和 iOS 无痕模式
 * 都会真实触发。所以失败必须冒到界面上去说。
 */
let failed = false
const failSubs = new Set<(f: boolean) => void>()
export function onPersistFail(f: (failed: boolean) => void) {
  failSubs.add(f)
  return () => { failSubs.delete(f) }
}

function persist() {
  try {
    localStorage.setItem(KEY, JSON.stringify(state))
    if (failed) { failed = false; failSubs.forEach((f) => f(false)) }
  } catch {
    if (!failed) { failed = true; failSubs.forEach((f) => f(true)) }
  }
}

export function get(): State {
  return state
}

export function update(fn: (s: State) => State) {
  state = fn(state)
  persist()
  subs.forEach((f) => f())
}

function subscribe(f: () => void) {
  subs.add(f)
  return () => { subs.delete(f) }
}

export function useStore<T>(select: (s: State) => T): T {
  return useSyncExternalStore(subscribe, () => select(state), () => select(state))
}

export const uid = () => Math.random().toString(36).slice(2, 10)

export function resetToEmpty() {
  update(() => empty())
}

export function exportJSON(): string {
  return JSON.stringify(state, null, 2)
}

/** 一份备份长什么样：状态本体 + 照片二进制（data URL） */
export interface Backup extends State {
  exportedAt: string
  photoData?: Record<string, string>
}

/**
 * 校验一份导入的数据。
 *
 * 以前只检查 `'tasks' in parsed` 就放行，那等于没检查：
 * `{"tasks": 123}` 能过闸，进来之后第一个 `.filter` 就把整个界面打崩，
 * 而这时旧数据已经被覆盖了，救不回来。
 */
export function looksLikeBackup(v: unknown): v is Partial<State> {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return false
  const o = v as Record<string, unknown>
  // 认得出是这个 App 导出的：至少要有一个我们认识的数组字段，且形状是对的
  const known = ['tasks', 'notes', 'engagements', 'wishes', 'entries', 'photos', 'moments', 'anniversaries']
  const present = known.filter((k) => k in o)
  if (present.length === 0) return false
  return present.every((k) => Array.isArray(o[k]))
}

export function importState(p: Partial<State>) {
  update(() => merge(p))
}
