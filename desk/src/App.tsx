import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  FALLBACK_ASK, IMG_PLACEHOLDER, KINDS, aiPrompt, asAi, asAiWith, askLabel, asksFor, asText, dayGroup, fromAi, manyAi, manyText, matches, newId, quick, stamp, tidy,
  type Ask, type Item, type Kind,
} from './lib/card'
import { askPrompt, pick, pieces, plainAnswer } from './lib/ask'
import { isImage, shrink, toPng } from './lib/image'
import { loadAsks, merge, mergeAsks, openStore, readBackup, saveAsks, toBackup, type Store } from './lib/store'
import { eventOf, personOf, toIcs, toVcf } from './lib/send'
import * as claude from './lib/ai'
import { copyImage, copyText } from './lib/copy'
import { applyUpdate, useUpdate } from './lib/update'
import { EXAMPLES } from './examples'

/**
 * 随手拾 —— 随手复制的信息，贴进来就被整理成一张卡片，收着、找得到、随时拿出去用。
 *
 * 三件事，按她用的顺序：
 *   收：粘贴即收下。不用点「保存」，不用选类型。文字、截图都行。
 *   整：本地先认一遍 —— 时间、地点、电话、金额、链接、待办，按类型配好「拿去问 AI」的那一句。
 *       在设置里填了自己的 Claude API Key 的话，再交给 Claude 读懂重写（截图也能读）。
 *   用：一张卡上能复制的东西都是按钮 —— 一个字段、整理版、给 AI 的版本、原文、截图；
 *       多选几张，合成一段再复制。
 *
 * 全部存在这台设备上（lib/store.ts）。不填 Key 就一个请求都不往外发。
 */

type Toast = { msg: string; action?: { label: string; run: () => void }; id: number }
type Answer = { q: string; text: string; busy: boolean; chosen: Item[]; err?: string }
/** 这两种错误说明 Key 本身用不了：别每收一条都再撞一次，等她去设置里换 */
const KEY_DEAD = new Set(['bad_key', 'no_access'])
const SHOT_LOCAL = '没开 Claude，读不了图里的字 ——「复制图片」贴给任何一个 AI 都行；或者在「设置」里填上 API Key'

const touch = typeof window !== 'undefined' && !!window.matchMedia?.('(pointer: coarse)').matches
const MOD = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? '⌘' : 'Ctrl'

