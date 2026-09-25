import { KINDS, askLabel, type Ask, type Item, type Kind } from './card'

/**
 * 东西存在哪：只在这台设备上，不上传。
 *
 *   IndexedDB —— 放得下几百 MB，截图也存得下。
 *   打不开（个别隐私模式）就退回 localStorage，只是容量小一些。
 *   老版本存在 localStorage 'suishou.items.v2' 里的，第一次打开时搬过来。
 *   同一台设备开了两个标签页：一边改了，另一边跟着变。
 *
 * 换手机 / 换浏览器：设置里「导出备份」存一个文件，那边「导入备份」。
 */

export interface Store {
  mode: 'idb' | 'ls'
  subscribe(next: (items: Item[]) => void): () => void
  put(it: Item): Promise<void>
  /** 导入：一次写一批 */
  putMany(its: Item[]): Promise<void>
  /** 那条已经被删了就什么都不做（Claude 整理完回来时她可能已经删了） */
  patch(id: string, p: Partial<Item>): Promise<void>
  remove(id: string): Promise<void>
}

/** 读回来的东西不一定是自己写的那个样子（老版本、导入的备份）：补齐每一格 */
export function normalize(id: string, d: Record<string, unknown>): Item | null {
  if (typeof d.raw !== 'string' || !d.raw) return null
  const arr = <T,>(x: unknown, ok: (v: unknown) => v is T): T[] => (Array.isArray(x) ? x.filter(ok) : [])
  const s = (x: unknown) => (typeof x === 'string' ? x : '')
  const kind = (s(d.kind) in KINDS ? s(d.kind) : 'other') as Kind
  const status = ['pending', 'done', 'local', 'failed'].includes(s(d.status)) ? (d.status as Item['status']) : 'local'
  return {
    id,
    raw: d.raw,
    createdAt: typeof d.createdAt === 'number' ? d.createdAt : 0,
    updatedAt: typeof d.updatedAt === 'number' ? d.updatedAt : 0,
    status,
    kind,
    title: s(d.title) || d.raw.slice(0, 18),
    summary: s(d.summary),
    fields: arr(d.fields, (f): f is Item['fields'][number] =>
      !!f && typeof (f as Record<string, unknown>).label === 'string' && typeof (f as Record<string, unknown>).value === 'string')
      .map((f) => ({ label: f.label, value: f.value })),
    todos: arr(d.todos, (t): t is Item['todos'][number] =>
      !!t && typeof (t as Record<string, unknown>).text === 'string').map((t) => ({ text: t.text, done: !!t.done })),
    tags: arr(d.tags, (t): t is string => typeof t === 'string'),
    prompt: s(d.prompt),
    pinned: !!d.pinned,
    note: s(d.note) || undefined,
    img: s(d.img).startsWith('data:image/') ? s(d.img) : undefined,
  }
}

const clean = (it: Item): Item => {
  const o = { ...it } as Record<string, unknown>
  for (const k of Object.keys(o)) if (o[k] === undefined) delete o[k]
  return o as unknown as Item
}

// ---------------------------------------------------------------- 备份

export interface Backup { app: 'suishou'; version: 1; exportedAt: string; items: Item[]; asks?: Ask[] }

export function toBackup(items: Item[], now = new Date(), asks: Ask[] = []): string {
  // 整理到一半的，导出时当作没整理完：换台设备打开不会一直转圈
  const out = items.map((it) => clean(it.status === 'pending' ? { ...it, status: 'failed', note: '' } : it))
  const b: Backup = { app: 'suishou', version: 1, exportedAt: now.toISOString(), items: out, ...(asks.length ? { asks } : {}) }
  return JSON.stringify(b, null, 1)
}

/** 认得自己导出的文件，也认一个光秃秃的数组；认不出来就抛错，不猜 */
export function readBackup(text: string): { items: Item[]; asks: Ask[] } {
  let j: unknown
  try { j = JSON.parse(text) } catch { throw new Error('not_json') }
  const list = Array.isArray(j) ? j : (j as Partial<Backup>)?.app === 'suishou' && Array.isArray((j as Backup).items) ? (j as Backup).items : null
  if (!list) throw new Error('not_backup')
  const items = list
    .map((d) => (d && typeof d === 'object' ? normalize(String((d as Record<string, unknown>).id ?? ''), d as Record<string, unknown>) : null))
    .filter((x): x is Item => !!x && !!x.id)
    .map((it) => (it.status === 'pending' ? { ...it, status: 'failed' as const } : it))
  return { items, asks: cleanAsks(Array.isArray(j) ? [] : (j as Backup).asks) }
}
export const fromBackup = (text: string): Item[] => readBackup(text).items

