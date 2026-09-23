import { KINDS, type Item, type Kind } from './card'

/**
 * 东西存在哪、Claude 从哪儿借。
 *
 * 在 claude.ai 里打开时（页面被 claude.ai 框着，有 window.claude）：
 *   - 存进这个 artifact 的数据库里、她自己那一格（data/users/<她的 id>/…），
 *     平台保证只有她本人读得到，连分享出去的人也看不到；手机、电脑同一份。
 *   - 整理交给 Claude（sample），花的是她自己账号的额度，第一次会问她同不同意。
 *
 * 在别处打开（GitHub Pages、下载下来的单文件）：没有 window.claude，
 * 存在这台设备的浏览器里，只做本地整理。页面照样能用，只是少了 AI。
 */

export type SampleJson = <T = unknown>(input: string, opts?: { modelTier?: 'quick' | 'default' | 'complex'; cache?: boolean; signal?: AbortSignal }) => Promise<T>
interface Sample { json: SampleJson }

interface Snap { id: string; exists: boolean; data(): Record<string, unknown> | undefined }
interface DocRef {
  set(d: Record<string, unknown>): Promise<void>
  update(d: Record<string, unknown>): Promise<void>
  delete(): Promise<void>
}
interface Query {
  orderBy(f: string, dir?: 'asc' | 'desc'): Query
  limit(n: number): Query
  onSnapshot(next: (s: { docs: Snap[] }) => void, err?: (e: { code: string }) => void): () => void
}
interface Collection extends Query { doc(id?: string): DocRef }
interface DB { doc(path: string): { collection(path: string): Collection } }
interface User { id(): Promise<string | null> }

interface ClaudeRuntime { use(name: string): Promise<unknown> }
declare global { interface Window { claude?: ClaudeRuntime } }

export interface Store {
  mode: 'cloud' | 'local'
  subscribe(next: (items: Item[]) => void, onError?: (code: string) => void): () => void
  put(it: Item): Promise<void>
  patch(id: string, p: Partial<Item>): Promise<void>
  remove(id: string): Promise<void>
}

export interface Runtime {
  store: Store
  /** null：这里没有 Claude 可用 */
  sample: Sample | null
}

export async function connect(): Promise<Runtime> {
  const rt = typeof window !== 'undefined' ? window.claude : undefined
  if (!rt || typeof rt.use !== 'function') return { store: local(), sample: null }
  const [sample, db, user] = await Promise.all(
    ['sample', 'db', 'user'].map((n) => rt.use(n).catch(() => null)),
  ) as [Sample | null, DB | null, User | null]
  const uid = await user?.id().catch(() => null)
  const store = db && uid ? cloud(db, uid) : local()
  return { store, sample: sample && typeof sample.json === 'function' ? sample : null }
}

/** 数据库里读出来的东西不一定是自己写的那个样子：补齐每一格 */
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
      !!f && typeof (f as Record<string, unknown>).label === 'string' && typeof (f as Record<string, unknown>).value === 'string'),
    todos: arr(d.todos, (t): t is Item['todos'][number] =>
      !!t && typeof (t as Record<string, unknown>).text === 'string').map((t) => ({ text: t.text, done: !!t.done })),
    tags: arr(d.tags, (t): t is string => typeof t === 'string'),
    prompt: s(d.prompt),
    pinned: !!d.pinned,
    note: s(d.note) || undefined,
  }
}

const body = (it: Partial<Item>) => {
  const o: Record<string, unknown> = { ...it }
  delete o.id
  for (const k of Object.keys(o)) if (o[k] === undefined) delete o[k]
  return o
}

/**
 * 同一条的写入排队：数据库要求同一个文档一次只写一笔。
 * 她连点三下待办的勾，Claude 的整理结果又刚好回来 —— 这几笔得一笔一笔来
 */
function serial() {
  const tails = new Map<string, Promise<unknown>>()
  return <T,>(id: string, fn: () => Promise<T>): Promise<T> => {
    const prev = tails.get(id) ?? Promise.resolve()
    const next = prev.catch(() => {}).then(fn)
    tails.set(id, next)
    void next.finally(() => { if (tails.get(id) === next) tails.delete(id) }).catch(() => {})
    return next
  }
}

function cloud(db: DB, uid: string): Store {
  const col = db.doc(`data/users/${uid}/lib`).collection('items')
  const q = serial()
  return {
    mode: 'cloud',
    subscribe(next, onError) {
      return col.orderBy('createdAt', 'desc').limit(1000).onSnapshot(
        (s) => next(s.docs.filter((d) => d.exists).map((d) => normalize(d.id, d.data() ?? {})).filter((x): x is Item => !!x)),
        (e) => onError?.(e.code),
      )
    },
    put: (it) => q(it.id, () => col.doc(it.id).set(body(it))),
    patch: (id, p) => q(id, () => col.doc(id).update(body(p))),
    remove: (id) => q(id, () => col.doc(id).delete()),
  }
}

const KEY = 'suishou.items.v2'

function local(): Store {
  const subs = new Set<(items: Item[]) => void>()
  const read = (): Item[] => {
    try {
      const raw = JSON.parse(localStorage.getItem(KEY) || '[]') as Record<string, unknown>[]
      return raw.map((d) => normalize(String(d.id ?? ''), d)).filter((x): x is Item => !!x && !!x.id)
    } catch { return [] }
  }
  let items = read()
  const sorted = () => [...items].sort((a, b) => b.createdAt - a.createdAt)
  const emit = () => { const s = sorted(); subs.forEach((f) => f(s)) }
  const write = () => {
    try { localStorage.setItem(KEY, JSON.stringify(items)) } catch { /* 无痕 / 满了：这次会话里还在 */ }
    emit()
  }
  // 另一个标签页改了，这边跟着变
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', (e) => { if (e.key === KEY) { items = read(); emit() } })
  }
  return {
    mode: 'local',
    subscribe(next) {
      subs.add(next)
      queueMicrotask(() => next(sorted()))
      return () => { subs.delete(next) }
    },
    async put(it) { items = [it, ...items.filter((x) => x.id !== it.id)]; write() },
    async patch(id, p) { items = items.map((x) => (x.id === id ? { ...x, ...p, id } : x)); write() },
    async remove(id) { items = items.filter((x) => x.id !== id); write() },
  }
}
