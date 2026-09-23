import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  KINDS, aiPrompt, asAi, asText, dayGroup, fromAi, manyAi, manyText, matches, newId, quick, stamp, tidy,
  type Item, type Kind,
} from './lib/card'
import { connect, type Runtime } from './lib/store'
import { copyText } from './lib/copy'
import { applyUpdate, useUpdate } from './lib/update'
import { EXAMPLES } from './examples'

/**
 * 随手拾 —— 随手复制的信息，贴进来就被整理成一张卡片，收着、找得到、随时拿出去用。
 *
 * 三件事，按她用的顺序：
 *   收：粘贴即收下。不用点「保存」，不用选类型。
 *   整：Claude 读懂它，拆成标题、要点、字段（时间 / 地点 / 电话 / 金额…）、待办，
 *       再替她想好下一步拿去问 AI 的那一句。Claude 想的那几秒，本地先认出来的东西已经摆上了。
 *   用：一张卡上能复制的东西都是按钮 —— 一个字段、整理版、给 AI 的版本、原文；
 *       多选几张，合成一段再复制。
 */

type Toast = { msg: string; undo?: () => void; id: number }
/** 这几种错误说明这个视图里用不了 Claude：别再问了，整理降级成本地 */
const AI_OFF = new Set(['not_granted', 'sampling_disabled', 'not_declared', 'capability_disabled', 'capability_removed'])

const touch = typeof window !== 'undefined' && !!window.matchMedia?.('(pointer: coarse)').matches
const MOD = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? '⌘' : 'Ctrl'