// ---------------------------------------------------------------- 她自己存的问法

const ASKS = 'suishou.asks'
function cleanAsks(x: unknown): Ask[] {
  if (!Array.isArray(x)) return []
  return x
    .filter((a): a is Ask => !!a && typeof (a as Ask).text === 'string' && !!(a as Ask).text.trim())
    .map((a) => ({ text: a.text.trim().slice(0, 300), label: typeof a.label === 'string' && a.label.trim() ? a.label.trim().slice(0, 12) : askLabel(a.text) }))
    .slice(0, 30)
}
export function loadAsks(): Ask[] {
  try { return cleanAsks(JSON.parse(localStorage.getItem(ASKS) || '[]')) } catch { return [] }
}
export function saveAsks(asks: Ask[]): void {
  try { localStorage.setItem(ASKS, JSON.stringify(asks)) } catch { /* 无痕模式：这次会话里还在 */ }
}
/** 合在一起，同一句不重复 */
export function mergeAsks(have: Ask[], more: Ask[]): Ask[] {
  const seen = new Set(have.map((a) => a.text))
  return [...have, ...more.filter((a) => !seen.has(a.text) && seen.add(a.text))].slice(0, 30)
}

/** 导入时怎么合：同一条（同 id）留改得更晚的；内容一模一样的不重复收（截图按图比，不按「［截图］」那几个字） */
export function merge(have: Item[], incoming: Item[]): { add: Item[]; skipped: number } {
  const byId = new Map(have.map((x) => [x.id, x]))
  const same = (x: Item) => x.img ?? x.raw
  const raws = new Set(have.map(same))
  const add: Item[] = []
  let skipped = 0
  for (const it of incoming) {
    const old = byId.get(it.id)
    if (old ? old.updatedAt >= it.updatedAt : raws.has(same(it))) { skipped++; continue }
    add.push(it)
    byId.set(it.id, it)
    raws.add(same(it))
  }
  return { add, skipped }
}

// ---------------------------------------------------------------- 打开

const LEGACY = 'suishou.items.v2'
const DB = 'suishou'
const OS = 'items'

export async function openStore(): Promise<Store> {
  try {
    if (typeof indexedDB === 'undefined') throw new Error('no idb')
    return await idbStore(await openDb())
  } catch {
    return lsStore()
  }
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((ok, no) => {
    const r = indexedDB.open(DB, 1)
    r.onupgradeneeded = () => { r.result.createObjectStore(OS, { keyPath: 'id' }) }
    r.onsuccess = () => ok(r.result)
    r.onerror = () => no(r.error)
    r.onblocked = () => no(new Error('blocked'))
  })
}

const done = (tx: IDBTransaction) => new Promise<void>((ok, no) => {
  tx.oncomplete = () => ok()
  tx.onerror = () => no(tx.error)
  tx.onabort = () => no(tx.error ?? new Error('abort'))
})

const quota = (e: unknown) => {
  const name = (e as { name?: string })?.name ?? ''
  return Object.assign(new Error(name), { code: /Quota/i.test(name) ? 'quota_exceeded' : 'write_failed' })
}