export function App() {
  const [store, setStore] = useState<Store | null>(null)
  const [items, setItems] = useState<Item[] | null>(null)
  const [key, setKey] = useState(() => claude.loadKey())
  const [keyBad, setKeyBad] = useState(false)
  const [settings, setSettings] = useState(false)
  /** 她自己存的问法：每张卡的「换个问法」里都有 */
  const [myAsks, setMyAsks] = useState<Ask[]>(() => loadAsks())
  const updateAsks = (a: Ask[]) => { setMyAsks(a); saveAsks(a) }
  const [open, setOpen] = useState<string | null>(null)
  const [kind, setKind] = useState<Kind | 'all'>('all')
  const [q, setQ] = useState('')
  const [searching, setSearching] = useState(false)
  const [picked, setPicked] = useState<Set<string> | null>(null)
  const [toast, setToast] = useState<Toast | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [now, setNow] = useState(() => Date.now())
  const [ask, setAsk] = useState<Answer | null>(null)
  const askCtl = useRef<AbortController | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const storeRef = useRef<Store | null>(null)
  const readyWaiters = useRef<((s: Store) => void)[]>([])
  const itemsRef = useRef<Item[]>([])
  itemsRef.current = items ?? []
  /** 能不能叫 Claude：填了 Key、而且这个 Key 没被判死 */
  const aiKey = key && !keyBad ? key : ''
  const keyRef = useRef('')
  keyRef.current = aiKey
  const capRef = useRef<HTMLTextAreaElement>(null)

  // ---------------------------------------------------------------- 连上

  useEffect(() => {
    let live = true
    void openStore().then((s) => {
      if (!live) return
      storeRef.current = s
      setStore(s)
      readyWaiters.current.splice(0).forEach((f) => f(s))
    })
    return () => { live = false }
  }, [])
  useEffect(() => {
    if (!store) return
    return store.subscribe(setItems)
  }, [store])
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000)
    return () => clearInterval(t)
  }, [])

  const whenReady = () => (storeRef.current ? Promise.resolve(storeRef.current) : new Promise<Store>((r) => readyWaiters.current.push(r)))

  // ---------------------------------------------------------------- 提示

  const say = useCallback((msg: string, action?: Toast['action']) => setToast({ msg, action, id: Date.now() }), [])
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), toast.action ? 6000 : 2200)
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
  /** 截图卡：把图本身复制出去，贴进任何一个 AI 的对话框 */
  const copyShot = (it: Item, key: string) => {
    if (!it.img) return
    void copyImage(toPng(it.img)).then((ok) => {
      if (!ok) { say('这个浏览器不让复制图片 —— 长按图片存下来'); return }
      setCopied(key)
      window.clearTimeout(copyTimer.current)
      copyTimer.current = window.setTimeout(() => setCopied(null), 1600)
      say('已复制图片 · 去 AI 那儿粘贴')
    })
  }

  // ---------------------------------------------------------------- 整理

  const patch = async (id: string, p: Partial<Item>) => {
    try { await storeRef.current?.patch(id, { ...p, updatedAt: Date.now() }) } catch { /* 写不进去：下次刷新按盘上的样子 */ }
  }

  /**
   * 交给 Claude 整理一条。没开（没填 Key / Key 用不了）就停在本地整理 ——
   * 本地那一遍在收下的时候已经做完了，卡上本来就有东西。
   * again：她点了「重新整理」，让 Claude 想得仔细一点
   */
  const organize = async (it: Item, again = false) => {
    const k = keyRef.current
    const shot = !!it.img
    if (!k) {
      await patch(it.id, { status: 'local', note: shot && it.raw === IMG_PLACEHOLDER ? SHOT_LOCAL : '' })
      return
    }
    if (again) await patch(it.id, { status: 'pending', note: '' })
    try {
      const j = await claude.organize(k, aiPrompt(shot ? '' : it.raw, new Date(), shot), shot ? it.img : undefined, again ? 'medium' : 'low')
      const card = fromAi(j)
      if (!card) throw new claude.AiError('invalid_json')
      // 读文字时不许 Claude 改原文；读截图时，它转写出来的字就是原文
      const { raw, ...rest } = card
      await patch(it.id, { ...rest, ...(shot && raw ? { raw } : {}), status: 'done', note: '' })
    } catch (e) {
      const code = e instanceof claude.AiError ? e.code : 'failed'
      if (code === 'cancelled') return
      if (KEY_DEAD.has(code)) setKeyBad(true)
      await patch(it.id, { status: 'failed', note: claude.noteFor(code) })
    }
  }

  // ---------------------------------------------------------------- 收

  const add = async (text: string) => {
    const raw = tidy(text)
    if (!raw) { say('剪贴板里没有文字'); return }
    const st = await whenReady()
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
      status: keyRef.current ? 'pending' : 'local',
      pinned: false,
      ...quick(raw),
    }
    setKind('all'); setQ(''); setSearching(false); setOpen(it.id)
    try {
      await st.put(it)
    } catch (e) {
      const code = (e as { code?: string })?.code
      say(code === 'quota_exceeded' ? '这台设备的空间满了，删掉一些旧的再收' : '没存上，再贴一次试试')
      return
    }
    if (it.status === 'pending') void organize(it)
  }
  const addRef = useRef(add)
  addRef.current = add

  /**
   * 收一张截图：压一份存进卡片。开了 Claude 就让它读图里的字；
   * 没开也收 —— 图就在卡上，「复制图片」能贴给任何一个 AI
   */
  const addImage = async (file: Blob) => {
    const st = await whenReady()
    let img: string
    try { img = await shrink(file) } catch { say('这张图读不了，换一张试试'); return }
    const t = Date.now()
    const d = new Date(t)
    const ai = !!keyRef.current
    const it: Item = {
      id: newId(), raw: IMG_PLACEHOLDER, createdAt: t, updatedAt: t, status: ai ? 'pending' : 'local', pinned: false,
      kind: 'other', title: ai ? '一张截图' : `截图 · ${d.getMonth() + 1}月${d.getDate()}日 ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`,
      summary: '', fields: [], todos: [], tags: [], prompt: '', img,
      ...(ai ? {} : { note: SHOT_LOCAL }),
    }
    setKind('all'); setQ(''); setSearching(false); setOpen(it.id)
    try {
      await st.put(it)
    } catch (e) {
      const code = (e as { code?: string })?.code
      say(code === 'quota_exceeded' ? '这台设备的空间满了，删掉一些旧的再收' : '没存上，再试一次')
      return
    }
    if (ai) void organize(it)
  }
  const addImageRef = useRef(addImage)
  addImageRef.current = addImage

  // 拖进来：图就当截图收，字就当文字收
  useEffect(() => {
    const over = (e: DragEvent) => { if (e.dataTransfer?.types.includes('Files') || e.dataTransfer?.types.includes('text/plain')) e.preventDefault() }
    const drop = (e: DragEvent) => {
      const dt = e.dataTransfer
      if (!dt) return
      const imgs = [...dt.files].filter(isImage)
      const text = dt.getData('text/plain')
      if (!imgs.length && !text) return
      e.preventDefault()
      imgs.forEach((f) => void addImageRef.current(f))
      if (!imgs.length && text) void addRef.current(text)
    }
    window.addEventListener('dragover', over)
    window.addEventListener('drop', drop)
    return () => { window.removeEventListener('dragover', over); window.removeEventListener('drop', drop) }
  }, [])

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
      const imgs = [...(e.clipboardData?.files ?? [])].filter(isImage)
      const text = e.clipboardData?.getData('text/plain') ?? ''
      e.preventDefault()
      setDraft('')
      if (touch) capRef.current?.blur() // 收下了就把键盘收起来，让她看到卡片
      if (imgs.length) { imgs.forEach((f) => void addImageRef.current(f)); return }
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
    const st = storeRef.current
    if (!st || !list.length) return
    await Promise.all(list.map((it) => st.remove(it.id).catch(() => {})))
    if (list.some((it) => it.id === open)) setOpen(null)
    say(list.length > 1 ? `删掉了 ${list.length} 条` : '删掉了', {
      label: '撤销', run: () => { void st.putMany(list).catch(() => {}) },
    })
  }

  const toggleTodo = (it: Item, i: number) =>
    patch(it.id, { todos: it.todos.map((t, j) => (j === i ? { ...t, done: !t.done } : t)) })

  // ---------------------------------------------------------------- 问

  const doAsk = async () => {
    const k = keyRef.current
    const question = q.trim()
    if (!k || !question) return
    askCtl.current?.abort()
    const ctl = new AbortController()
    askCtl.current = ctl
    const chosen = pick(question, itemsRef.current)
    const mine = (a: Answer | null) => !!a && a.q === question && askCtl.current === ctl
    setAsk({ q: question, text: '', busy: true, chosen })
    try {
      const text = await claude.ask(k, askPrompt(question, chosen), (t) => setAsk((a) => (mine(a) ? { ...a!, text: t } : a)), ctl.signal)
      setAsk((a) => (mine(a) ? { ...a!, text, busy: false } : a))
    } catch (e) {
      const { code, text } = (e ?? {}) as { code?: claude.AiErrCode; text?: string }
      if (code && KEY_DEAD.has(code)) setKeyBad(true)
      const err =
        code === 'cancelled' ? undefined
        : code === 'bad_key' || code === 'no_access' ? 'API Key 用不了，问不了 —— 去「设置」里看看。上面的搜索照样能用'
        : code === 'rate_limited' || code === 'overloaded' ? 'Claude 这会儿忙，过一会儿再问'
        : code === 'offline' ? '没连上网，问不了 —— 上面的搜索照样能用'
        : code === 'no_credit' ? 'API 账户余额不足，充值后再问'
        : code === 'too_large' ? '收的东西太多了，换个更具体的问法试试'
        : '没问成，再问一次试试'
      setAsk((a) => (mine(a) ? { ...a!, text: text ?? a!.text, busy: false, err } : a))
    }
  }
  const stopAsk = () => { askCtl.current?.abort() }
  const closeSearch = () => { setSearching(false); setQ(''); askCtl.current?.abort(); setAsk(null) }
  useEffect(() => () => askCtl.current?.abort(), [])

  const jumpTo = (id: string) => {
    setQ(''); setKind('all'); setOpen(id)
    requestAnimationFrame(() => document.getElementById('c-' + id)?.scrollIntoView({ block: 'start', behavior: 'smooth' }))
  }

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
  // 示例卡照实演示：没开 Claude 时就是本地整理出来的样子，贴进来真的会变成这样
  const examples = useMemo(() => (aiKey ? EXAMPLES : EXAMPLES.map((e) => ({ ...e, ...quick(e.raw), status: 'local' as const }))), [aiKey])
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
        else if (searching) closeSearch()
      } else if (e.key === '/' && !inField) {
        e.preventDefault()
        setSearching(true)
      }
    }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [picked, open, searching])

  const canAsk = !!aiKey && lib.length > 0

  const status =
    !store ? '正在打开你的收藏…'
    : keyBad ? 'API Key 用不了，先做基础整理 —— 去设置里看看'
    : aiKey ? '粘贴即收下 · Claude 帮你整理'
    : '粘贴即收下 · 只存在这台设备'

  // ---------------------------------------------------------------- 导出 / 导入

  const doExport = () => {
    const d = new Date()
    const p = (n: number) => String(n).padStart(2, '0')
    saveFile(`suishou-backup-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}.json`, 'application/json', toBackup(lib, d, myAsks))
    say(`导出了 ${lib.length} 条`)
  }
  const doImport = async (f: File) => {
    const st = await whenReady()
    let incoming: { items: Item[]; asks: Ask[] }
    try { incoming = readBackup(await f.text()) } catch { say('这不是随手拾的备份文件'); return }
    const { add, skipped } = merge(itemsRef.current, incoming.items)
    try { await st.putMany(add) } catch { say('没导进去 —— 这台设备的空间可能满了'); return }
    const asks = mergeAsks(myAsks, incoming.asks)
    const newAsks = asks.length - myAsks.length
    if (newAsks) updateAsks(asks)
    say((add.length ? `导入了 ${add.length} 条${skipped ? `，${skipped} 条已经有了` : ''}` : `都已经有了（${skipped} 条）`) + (newAsks ? `，问法 ${newAsks} 个` : ''))
  }
  /** 放到别处：日程 → 日历文件，名片 → 联系人文件。手机上点开就弹「添加」 */
  const send = (it: Item, what: 'ics' | 'vcf') => {
    if (what === 'ics') {
      const ev = eventOf(it)
      if (!ev) return
      saveFile(`suishou-${it.id}.ics`, 'text/calendar;charset=utf-8', toIcs(it, ev))
      say('日历文件好了 —— 点开它就加进日历')
    } else {
      const person = personOf(it)
      if (!person) return
      saveFile(`suishou-${it.id}.vcf`, 'text/vcard;charset=utf-8', toVcf(person, it))
      say('联系人文件好了 —— 点开它就存进通讯录')
    }
  }

  // 安卓上装成 App 后，别的 App 里「分享」到这里：带着 ?text= / ?url= 打开，当场收下
  useEffect(() => {
    const u = new URLSearchParams(location.search)
    const parts = uniqParts([u.get('title'), u.get('text'), u.get('url')])
    if (!parts.length) return
    history.replaceState(null, '', location.pathname)
    void addRef.current(parts.join('\n'))
  }, [])

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
              onClick={() => (searching ? closeSearch() : setSearching(true))}>
              <SearchIcon />
            </button>
          )}
          {lib.length > 0 && (
            <button type="button" className="ghost txt" aria-pressed={!!picked}
              onClick={() => setPicked((p) => (p ? null : new Set()))}>
              {picked ? '完成' : '选择'}
            </button>
          )}
          {!picked && (
            <button type="button" className={'ghost' + (keyBad ? ' warn-dot' : '')} aria-label="设置" onClick={() => setSettings(true)}>
              <GearIcon />
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
            enterKeyHint={canAsk ? 'send' : 'search'}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && canAsk) { e.preventDefault(); void doAsk() } }}
            placeholder={canAsk ? '搜，或者直接问：Lily 的电话？这周有哪些会？' : '搜标题、原文、电话、地点……'}
            aria-label="搜索或提问"
          />
        </div>
      )}

      {searching && canAsk && q.trim() && !(ask && ask.q === q.trim() && !ask.err) && (
        <button type="button" className="ask-go" onClick={() => void doAsk()}>
          <SparkIcon />
          <span>问 Claude：<b>{q.trim()}</b></span>
        </button>
      )}

      {ask && (
        <section className="answer" aria-live="polite" aria-label="Claude 的回答">
          <div className="answer-h">
            <span className="answer-q">{ask.q}</span>
            {ask.busy ? (
              <button type="button" className="mini" onClick={stopAsk}>停止</button>
            ) : ask.text ? (
              <button type="button" className={'mini' + (copied === 'ask' ? ' ok' : '')}
                onClick={() => copy(plainAnswer(ask.text, ask.chosen), 'ask', '回答')}>
                {copied === 'ask' ? '已复制' : '复制回答'}
              </button>
            ) : null}
            <button type="button" className="mini x" aria-label="关掉回答" onClick={() => { stopAsk(); setAsk(null) }}>✕</button>
          </div>
          <div className="answer-b">
            {!ask.text && ask.busy && <p className="answer-wait">正在翻你收的 {ask.chosen.length} 条……</p>}
            {ask.text && (() => {
              const ps = pieces(ask.text, ask.chosen.length)
              // 出处按第一次出现的顺序编 1、2、3 —— 不用提示里那一长串的原编号
              const order: number[] = []
              for (const pc of ps) if ('ref' in pc && !order.includes(pc.ref)) order.push(pc.ref)
              return (
                <>
                  <p className="answer-t">
                    {ps.map((pc, i) =>
                      'ref' in pc ? <span key={i} className="ref" aria-label={`出处 ${order.indexOf(pc.ref) + 1}`}>{order.indexOf(pc.ref) + 1}</span>
                        : <span key={i}>{pc.text}</span>,
                    )}
                  </p>
                  {order.length > 0 && !ask.busy && (
                    <div className="srcs" aria-label="出处">
                      {order.map((ref, i) => {
                        const it = ask.chosen[ref - 1]
                        return (
                          <button key={ref} type="button" className="src" data-k={it.kind} onClick={() => jumpTo(it.id)}>
                            <span className="ref">{i + 1}</span>
                            <span className="src-k">{KINDS[it.kind]}</span>
                            <span className="src-t">{it.title}</span>
                            <span className="src-go" aria-hidden="true">↗</span>
                          </button>
                        )
                      })}
                    </div>
                  )}
                </>
              )
            })()}
            {ask.err && <p className="answer-err">{ask.err}</p>}
          </div>
        </section>
      )}

      {!picked && !searching && (
        <>
          <section className="capture" aria-label="收下一条">
            <textarea
              id="capture"
              ref={capRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); takeDraft() } }}
              placeholder={touch ? '长按这里，粘贴进来' : `粘贴到这里，或在页面任何地方按 ${MOD}+V`}
              rows={draft ? Math.min(8, draft.split('\n').length + 1) : 1}
              aria-label="粘贴或输入要收下的内容"
            />
            {draft.trim() ? (
              <button type="button" className="take" onClick={takeDraft}>收下</button>
            ) : (
              <>
                <input
                  id="shot"
                  ref={fileRef}
                  type="file"
                  accept="image/*"
                  multiple
                  hidden
                  onChange={(e) => {
                    const fs = [...(e.target.files ?? [])].filter(isImage)
                    fs.forEach((f) => void addImage(f))
                    e.target.value = ''
                  }}
                />
                <button type="button" className="shot-btn" aria-label="收一张截图" onClick={() => fileRef.current?.click()}>
                  <ImageIcon />
                  <span>截图</span>
                </button>
              </>
            )}
          </section>
          <p className={'cap-hint' + (aiKey ? ' ai' : '')}>{status}</p>
        </>
      )}

      {lib.length > 0 && (
        <nav className="kinds" aria-label="按类型看">
          <button type="button" className={kind === 'all' ? 'on' : ''} aria-pressed={kind === 'all'} onClick={() => setKind('all')}>
            <span className="k-in">全部 <i>{lib.length}</i></span>
          </button>
          {(Object.keys(KINDS) as Kind[]).filter((k) => counts.get(k)).map((k) => (
            <button key={k} type="button" className={kind === k ? 'on' : ''} aria-pressed={kind === k} data-k={k} onClick={() => setKind(kind === k ? 'all' : k)}>
              <span className="k-in">{KINDS[k]} <i>{counts.get(k)}</i></span>
            </button>
          ))}
        </nav>
      )}

      <main className="list">
        {items === null && <div className="loading" aria-hidden="true"><i /><i /><i /></div>}

        {empty && (
          <>
            <p className="ex-h">示例 · 贴进来的东西会变成这样。收下第一条后这些就不见了。</p>
            {examples.map((it) => (
              <Card key={it.id} it={it} example open={open === it.id} now={now} copied={copied} myAsks={myAsks}
                onToggle={() => setOpen(open === it.id ? null : it.id)} copy={copy} onSend={send} />
            ))}
          </>
        )}

        {/* 刚问过同一句、Claude 已经在上面回答了：下面就别再说「没找到」，两句话打架 */}
        {!empty && items !== null && shown.length === 0 && !(ask && ask.q === q.trim()) && (
          <p className="none">
            {!q ? '这一类还没有' : canAsk ? `没有卡片同时包含「${q}」—— 点上面「问 Claude」试试` : `没找到「${q}」`}
          </p>
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
                copyShot={copyShot}
                myAsks={myAsks}
                onSend={send}
                aiReady={!!aiKey}
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
            {toast.action && <button type="button" onClick={() => { toast.action?.run(); setToast(null) }}>{toast.action.label}</button>}
          </div>
        )}
      </div>

      {settings && (
        <Settings
          count={lib.length}
          asks={myAsks}
          onAsks={updateAsks}
          apiKey={key}
          keyBad={keyBad}
          onKey={(k) => { setKey(k); setKeyBad(false) }}
          onExport={doExport}
          onImport={(f) => void doImport(f)}
          onClose={() => setSettings(false)}
        />
      )}

      <footer className="foot">
        <span>{aiKey ? '存在这台设备上。开着 Claude 整理：收下的内容会直接发给 Anthropic。' : '存在这台设备的浏览器里，不上传。'}</span>
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
  copyShot?: (it: Item, key: string) => void
  myAsks?: Ask[]
  onSend?: (it: Item, what: 'ics' | 'vcf') => void
  aiReady?: boolean
}