export function App() {
  const [rt, setRt] = useState<Runtime | null>(null)
  const [items, setItems] = useState<Item[] | null>(null)
  const [aiOff, setAiOff] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const [kind, setKind] = useState<Kind | 'all'>('all')
  const [q, setQ] = useState('')
  const [searching, setSearching] = useState(false)
  const [picked, setPicked] = useState<Set<string> | null>(null)
  const [toast, setToast] = useState<Toast | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [storeErr, setStoreErr] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())

  const rtRef = useRef<Runtime | null>(null)
  const readyWaiters = useRef<((r: Runtime) => void)[]>([])
  const itemsRef = useRef<Item[]>([])
  itemsRef.current = items ?? []
  const aiOffRef = useRef(false)
  aiOffRef.current = aiOff
  const capRef = useRef<HTMLTextAreaElement>(null)

  // ---------------------------------------------------------------- 连上

  useEffect(() => {
    let live = true
    void connect().then((r) => {
      if (!live) return
      rtRef.current = r
      setRt(r)
      readyWaiters.current.splice(0).forEach((f) => f(r))
    })
    return () => { live = false }
  }, [])
  useEffect(() => {
    if (!rt) return
    return rt.store.subscribe(setItems, (code) => setStoreErr(code))
  }, [rt])
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000)
    return () => clearInterval(t)
  }, [])

  const whenReady = () => (rtRef.current ? Promise.resolve(rtRef.current) : new Promise<Runtime>((r) => readyWaiters.current.push(r)))

  // ---------------------------------------------------------------- 提示

  const say = useCallback((msg: string, undo?: () => void) => setToast({ msg, undo, id: Date.now() }), [])
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), toast.undo ? 6000 : 2200)
    return () => clearTimeout(t)
  }, [toast])

  const copyTimer = useRef<number>()
  /** 必须在点击 / 按键里同步调用：copyText 第一步就写剪贴板，iOS 只认手势里发起的写入 */
  const copy = (text: string, key: string, what: string) => {
    void copyText(text).then((ok) => {
      if (!ok) { say('没复制上 —— 长按文字自己选一下'); return }
      setCopied(key)
      window.clearTimeout(copyTimer.current)
      copyTimer.current = window.setTimeout(() => setCopied(null), 1600)
      try { navigator.vibrate?.(10) } catch { /* 不支持就算了 */ }
      say(`已复制${what}`)
    })
  }

  // ---------------------------------------------------------------- 整理

  const patch = async (id: string, p: Partial<Item>) => {
    try { await rtRef.current?.store.patch(id, { ...p, updatedAt: Date.now() }) } catch { /* 已经被删了 */ }
  }

  const organize = async (it: Item, again = false) => {
    const r = await whenReady()
    if (!r.sample || aiOffRef.current) { await patch(it.id, { status: 'local', note: '' }); return }
    if (again) await patch(it.id, { status: 'pending', note: '' })
    try {
      const j = await r.sample.json(aiPrompt(it.raw), again ? { modelTier: 'default', cache: false } : { modelTier: 'quick' })
      const card = fromAi(j)
      if (!card) throw { code: 'invalid_json' }
      await patch(it.id, { ...card, status: 'done', note: '' })
    } catch (e) {
      const code = (e as { code?: string })?.code ?? 'upstream_error'
      if (code === 'cancelled') return
      if (AI_OFF.has(code)) {
        setAiOff(true)
        await patch(it.id, { status: 'local', note: '' })
        return
      }
      const note =
        code === 'rate_limited' ? 'Claude 这会儿忙，过一会儿点「重新整理」'
        : code === 'prompt_too_large' ? '太长了，Claude 一次读不完 —— 可以分几段收'
        : code === 'refused' ? 'Claude 没接这条，先做了基础整理'
        : code === 'session_expired' ? '登录过期了，重新登录 claude.ai 后点「重新整理」'
        : '这次没整理成，点「重新整理」再试'
      await patch(it.id, { status: 'failed', note })
    }
  }

  // ---------------------------------------------------------------- 收

  const add = async (text: string) => {
    const raw = tidy(text)
    if (!raw) { say('剪贴板里没有文字'); return }
    const r = await whenReady()
    const dup = itemsRef.current.find((x) => x.raw === raw)
    if (dup) {
      setKind('all'); setQ(''); setOpen(dup.id)
      say('这条已经收过了')
      requestAnimationFrame(() => document.getElementById('c-' + dup.id)?.scrollIntoView({ block: 'center', behavior: 'smooth' }))
      return
    }
    const t = Date.now()
    const it: Item = {
      id: newId(), raw, createdAt: t, updatedAt: t,
      status: r.sample && !aiOffRef.current ? 'pending' : 'local',
      pinned: false,
      ...quick(raw),
    }
    setKind('all'); setQ(''); setSearching(false); setOpen(it.id)
    try {
      await r.store.put(it)
    } catch (e) {
      const code = (e as { code?: string })?.code
      say(code === 'quota_exceeded' ? '库满了，删掉一些旧的再收' : '没存上，再贴一次试试')
      return
    }
    if (it.status === 'pending') void organize(it)
  }
  const addRef = useRef(add)
  addRef.current = add

  // 页面任何地方粘贴都算收下；在别的输入框里粘贴不抢
  useEffect(() => {
    const on = (e: ClipboardEvent) => {
      const el = e.target instanceof Element ? e.target : null
      const field = el?.closest('input, textarea, [contenteditable="true"]')
      if (field && field !== capRef.current) return
      if (field === capRef.current) {
        const ta = capRef.current!
        const whole = !ta.value.trim() || (ta.selectionStart === 0 && ta.selectionEnd === ta.value.length)
        if (!whole) return // 在框里接着编辑，不是收新的一条
      }
      const text = e.clipboardData?.getData('text/plain') ?? ''
      e.preventDefault()
      setDraft('')
      if (touch) capRef.current?.blur() // 收下了就把键盘收起来，让她看到卡片
      void addRef.current(text)
    }
    document.addEventListener('paste', on)
    return () => document.removeEventListener('paste', on)
  }, [])

  const takeDraft = () => {
    if (!draft.trim()) return
    const t = draft
    setDraft('')
    void add(t)
  }

  // ---------------------------------------------------------------- 改 / 删

  const remove = async (list: Item[]) => {
    const r = rtRef.current
    if (!r || !list.length) return
    await Promise.all(list.map((it) => r.store.remove(it.id).catch(() => {})))
    if (list.some((it) => it.id === open)) setOpen(null)
    say(list.length > 1 ? `删掉了 ${list.length} 条` : '删掉了', () => { list.forEach((it) => void r.store.put(it).catch(() => {})) })
  }

  const toggleTodo = (it: Item, i: number) =>
    patch(it.id, { todos: it.todos.map((t, j) => (j === i ? { ...t, done: !t.done } : t)) })

  // ---------------------------------------------------------------- 看

  const lib = items ?? []
  const counts = useMemo(() => {
    const c = new Map<Kind, number>()
    for (const it of lib) c.set(it.kind, (c.get(it.kind) ?? 0) + 1)
    return c
  }, [lib])
  const shown = useMemo(() => {
    const list = lib.filter((it) => (kind === 'all' || it.kind === kind) && matches(it, q))
    return [...list.filter((x) => x.pinned), ...list.filter((x) => !x.pinned)]
  }, [lib, kind, q])
  const groups = useMemo(() => {
    const out: { name: string; items: Item[] }[] = []
    for (const it of shown) {
      const name = it.pinned ? '置顶' : dayGroup(it.createdAt, now)
      const g = out[out.length - 1]
      if (g && g.name === name) g.items.push(it)
      else out.push({ name, items: [it] })
    }
    return out
  }, [shown, now])

  const empty = items !== null && lib.length === 0
  const pickedItems = picked ? lib.filter((it) => picked.has(it.id)) : []

  // 键盘：/ 搜索，Esc 收起
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const el = e.target instanceof Element ? e.target : null
      const inField = !!el?.closest('input, textarea, [contenteditable="true"]')
      if (e.key === 'Escape') {
        if (inField) (el as HTMLElement).blur()
        else if (picked) setPicked(null)
        else if (open) setOpen(null)
        else if (searching) { setSearching(false); setQ('') }
      } else if (e.key === '/' && !inField) {
        e.preventDefault()
        setSearching(true)
      }
    }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [picked, open, searching])

  const status =
    !rt ? '正在打开你的收藏…'
    : rt.sample && !aiOff ? (rt.store.mode === 'cloud' ? '粘贴即收下 · Claude 帮你整理 · 手机电脑同一份' : '粘贴即收下 · Claude 帮你整理')
    : aiOff ? '粘贴即收下 · 这里没开 Claude，只做基础整理'
    : '粘贴即收下 · 只存在这台设备 · 在 Claude 里打开能用 AI 整理'

  return (
    <div className={'app' + (picked ? ' picking' : '')}>
      <header className="top">
        <div className="brand">
          <span className="logo" aria-hidden="true">拾</span>
          <h1>随手拾</h1>
          {lib.length > 0 && <span className="count">{lib.length} 条</span>}
        </div>
        <div className="top-a">
          {lib.length > 0 && (
            <button type="button" className="ghost" aria-label="搜索" aria-pressed={searching}
              onClick={() => { setSearching((s) => !s); if (searching) setQ('') }}>
              <SearchIcon />
            </button>
          )}
          {lib.length > 0 && (
            <button type="button" className="ghost txt" aria-pressed={!!picked}
              onClick={() => setPicked((p) => (p ? null : new Set()))}>
              {picked ? '完成' : '选择'}
            </button>
          )}
        </div>
      </header>

      <UpdateBanner />

      {searching && (
        <div className="search">
          <SearchIcon />
          <input
            id="search"
            type="search"
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜标题、原文、电话、地点……"
            aria-label="搜索"
          />
        </div>
      )}

      {!picked && !searching && (
        <section className="capture" aria-label="收下一条">
          <textarea
            id="capture"
            ref={capRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); takeDraft() } }}
            placeholder={touch ? '长按这里，粘贴 —— 聊天、地址、报价、链接、名片都行' : `粘贴到这里，或者在页面任何地方按 ${MOD}+V`}
            rows={draft ? Math.min(8, draft.split('\n').length + 1) : 2}
            aria-label="粘贴或输入要收下的内容"
          />
          <div className="cap-foot">
            <span className={'cap-hint' + (rt?.sample && !aiOff ? ' ai' : '')}>{status}</span>
            {draft.trim() && (
              <button type="button" className="take" onClick={takeDraft}>收下</button>
            )}
          </div>
        </section>
      )}

      {storeErr && (
        <p className="warn" role="status">
          {storeErr === 'revoked' ? '这个页面的存储权限被收回了，新收的东西不会保存。' : '存储暂时连不上，刚收的可能没保存 —— 刷新一下再看。'}
        </p>
      )}

      {lib.length > 0 && (
        <nav className="kinds" aria-label="按类型看">
          <button type="button" className={kind === 'all' ? 'on' : ''} aria-pressed={kind === 'all'} onClick={() => setKind('all')}>
            全部 <span>{lib.length}</span>
          </button>
          {(Object.keys(KINDS) as Kind[]).filter((k) => counts.get(k)).map((k) => (
            <button key={k} type="button" className={kind === k ? 'on' : ''} aria-pressed={kind === k} data-k={k} onClick={() => setKind(kind === k ? 'all' : k)}>
              {KINDS[k]} <span>{counts.get(k)}</span>
            </button>
          ))}
        </nav>
      )}

      <main className="list">
        {items === null && <div className="loading" aria-hidden="true"><i /><i /><i /></div>}

        {empty && (
          <>
            <p className="ex-h">示例 · 贴进来的东西会变成这样。收下第一条后这些就不见了。</p>
            {EXAMPLES.map((it) => (
              <Card key={it.id} it={it} example open={open === it.id} now={now} copied={copied}
                onToggle={() => setOpen(open === it.id ? null : it.id)} copy={copy} />
            ))}
          </>
        )}

        {!empty && items !== null && shown.length === 0 && (
          <p className="none">{q ? `没找到「${q}」` : '这一类还没有'}</p>
        )}

        {groups.map((g) => (
          <section key={g.name} className="group" aria-label={g.name}>
            <h2 className="group-h">{g.name}</h2>
            {g.items.map((it) => (
              <Card
                key={it.id}
                it={it}
                now={now}
                open={!picked && open === it.id}
                copied={copied}
                picking={!!picked}
                picked={!!picked?.has(it.id)}
                onPick={() => setPicked((p) => {
                  const n = new Set(p ?? [])
                  if (n.has(it.id)) n.delete(it.id); else n.add(it.id)
                  return n
                })}
                onToggle={() => setOpen(open === it.id ? null : it.id)}
                copy={copy}
                onTodo={(i) => void toggleTodo(it, i)}
                onPin={() => void patch(it.id, { pinned: !it.pinned })}
                onRetitle={(title) => void patch(it.id, { title })}
                onRedo={() => void organize(it, true)}
                onDelete={() => void remove([it])}
                aiReady={!!rt?.sample && !aiOff}
              />
            ))}
          </section>
        ))}
      </main>

      {picked && (
        <div className="pickbar" role="toolbar" aria-label="选中的条目">
          <span className="pick-n">已选 {picked.size} 条</span>
          <div className="pick-a">
            <button type="button" className="btn solid" disabled={!picked.size}
              onClick={() => copy(manyText(pickedItems), 'many-text', ` ${picked.size} 条整理版`)}>复制整理版</button>
            <button type="button" className="btn" disabled={!picked.size}
              onClick={() => copy(manyAi(pickedItems), 'many-ai', ` ${picked.size} 条给 AI`)}>复制给 AI</button>
            <button type="button" className="btn quiet" disabled={!picked.size}
              onClick={() => { void remove(pickedItems); setPicked(new Set()) }}>删除</button>
          </div>
        </div>
      )}

      <div className={'toast-wrap' + (picked ? ' up' : '')} aria-live="polite">
        {toast && (
          <div className="toast" key={toast.id}>
            <span>{toast.msg}</span>
            {toast.undo && <button type="button" onClick={() => { toast.undo?.(); setToast(null) }}>撤销</button>}
          </div>
        )}
      </div>

      <footer className="foot">
        <span>{rt?.store.mode === 'cloud' ? '存在你的 Claude 账号里，只有你看得到。' : '存在这台设备的浏览器里，不上传。'}</span>
        <span className="ver">{__BUILD_SHA__ === 'offline' ? '单文件版' : `v${__BUILD_SHA__}`}</span>
      </footer>
    </div>
  )
}

