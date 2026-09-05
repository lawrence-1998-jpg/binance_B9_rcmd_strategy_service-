import { useSyncExternalStore } from 'react'
import type { State } from './types'
import { seed, empty } from './seed'

const KEY = 'deskside.v1'
/**
 * 读不出来的那份原始数据留在这儿。
 *
 * 以前 load() 遇到解析失败、或者对象上没有 version，就直接 return seed()
 * ——回到示例数据。然后她一动，persist() 就把示例数据盖回同一个 key。
 * 也就是那本日记会被**静默地、永久地**覆盖掉，一句提示都没有。
 * 没有后端、没有回收站、她也还没有导出备份的习惯，这是这个 App
 * 能造成的最坏结果。
 *
 * 现在：读不出来就先把原始那串字节原样抄到这个 key 再说。哪怕我
 * 解析不了它，那也是她的东西，轮不到我扔。只写一次、永不覆盖——
 * 第一份才是最接近她真实数据的那份。
 */
const RESCUE = 'deskside.v1.rescue'

/**
 * 全部外部数据只经过这一个文件，界面只跟它打交道。
 * 以后要换成后端 API，只改这里，五个屏一行不用动。
 */
function load(): State {
  let raw: string | null = null
  try {
    raw = localStorage.getItem(KEY)
  } catch {
    /* 存储被清了、或在隐私模式下读不到 —— 回到种子数据，不崩 */
    return seed()
  }
  if (!raw) return seed()
  try {
    const parsed = JSON.parse(raw) as Partial<State>
    if (parsed && typeof parsed === 'object' && (parsed.version ?? 0) >= 1) return merge(parsed)
  } catch {
    /* 落到下面去救 */
  }
  // 有东西，但读不出来。先留一份原样的，再回种子
  keepRescue(raw)
  return seed()
}

/** 原样抄一份。已经有一份了就不动它——先来的那份更接近她真实的数据 */
function keepRescue(raw: string) {
  try {
    if (localStorage.getItem(RESCUE) === null) localStorage.setItem(RESCUE, raw)
  } catch {
    /* 配额满了/无痕模式，救不了就算了，至少没让它更糟 */
  }
}

function peekRescue(): string | null {
  try { return localStorage.getItem(RESCUE) } catch { return null }
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
    inquiries: arr(p.inquiries, []),
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
 * 「上次有一份数据没读出来」。
 *
 * 每次启动都读一遍，不只是刚出事那一次：出事的时候她多半不在看，
 * 得让这条一直挂着，直到她自己把那份导出去。
 */
let rescued: string | null = peekRescue()
const rescueSubs = new Set<(r: string | null) => void>()

export function onRescue(cb: (r: string | null) => void) {
  rescueSubs.add(cb)
  cb(rescued)
  return () => { rescueSubs.delete(cb) }
}

export function rescuedRaw(): string | null { return rescued }

/** 她说存好了才删。这一步是不可逆的，所以只能由她点 */
export function dropRescue() {
  try { localStorage.removeItem(RESCUE) } catch { /* 删不掉就留着，不是坏事 */ }
  rescued = null
  rescueSubs.forEach((f) => f(null))
}

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
  const known = ['tasks', 'notes', 'engagements', 'inquiries', 'wishes', 'entries', 'photos', 'moments', 'anniversaries']
  const present = known.filter((k) => k in o)
  if (present.length === 0) return false
  return present.every((k) => Array.isArray(o[k]))
}

export function importState(p: Partial<State>) {
  update(() => merge(p))
}