function Card(p: CardProps) {
  const { it, open, copied, copy } = p
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(it.title)
  const [showRaw, setShowRaw] = useState(false)
  const [bigShot, setBigShot] = useState(false)
  useEffect(() => { if (!editing) setTitle(it.title) }, [it.title, editing])
  useEffect(() => { if (!open) { setEditing(false); setShowRaw(false) } }, [open])

  // 整理中卡太久（刷新过、或者那次调用丢了）：别一直转圈，给她一个按钮
  const stale = it.status === 'pending' && p.now - it.updatedAt > 90_000
  const busy = it.status === 'pending' && !stale
  const k = (s: string) => `${it.id}:${s}`
  const done = (s: string) => copied === k(s)
  const chips = it.fields.slice(0, 3)
  /** 截图、图里的字还没读出来 */
  const textless = !!it.img && it.raw === IMG_PLACEHOLDER
  const alts = useMemo(() => (open && !textless ? asksFor(it, p.myAsks) : []), [open, textless, it, p.myAsks])
  const ev = useMemo(() => (open && p.onSend ? eventOf(it) : null), [open, it, p.onSend])
  const person = useMemo(() => (open && p.onSend ? personOf(it) : null), [open, it, p.onSend])

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
        {it.img && <span className="badge">截图</span>}
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
        <button type="button" className={'card-main' + (it.summary || busy ? '' : ' solo')} aria-expanded={open} onClick={p.picking ? p.onPick : p.onToggle}>
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
              <span className="chip-in">
                <span className="chip-l">{f.label}</span>
                <span className="chip-v">{done('f' + i) ? '已复制' : f.value}</span>
              </span>
            </button>
          ))}
          {it.fields.length > 3 && !p.picking && (
            <button type="button" className="chip more" onClick={p.onToggle}><span className="chip-in">还有 {it.fields.length - 3} 项</span></button>
          )}
        </div>
      )}

      {open && (
        <div className="detail">
          {/* 「没开 Claude」那句：她已经开了，就别再说了（下面有「让 Claude 读图」） */}
          {it.note && !(p.aiReady && it.status === 'local') && <p className="note">{it.note}</p>}

          {it.img && (
            <div className="shot-wrap">
              <button type="button" className={'shot' + (bigShot ? ' big' : '')} onClick={() => setBigShot((b) => !b)}
                aria-label={bigShot ? '收起截图' : '看完整截图'}>
                <img src={it.img} alt="收进来的截图" />
              </button>
              {!textless && p.copyShot && (
                <button type="button" className={'shot-copy' + (done('img') ? ' done' : '')} onClick={() => p.copyShot?.(it, k('img'))}>
                  {done('img') ? '✓ 已复制' : '复制图片'}
                </button>
              )}
            </div>
          )}

          {it.fields.length > 0 && (
            <div className="rows" role="list">
              {it.fields.map((f, i) => (
                <button key={i} type="button" role="listitem" className={'row' + (done('f' + i) ? ' done' : '')}
                  onClick={() => copy(f.value, k('f' + i), `「${f.label}」`)}>
                  <span className="row-l">{f.label}</span>
                  <span className="row-v">{f.value}</span>
                  <span className="row-c" aria-hidden="true">{done('f' + i) ? '已复制' : <CopyIcon />}</span>
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

          {/* 拿去问 AI：卡上配好的那一句是主按钮，下面一排是换个问法 —— 所有「给 AI」的都在这一块 */}
          {!textless && (
            <div className="ai-box">
              <button type="button" className={'ask' + (done('ai') ? ' done' : '')}
                onClick={() => copy(asAi(it), k('ai'), '给 AI 的版本')}>
                <span className="ask-top">
                  <span className="ask-l"><SparkIcon />拿去问 AI</span>
                  <span className="ask-btn">{done('ai') ? '✓ 已复制' : '复制给 AI'}</span>
                </span>
                <span className="ask-t">{it.prompt || FALLBACK_ASK}</span>
              </button>
              {alts.length > 0 && (
                <div className="alts" aria-label="换个问法">
                  <span className="alts-h">换个问法</span>
                  {alts.map((a, i) => (
                    <button key={a.text} type="button" className={'alt' + (done('alt' + i) ? ' done' : '')} title={a.text}
                      onClick={() => copy(asAiWith(it, a.text), k('alt' + i), `「${a.label}」`)}>
                      {done('alt' + i) ? '已复制' : a.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 一排拿走：整理版 / 原文（截图卡是图）/ 日历 / 通讯录 */}
          <div className={'copies n' + (2 + (ev ? 1 : 0) + (person ? 1 : 0))}>
            {textless ? (
              <button type="button" className={'btn solid' + (done('img') ? ' done' : '')} onClick={() => p.copyShot?.(it, k('img'))}>
                {done('img') ? '✓ 已复制' : '复制图片'}
              </button>
            ) : (
              <button type="button" className={'btn solid' + (done('text') ? ' done' : '')} onClick={() => copy(asText(it), k('text'), '整理版')}>
                {done('text') ? '✓ 已复制' : '复制整理版'}
              </button>
            )}
            {textless ? (
              <button type="button" className={'btn' + (done('text') ? ' done' : '')} onClick={() => copy(asText(it), k('text'), '整理版')}>
                {done('text') ? '✓ 已复制' : '复制整理版'}
              </button>
            ) : (
              <button type="button" className={'btn' + (done('raw') ? ' done' : '')} onClick={() => copy(it.raw, k('raw'), '原文')}>
                {done('raw') ? '✓ 已复制' : '复制原文'}
              </button>
            )}
            {ev && (
              <button type="button" className="btn send" title={ev.due ? '把截止日加到日历' : undefined} onClick={() => p.onSend?.(it, 'ics')}>
                <CalIcon /><span>加到日历</span>
              </button>
            )}
            {person && (
              <button type="button" className="btn send" onClick={() => p.onSend?.(it, 'vcf')}>
                <PersonIcon /><span>存到通讯录</span>
              </button>
            )}
          </div>

          {/* 不常用的：一排安静的字 */}
          <div className="acts">
            {!textless && (
              <button type="button" className="raw-t" aria-expanded={showRaw} onClick={() => setShowRaw((s) => !s)}>
                {showRaw ? '收起原文' : it.img ? '图里的字' : '看原文'}
              </button>
            )}
            {!p.example && (
              <>
                <button type="button" onClick={() => setEditing(true)}>改标题</button>
                {p.aiReady && (it.status !== 'pending' || stale) && (
                  <button type="button" onClick={p.onRedo}>{it.status === 'local' ? (it.img ? '让 Claude 读图' : '让 Claude 整理') : '重新整理'}</button>
                )}
                <button type="button" onClick={p.onPin}>{it.pinned ? '取消置顶' : '置顶'}</button>
                <button type="button" className="danger" onClick={p.onDelete}>删除</button>
              </>
            )}
          </div>
          {showRaw && !textless && <div className="raw"><pre>{it.raw}</pre></div>}
        </div>
      )}
    </article>
  )
}

// ---------------------------------------------------------------- 存成文件

/** 让浏览器存一个文件。文件名用英文：有的浏览器碰到中文文件名直接存成「download」 */
function saveFile(name: string, type: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

// ---------------------------------------------------------------- 设置

/** 分享进来的标题 / 正文 / 链接：去掉重复的（很多 App 会把链接同时塞进 text） */
function uniqParts(xs: (string | null)[]): string[] {
  const out: string[] = []
  for (const x of xs) {
    const t = x?.trim()
    if (t && !out.some((o) => o.includes(t))) out.push(t)
  }
  return out
}

interface SettingsProps {
  count: number
  asks: Ask[]
  onAsks: (a: Ask[]) => void
  apiKey: string
  keyBad: boolean
  onKey: (k: string) => void
  onExport: () => void
  onImport: (f: File) => void
  onClose: () => void
}

function Settings(p: SettingsProps) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [newAsk, setNewAsk] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const boxRef = useRef<HTMLElement>(null)

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null
    boxRef.current?.focus()
    const on = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); p.onClose() } }
    window.addEventListener('keydown', on, true)
    return () => { window.removeEventListener('keydown', on, true); prev?.focus?.() }
  }, [])

  const say = (ok: boolean, text: string) => setMsg({ ok, text })
  const addAsk = () => {
    const text = newAsk.trim()
    if (!text) return
    p.onAsks(mergeAsks(p.asks, [{ text, label: askLabel(text) }]))
    setNewAsk('')
  }
  const why = (code: string) =>
    code === 'bad_key' ? '这个 Key 不对 —— 检查一下有没有复制完整'
    : code === 'no_access' ? '这个 Key 用不了 Claude（没有权限），换一个试试'
    : code === 'rate_limited' || code === 'overloaded' ? 'Claude 那边这会儿忙，过一会儿再试'
    : '没测成，再试一次'

  const save = async () => {
    const k = draft.trim()
    if (!k) return
    if (!claude.looksLikeKey(k)) { say(false, '这看起来不像 Claude 的 API Key（应该以 sk-ant- 开头）'); return }
    setBusy(true); setMsg(null)
    try {
      await claude.check(k)
      claude.saveKey(k)
      p.onKey(k)
      setDraft('')
      say(true, '已开启。之后收下的每一条都会交给 Claude 整理')
    } catch (e) {
      const code = e instanceof claude.AiError ? e.code : 'failed'
      if (code === 'offline') {
        // 没网测不了：先存上，有网时用得上
        claude.saveKey(k)
        p.onKey(k)
        setDraft('')
        say(true, '没连上网，测不了 —— 先存上了，有网时就会用')
      } else say(false, why(code))
    } finally { setBusy(false) }
  }

  const test = async () => {
    setBusy(true); setMsg(null)
    try { await claude.check(p.apiKey); p.onKey(p.apiKey); say(true, '能用 ✓') }
    catch (e) { const code = e instanceof claude.AiError ? e.code : 'failed'; say(false, code === 'offline' ? '没连上网' : why(code)) }
    finally { setBusy(false) }
  }

  const off = () => {
    claude.clearKey()
    p.onKey('')
    say(true, '已关掉，Key 已从这台设备删除。之后只做本地整理，不再往外发任何东西')
  }

  return (
    <div className="sheet-bg" onClick={(e) => { if (e.target === e.currentTarget) p.onClose() }}>
      <section className="sheet" role="dialog" aria-modal="true" aria-labelledby="set-h" tabIndex={-1} ref={boxRef}>
        <header className="sheet-h">
          <h2 id="set-h">设置</h2>
          <button type="button" className="ghost" aria-label="关闭设置" onClick={p.onClose}>✕</button>
        </header>

        <div className="set-sec">
          <h3>你的数据</h3>
          <p className="set-p">
            {p.count ? `${p.count} 条，` : ''}只存在这台设备的浏览器里，不上传到任何地方。换手机、换浏览器、清理浏览器数据之前，先导出一份备份。
          </p>
          <div className="set-row">
            <button type="button" className="btn solid" disabled={!p.count} onClick={p.onExport}>导出备份</button>
            <button type="button" className="btn" onClick={() => fileRef.current?.click()}>导入备份</button>
            <input
              id="import"
              ref={fileRef}
              type="file"
              accept="application/json,.json"
              hidden
              onChange={(e) => { const f = e.target.files?.[0]; if (f) p.onImport(f); e.target.value = '' }}
            />
          </div>
        </div>

        <div className="set-sec">
          <h3>我的问法</h3>
          <p className="set-p">常用的那句存在这里。每张卡展开后的「换个问法」里都会有它，点一下就连同这条信息一起复制，贴进哪家 AI 都行。</p>
          {p.asks.length > 0 && (
            <ul className="my-asks">
              {p.asks.map((a) => (
                <li key={a.text}>
                  <span className="my-ask-t"><b>{a.label}</b>{a.text}</span>
                  <button type="button" className="my-ask-x" aria-label={`删掉问法：${a.label}`}
                    onClick={() => p.onAsks(p.asks.filter((x) => x.text !== a.text))}>删掉</button>
                </li>
              ))}
            </ul>
          )}
          <div className="set-add">
            <input
              id="newask"
              className="set-in plain"
              value={newAsk}
              placeholder="比如：帮我改写成一条朋友圈"
              onChange={(e) => setNewAsk(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') addAsk() }}
              aria-label="新的问法"
            />
            <button type="button" className="btn" disabled={!newAsk.trim()} onClick={addAsk}>存下</button>
          </div>
        </div>

        <div className="set-sec">
          <h3>
            Claude 整理
            <span className={'pill' + (p.apiKey && !p.keyBad ? ' on' : p.keyBad ? ' bad' : '')}>
              {p.keyBad ? '用不了' : p.apiKey ? '已开' : '可选'}
            </span>
          </h3>
          <p className="set-p">
            不开也能用：本地会认出时间、地点、电话、金额、链接和待办。开了之后，Claude 会读懂每一条再整理，还能读截图里的字、在搜索框里直接提问。
          </p>
          {p.apiKey ? (
            <>
              <p className="key-on">你的 API Key：<code>sk-ant-…{p.apiKey.slice(-4)}</code></p>
              <div className="set-row">
                <button type="button" className="btn" disabled={busy} onClick={() => void test()}>{busy ? '在测…' : '测一下'}</button>
                <button type="button" className="btn quiet" onClick={off}>关掉并删除 Key</button>
              </div>
            </>
          ) : (
            <>
              <label className="set-l" htmlFor="apikey">你自己的 Claude API Key</label>
              <input
                id="apikey"
                className="set-in"
                type="password"
                autoComplete="off"
                autoCapitalize="off"
                spellCheck={false}
                placeholder="sk-ant-…"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') void save() }}
              />
              <div className="set-row">
                <button type="button" className="btn solid" disabled={busy || !draft.trim()} onClick={() => void save()}>
                  {busy ? '在测…' : '保存并开启'}
                </button>
              </div>
              <p className="set-fine">在 console.anthropic.com 的 API Keys 页面创建。按用量付费，记在你自己的账户上。</p>
            </>
          )}
          {msg && <p className={'set-msg' + (msg.ok ? ' ok' : ' no')} role="status">{msg.text}</p>}
          <p className="set-fine">
            Key 只存在这台设备上。开着的时候，你收下的内容（和截图、提问）会从这台设备直接发给 Anthropic（api.anthropic.com）处理，不经过其他任何服务器。偶尔主力模型不接某条时，Anthropic 会自动换一个模型接着整理。
          </p>
        </div>

        <p className="set-fine set-ver">随手拾 · {__BUILD_SHA__ === 'offline' ? '单文件版' : `v${__BUILD_SHA__}`} · 不联网也能用</p>
      </section>
    </div>
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

function GearIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
    </svg>
  )
}
function CalIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3.5" y="5" width="17" height="15.5" rx="3" />
      <path d="M3.5 10h17M8 3v4M16 3v4" />
    </svg>
  )
}
function PersonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8.5" r="3.8" />
      <path d="M4.5 20c1.2-3.6 4.1-5.5 7.5-5.5s6.3 1.9 7.5 5.5" />
    </svg>
  )
}
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
function ImageIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3.5" y="4.5" width="17" height="15" rx="3" />
      <circle cx="9" cy="10" r="1.8" />
      <path d="m20.5 16-4.5-4.5-8 8" />
    </svg>
  )
}
function SparkIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="currentColor">
      <path d="M12 2.5c.5 4.6 2.9 7 7.5 7.5-4.6.5-7 2.9-7.5 7.5-.5-4.6-2.9-7-7.5-7.5 4.6-.5 7-2.9 7.5-7.5Z" />
      <path d="M19 15.5c.2 1.8 1.2 2.8 3 3-1.8.2-2.8 1.2-3 3-.2-1.8-1.2-2.8-3-3 1.8-.2 2.8-1.2 3-3Z" opacity=".7" />
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