async function idbStore(db: IDBDatabase): Promise<Store> {
  const readAll = () => new Promise<Item[]>((ok, no) => {
    const r = db.transaction(OS).objectStore(OS).getAll()
    r.onsuccess = () => ok((r.result as Record<string, unknown>[]).map((d) => normalize(String(d.id ?? ''), d)).filter((x): x is Item => !!x && !!x.id))
    r.onerror = () => no(r.error)
  })
  const write = async (put: Item[], del: string[] = []) => {
    try {
      const tx = db.transaction(OS, 'readwrite')
      const os = tx.objectStore(OS)
      put.forEach((it) => os.put(clean(it)))
      del.forEach((id) => os.delete(id))
      await done(tx)
    } catch (e) { throw quota(e) }
  }

  // 老版本（localStorage）里的搬过来。写进去了才删旧的
  try {
    const old = localStorage.getItem(LEGACY)
    if (old) {
      const have = new Set((await readAll()).map((x) => x.id))
      const list = (JSON.parse(old) as Record<string, unknown>[])
        .map((d) => normalize(String(d.id ?? ''), d)).filter((x): x is Item => !!x && !!x.id && !have.has(x.id))
      if (list.length) await write(list)
      localStorage.removeItem(LEGACY)
    }
  } catch { /* 搬不动就留着，下次再搬 */ }

  let items = new Map((await readAll()).map((x) => [x.id, x]))
  const subs = new Set<(items: Item[]) => void>()
  const sorted = () => [...items.values()].sort((a, b) => b.createdAt - a.createdAt)
  const emit = () => { const s = sorted(); subs.forEach((f) => f(s)) }
  const reload = () => readAll().then((all) => { items = new Map(all.map((x) => [x.id, x])); emit() }).catch(() => {})
  const bc = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('suishou') : null
  bc?.addEventListener('message', () => { void reload() })

  /**
   * 先改内存、马上显示，再落盘。两笔紧挨着的改动（连点两下待办的勾、Claude 的结果刚好回来）
   * 第二笔是在第一笔改完的样子上改的；落盘的事务按开的顺序执行，盘上最后也是第二笔。
   * 落盘失败（满了）：按盘上的样子重读一遍，再告诉调用方
   */
  const commit = async (put: Item[], del: string[] = []) => {
    put.forEach((it) => items.set(it.id, it))
    del.forEach((id) => items.delete(id))
    emit()
    try {
      await write(put, del)
    } catch (e) {
      await reload()
      throw e
    }
    bc?.postMessage('changed')
  }

  return {
    mode: 'idb',
    subscribe(next) {
      subs.add(next)
      queueMicrotask(() => next(sorted()))
      return () => { subs.delete(next) }
    },
    async put(it) {
      await commit([it])
      askToKeep()
    },
    async putMany(its) {
      if (its.length) await commit(its)
    },
    async patch(id, p) {
      const cur = items.get(id)
      if (!cur) return // 已经删了：别把它写回来
      await commit([{ ...cur, ...p, id }])
    },
    async remove(id) {
      await commit([], [id])
    },
  }
}

/** 退路：localStorage。另一个标签页改了，这边跟着变 */
function lsStore(): Store {
  const subs = new Set<(items: Item[]) => void>()
  const read = (): Item[] => {
    try {
      const raw = JSON.parse(localStorage.getItem(LEGACY) || '[]') as Record<string, unknown>[]
      return raw.map((d) => normalize(String(d.id ?? ''), d)).filter((x): x is Item => !!x && !!x.id)
    } catch { return [] }
  }
  let items = read()
  const sorted = () => [...items].sort((a, b) => b.createdAt - a.createdAt)
  const emit = () => { const s = sorted(); subs.forEach((f) => f(s)) }
  const save = (next: Item[]) => {
    try { localStorage.setItem(LEGACY, JSON.stringify(next.map(clean))) } catch (e) { throw quota(e) }
    items = next
    emit()
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', (e) => { if (e.key === LEGACY) { items = read(); emit() } })
  }
  return {
    mode: 'ls',
    subscribe(next) {
      subs.add(next)
      queueMicrotask(() => next(sorted()))
      return () => { subs.delete(next) }
    },
    async put(it) { save([it, ...items.filter((x) => x.id !== it.id)]) },
    async putMany(its) {
      const ids = new Set(its.map((x) => x.id))
      save([...its, ...items.filter((x) => !ids.has(x.id))])
    },
    async patch(id, p) { if (items.some((x) => x.id === id)) save(items.map((x) => (x.id === id ? { ...x, ...p, id } : x))) },
    async remove(id) { save(items.filter((x) => x.id !== id)) },
  }
}

/**
 * 请浏览器别在空间紧张时把这些数据清掉 —— 这里是她唯一的一份。
 * Chrome / Safari 静默决定，不弹框；只问一次。
 */
let asked = false
function askToKeep() {
  if (asked) return
  asked = true
  // Firefox 会为这个弹一个吓人的框，它那边就不问了（数据照样在，只是没打「别清」的标记）
  if (typeof navigator === 'undefined' || /Firefox\//.test(navigator.userAgent)) return
  try { void navigator.storage?.persist?.().catch(() => {}) } catch { /* 不支持就算了 */ }
}
