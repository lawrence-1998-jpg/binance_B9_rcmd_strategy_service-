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
    const parsed = JSON.parse(raw) as State
    if (parsed && parsed.version === 1) return { ...seed(), ...parsed }
  } catch {
    /* 存储被清了、或在隐私模式下读不到 —— 回到种子数据，不崩 */
  }
  return seed()
}

let state: State = load()
const subs = new Set<() => void>()

function persist() {
  try {
    localStorage.setItem(KEY, JSON.stringify(state))
  } catch {
    /* 写不进去也不能让界面挂掉 */
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

export function importJSON(text: string): boolean {
  try {
    const parsed = JSON.parse(text) as State
    if (!parsed || typeof parsed !== 'object' || !('tasks' in parsed)) return false
    update(() => ({ ...seed(), ...parsed, version: 1 }))
    return true
  } catch {
    return false
  }
}