// ---------------------------------------------------------------- 一张卡

interface CardProps {
  it: Item
  now: number
  open: boolean
  copied: string | null
  copy: (text: string, key: string, what: string) => void
  onToggle: () => void
  example?: boolean
  picking?: boolean
  picked?: boolean
  onPick?: () => void
  onTodo?: (i: number) => void
  onPin?: () => void
  onRetitle?: (t: string) => void
  onRedo?: () => void
  onDelete?: () => void
  aiReady?: boolean
}

function Card(p: CardProps) {
  const { it, open, copied, copy } = p
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(it.title)
  const [showRaw, setShowRaw] = useState(false)
  useEffect(() => { if (!editing) setTitle(it.title) }, [it.title, editing])
  useEffect(() => { if (!open) { setEditing(false); setShowRaw(false) } }, [open])

  // 整理中卡太久（刷新过、或者那次调用丢了）：别一直转圈，给她一个按钮
  const stale = it.status === 'pending' && p.now - it.updatedAt > 90_000
  const busy = it.status === 'pending' && !stale
  const k = (s: string) => `${it.id}:${s}`
  const done = (s: string) => copied === k(s)
  const chips = it.fields.slice(0, 3)

  const saveTitle = () => {
    setEditing(false)
    const t = title.trim()
    if (t && t !== it.title) p.onRetitle?.(t)
  }

  return (
    <article
      id={'c-' + it.id}
      className={'card' + (open ? ' open' : '') + (p.picked ? ' picked' : '') + (busy ? ' busy' : '')}
      data-k={it.kind}
      data-status={it.status}
    >
      <div className="card-head">
        {p.picking && (
          <button type="button" className={'tick' + (p.picked ? ' on' : '')} aria-pressed={p.picked} aria-label="选中这条" onClick={p.onPick}>
            {p.picked && <CheckIcon />}
          </button>
        )}
        <span className="kind">{KINDS[it.kind]}</span>
        {p.example && <span className="badge">示例</span>}
        {it.pinned && <span className="badge">置顶</span>}
        {busy && <span className="busy-t"><i aria-hidden="true" />Claude 在整理</span>}
        <span className="when">{p.example ? '' : stamp(it.createdAt, p.now)}</span>
        {!p.picking && (
          <button
            type="button"
            className={'copy-ic' + (done('text') ? ' done' : '')}
            aria-label="复制整理版"
            onClick={() => copy(asText(it), k('text'), '整理版')}
          >
            {done('text') ? <CheckIcon /> : <CopyIcon />}
          </button>
        )}
      </div>

      {editing ? (
        <input
          id={'t-' + it.id}
          className="title-in"
          value={title}
          autoFocus
          onChange={(e) => setTitle(e.target.value)}
          onBlur={saveTitle}
          onKeyDown={(e) => { if (e.key === 'Enter') saveTitle(); if (e.key === 'Escape') { setTitle(it.title); setEditing(false) } }}
          aria-label="标题"
        />
      ) : (
        <button type="button" className="card-main" aria-expanded={open} onClick={p.picking ? p.onPick : p.onToggle}>
          <h3>{it.title}</h3>
          {it.summary ? <p>{it.summary}</p> : busy ? <p className="dim">{it.raw.replace(/\s+/g, ' ').slice(0, 60)}</p> : null}
        </button>
      )}

      {!open && chips.length > 0 && (
        <div className="chips">
          {chips.map((f, i) => (
            <button key={i} type="button" className={'chip' + (done('f' + i) ? ' done' : '')}
              onClick={() => (p.picking ? p.onPick?.() : copy(f.value, k('f' + i), `「${f.label}」`))}
              aria-label={`复制${f.label}：${f.value}`}>
              <span className="chip-l">{f.label}</span>
              <span className="chip-v">{done('f' + i) ? '已复制' : f.value}</span>
            </button>
          ))}
          {it.fields.length > 3 && !p.picking && (
            <button type="button" className="chip more" onClick={p.onToggle}>还有 {it.fields.length - 3} 项</button>
          )}
        </div>
      )}

      {open && (
        <div className="detail">
          {it.note && <p className="note">{it.note}</p>}

          {it.fields.length > 0 && (
            <div className="rows" role="list">
              {it.fields.map((f, i) => (
                <button key={i} type="button" role="listitem" className={'row' + (done('f' + i) ? ' done' : '')}
                  onClick={() => copy(f.value, k('f' + i), `「${f.label}」`)}>
                  <span className="row-l">{f.label}</span>
                  <span className="row-v">{f.value}</span>
                  <span className="row-c" aria-hidden="true">{done('f' + i) ? '已复制' : '复制'}</span>
                </button>
              ))}
            </div>
          )}

          {it.todos.length > 0 && (
            <div className="todos">
              <h4>要做的</h4>
              {it.todos.map((t, i) => (
                <label key={i} className={'todo' + (t.done ? ' did' : '')}>
                  <input id={`td-${it.id}-${i}`} type="checkbox" checked={t.done} disabled={p.example}
                    onChange={() => p.onTodo?.(i)} />
                  <span>{t.text}</span>
                </label>
              ))}
            </div>
          )}

          {it.tags.length > 0 && (
            <p className="tags">{it.tags.map((t) => <span key={t}>#{t}</span>)}</p>
          )}

          {it.prompt && (
            <button type="button" className={'ask' + (done('ai') ? ' done' : '')}
              onClick={() => copy(asAi(it), k('ai'), '给 AI 的版本')}>
              <span className="ask-l">{done('ai') ? '已复制 · 去 AI 那儿粘贴' : '下一步可以这样问 AI'}</span>
              <span className="ask-t">{it.prompt}</span>
            </button>
          )}

          <div className="raw">
            <button type="button" className="raw-t" aria-expanded={showRaw} onClick={() => setShowRaw((s) => !s)}>
              {showRaw ? '收起原文 ▴' : '看原文 ▾'}
            </button>
            {showRaw && <pre>{it.raw}</pre>}
          </div>

          <div className="copies">
            <button type="button" className={'btn solid' + (done('text') ? ' done' : '')} onClick={() => copy(asText(it), k('text'), '整理版')}>
              {done('text') ? '✓ 已复制' : '复制整理版'}
            </button>
            <button type="button" className={'btn' + (done('ai') ? ' done' : '')} onClick={() => copy(asAi(it), k('ai'), '给 AI 的版本')}>
              {done('ai') ? '✓ 已复制' : '复制给 AI'}
            </button>
            <button type="button" className={'btn' + (done('raw') ? ' done' : '')} onClick={() => copy(it.raw, k('raw'), '原文')}>
              {done('raw') ? '✓ 已复制' : '复制原文'}
            </button>
          </div>

          {!p.example && (
            <div className="acts">
              <button type="button" onClick={() => setEditing(true)}>改标题</button>
              {p.aiReady && it.status !== 'pending' && <button type="button" onClick={p.onRedo}>重新整理</button>}
              {stale && p.aiReady && <button type="button" onClick={p.onRedo}>重新整理</button>}
              <button type="button" onClick={p.onPin}>{it.pinned ? '取消置顶' : '置顶'}</button>
              <button type="button" className="danger" onClick={p.onDelete}>删除</button>
            </div>
          )}
        </div>
      )}
    </article>
  )
}

// ---------------------------------------------------------------- 新版本（只在 GitHub Pages 装成 App 时有）

function UpdateBanner() {
  const { ready, applying } = useUpdate()
  if (!ready) return null
  return (
    <button type="button" className="update-pill" disabled={applying} onClick={applyUpdate}>
      {applying ? '正在换……' : <><b>有新版本</b> 点一下换过来</>}
    </button>
  )
}

// ---------------------------------------------------------------- 图标

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="8.5" y="8.5" width="11" height="11" rx="2.5" />
      <path d="M15.5 8.5V6.5a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2" />
    </svg>
  )
}
function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 12.5 10 17.5 19 7" />
    </svg>
  )
}
function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4 4" />
    </svg>
  )
}
