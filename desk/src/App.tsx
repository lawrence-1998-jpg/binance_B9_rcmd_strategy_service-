import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { build, detect, intentInfo, intentsFor, type Intent, type Kind, type Target } from './lib/shape'
import { copyText } from './lib/copy'
import { ago, load, remember, save, type Item } from './lib/store'
import { applyUpdate, useUpdate } from './lib/update'
import { Preview } from './Preview'
import { EXAMPLES } from './examples'

/**
 * 随手：复制了什么就贴进来 → 自动认出是什么、拼好 Prompt → 拿走去粘贴。
 *
 * 整个页面只干这一件事。几条定下来的规矩：
 *
 * 1. **贴进来那一下就已经复制好了。** 贴入（按钮、⌘V、长按粘贴）会顺手把推荐的
 *    那一版写回剪贴板 —— 她切回 AI 直接粘贴，一下都不用多点。
 * 2. **选用途 = 复制。** 用途是一排大按钮，点哪个就复制哪个版本，
 *    不存在「先选、再找复制按钮」。
 * 3. **复制的入口到处都是，而且都够大：** 底部整条按钮、整张 Prompt 卡片、
 *    用途按钮、「去 ChatGPT / Claude…」（先复制再打开）、⌘↵。
 * 4. 永远说清楚剪贴板里现在是哪一版：改了一个字，按钮就从「✓ 已复制」
 *    变回「复制新版本」—— 不会让她带着旧的那版去粘贴。
 * 5. 什么都能撤销。换掉、清空、手改被覆盖，都给一个「撤销」。
 */

type ToastT = { msg: string; undo?: () => void; id: number }
type Snapshot = { material: string; picked: Intent | null; note: string; edited: string | null }

const OPENERS: { id: string; label: string; href: (q: string) => string }[] = [
  // ChatGPT 和 Claude 认 ?q= 预填；太长的放不进网址，就只打开、靠剪贴板
  { id: 'chatgpt', label: 'ChatGPT', href: (q) => (q ? `https://chatgpt.com/?q=${q}` : 'https://chatgpt.com/') },
  { id: 'claude', label: 'Claude', href: (q) => (q ? `https://claude.ai/new?q=${q}` : 'https://claude.ai/new') },
  { id: 'doubao', label: '豆包', href: () => 'https://www.doubao.com/chat/' },
  { id: 'deepseek', label: 'DeepSeek', href: () => 'https://chat.deepseek.com/' },
  { id: 'kimi', label: 'Kimi', href: () => 'https://www.kimi.com/' },
]
/** 网址预填的上限。再长，有的浏览器/网关会直接截断或拒绝 */
const Q_MAX = 6000

const touch = typeof window !== 'undefined' && window.matchMedia?.('(pointer: coarse)').matches
const mac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)
const MOD = mac ? '⌘' : 'Ctrl'

export function App() {
  const init = useMemo(load, [])
  const [material, setMaterial] = useState(init.draft.material)
  const [picked, setPicked] = useState<Intent | null>(init.draft.intent)
  const [note, setNote] = useState(init.draft.note)
  const [edited, setEdited] = useState<string | null>(init.draft.edited)
  const [target, setTarget] = useState<Target>(init.target)
  const [auto, setAuto] = useState(init.auto)
  const [history, setHistory] = useState<Item[]>(init.history)
  /** 最后一次真的写进剪贴板的那段文字。跟当前 Prompt 一比，就知道剪贴板是不是最新的 */
  const [copied, setCopied] = useState<string | null>(null)
  const [pulse, setPulse] = useState(0)
  const [toast, setToast] = useState<ToastT | null>(null)
  const [sheet, setSheet] = useState(false)
  const [editing, setEditing] = useState(false)

  const det = useMemo(() => detect(material), [material])
  const has = material.trim().length > 0
  const intents = useMemo(() => intentsFor(det), [det])
  const intent: Intent = picked && intents.some((i) => i.id === picked) ? picked : det.picks[0]
  const info = intentInfo(intent, det)
  const generated = useMemo(
    () => (has ? build({ material, intent, note, target, det }) : ''),
    [has, material, intent, note, target, det],
  )
  const prompt = edited ?? generated
  const fresh = has && copied === prompt

  const matRef = useRef<HTMLTextAreaElement>(null)

  // ---------------------------------------------------------------- 存

  const saved = useRef({ material, picked, note, edited, target, auto, history })
  saved.current = { material, picked, note, edited, target, auto, history }
  const flush = useCallback(() => {
    const s = saved.current
    save({ draft: { material: s.material, intent: s.picked, note: s.note, edited: s.edited }, history: s.history, target: s.target, auto: s.auto })
  }, [])
  useEffect(() => {
    const t = setTimeout(flush, 300)
    return () => clearTimeout(t)
  }, [material, picked, note, edited, target, auto, history, flush])
  useEffect(() => {
    // 她复制完马上切走，300ms 的防抖可能还没到 —— 切走那一刻补存一次
    const on = () => { if (document.visibilityState === 'hidden') flush() }
    document.addEventListener('visibilitychange', on)
    window.addEventListener('pagehide', flush)
    return () => { document.removeEventListener('visibilitychange', on); window.removeEventListener('pagehide', flush) }
  }, [flush])

  // ---------------------------------------------------------------- 提示条

  const say = useCallback((msg: string, undo?: () => void) => setToast({ msg, undo, id: Date.now() }), [])
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), toast.undo ? 6000 : 2600)
    return () => clearTimeout(t)
  }, [toast])

  const snapshot = (): Snapshot => ({ material, picked, note, edited })
  const restore = (s: Snapshot) => {
    setMaterial(s.material); setPicked(s.picked); setNote(s.note); setEdited(s.edited); setEditing(false)
  }

  // ---------------------------------------------------------------- 复制

  /**
   * 注意：这个函数必须在点击 / 粘贴事件里**同步**调起来。
   * copyText 的第一行就是 clipboard.writeText —— iOS 只认用户手势里发起的写入，
   * 前面垫一个 await 就会被拒。
   */
  const doCopy = useCallback(
    (text: string, it: { material: string; intent: Intent; note: string; kind: Kind }, quiet = false) => {
      if (!text) return Promise.resolve(false)
      return copyText(text).then((ok) => {
        if (ok) {
          setCopied(text)
          setPulse((n) => n + 1)
          try { navigator.vibrate?.(12) } catch { /* 不支持就算了 */ }
          setHistory((h) => remember(h, it))
        } else if (!quiet) {
          say('没复制上 —— 点「手改」，全选后自己复制')
        }
        return ok
      })
    },
    [say],
  )

  const copyNow = () => doCopy(prompt, { material, intent, note, kind: det.kind })

  // ---------------------------------------------------------------- 贴进来

  const takeIn = (raw: string, opts: { autoCopy: boolean }) => {
    const text = raw.replace(/\r\n?/g, '\n')
    if (!text.trim()) {
      say('剪贴板里没有文字')
      return
    }
    const prev = snapshot()
    setMaterial(text); setPicked(null); setNote(''); setEdited(null); setEditing(false)
    if (prev.material.trim() && prev.material !== text) say('换成新贴的这段了', () => restore(prev))
    if (opts.autoCopy && auto) {
      const d = detect(text)
      const p = build({ material: text, intent: d.picks[0], note: '', target, det: d })
      // 静默：自动复制失败不算错，底下那个大按钮还在
      void doCopy(p, { material: text, intent: d.picks[0], note: '', kind: d.kind }, true)
    } else {
      setCopied(null)
    }
  }
  const takeInRef = useRef(takeIn)
  takeInRef.current = takeIn

  const fromClipboard = async () => {
    const help = () => {
      matRef.current?.focus()
      say(touch ? '这台设备不让直接读剪贴板 —— 长按上面的框，点「粘贴」' : `直接按 ${MOD}+V 就能贴进来`)
    }
    if (!navigator.clipboard?.readText) return help()
    try {
      const t = await navigator.clipboard.readText()
      takeIn(t, { autoCopy: true })
    } catch {
      help()
    }
  }

  // ⌘V 在页面任何地方都算贴进来；在输入框里正常编辑时不抢
  useEffect(() => {
    const on = (e: ClipboardEvent) => {
      const el = e.target instanceof Element ? e.target : null
      const field = el?.closest('input, textarea, [contenteditable="true"]')
      const mat = el?.closest('[data-material]') as HTMLTextAreaElement | null
      if (field && !mat) return
      if (mat) {
        // 框是空的、或者整段选中了 —— 这是「换一段」；否则是在中间插字，是编辑
        const whole = !mat.value.trim() || (mat.selectionStart === 0 && mat.selectionEnd === mat.value.length)
        if (!whole) return
      }
      const text = e.clipboardData?.getData('text/plain') ?? ''
      e.preventDefault()
      takeInRef.current(text, { autoCopy: true })
    }
    document.addEventListener('paste', on)
    return () => document.removeEventListener('paste', on)
  }, [])

  // 从别的 App 分享过来（安卓 share target / iOS 快捷指令）：?text=…&url=…
  useEffect(() => {
    const q = new URLSearchParams(location.search)
    const parts = [q.get('title'), q.get('text'), q.get('url')].filter((x): x is string => !!x && !!x.trim())
    if (!parts.length) return
    // 安卓常把链接同时塞进 text 和 url，去个重
    const uniq = parts.filter((p, i) => !parts.slice(0, i).some((o) => o.includes(p.trim())))
    takeInRef.current(uniq.join('\n'), { autoCopy: false })
    window.history.replaceState(null, '', location.pathname + location.hash)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ---------------------------------------------------------------- 动作

  const choose = (id: Intent) => {
    const hadEdit = edited !== null
    const prev = snapshot()
    setPicked(id); setEdited(null); setEditing(false)
    const p = build({ material, intent: id, note, target, det })
    void doCopy(p, { material, intent: id, note, kind: det.kind })
    if (hadEdit) say('手改的那版被换掉了', () => restore(prev))
  }

  const clear = () => {
    const prev = snapshot()
    setMaterial(''); setPicked(null); setNote(''); setEdited(null); setEditing(false); setCopied(null)
    say('清空了', () => restore(prev))
    requestAnimationFrame(() => window.scrollTo({ top: 0 }))
  }

  const reuse = (it: Item) => {
    const prev = snapshot()
    setMaterial(it.material); setPicked(it.intent); setNote(it.note); setEdited(null); setEditing(false); setCopied(null)
    setSheet(false)
    say('拿回来了，点复制就能用', prev.material.trim() ? () => restore(prev) : undefined)
  }

  const forget = (id: string) => {
    const before = history
    setHistory((h) => h.filter((x) => x.id !== id))
    say('删掉了一条', () => setHistory(before))
  }

  const forgetAll = () => {
    const before = history
    setHistory([])
    say('最近的记录清空了', () => setHistory(before))
  }

  const share = async () => {
    try {
      await navigator.share({ text: prompt })
      setHistory((h) => remember(h, { material, intent, note, kind: det.kind }))
    } catch { /* 她取消了 */ }
  }

  // 键盘：⌘↵ 复制、1–9 选用途、Esc 关
  const keys = useRef({ copyNow, choose, intents, has, sheet })
  keys.current = { copyNow, choose, intents, has, sheet }
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const k = keys.current
      const el = e.target instanceof Element ? e.target : null
      const inField = !!el?.closest('input, textarea, [contenteditable="true"]')
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && k.has) {
        e.preventDefault()
        void k.copyNow()
      } else if (e.key === 'Escape') {
        if (k.sheet) setSheet(false)
        else if (inField) (el as HTMLElement).blur()
      } else if (!inField && !k.sheet && k.has && !e.metaKey && !e.ctrlKey && !e.altKey && /^[1-9]$/.test(e.key)) {
        const it = k.intents[Number(e.key) - 1]
        if (it) k.choose(it.id)
      }
    }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [])

  // 输入框跟着内容长高，但有上限，超过就在框里滚。
  // 手机上贴进来之后压得更矮：这时候要让她不滚动就看到「拿去做什么」——
  // 材料是她自己刚复制的，不用再读一遍
  useEffect(() => {
    const ta = matRef.current
    if (!ta) return
    const wide = window.matchMedia?.('(min-width: 900px)').matches
    const cap = has && !wide ? Math.max(96, window.innerHeight * 0.26) : Math.max(160, window.innerHeight * 0.4)
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight + 2, cap) + 'px'
  }, [material, has])

  const size = prompt.length
  const q = size && encodeURIComponent(prompt).length <= Q_MAX ? encodeURIComponent(prompt) : ''

  return (
    <div className={'app' + (has ? ' has' : ' empty')}>
      <header className="top">
        <div className="brand">
          <span className="mark" aria-hidden="true">随</span>
          <span className="name">随手</span>
          <span className="tag">复制什么都行，拿走 Prompt</span>
        </div>
        <div className="top-a">
          {has && (
            <button type="button" className="ghost" onClick={clear}>
              <span aria-hidden="true">＋</span> 新的
            </button>
          )}
          <button type="button" className="ghost" onClick={() => setSheet(true)} aria-haspopup="dialog">
            最近{history.length ? <span className="count">{history.length}</span> : null}
          </button>
        </div>
      </header>

      <UpdateBanner />

      <main className="grid">
        <section className="left">
          {!has && (
            <div className="hero">
              <h1>复制了什么，<br />就贴进来。</h1>
              <p className="sub">聊天记录、邮件、文章、报错、会议纪要、一个问题 —— 我认出是什么，拼好 Prompt，你拿去粘贴。</p>
              <button type="button" className="paste-btn" onClick={fromClipboard}>
                <ClipIcon />
                <span>
                  <b>从剪贴板贴入</b>
                  <small>{touch ? '点一下，再点系统弹出的「粘贴」' : `或者在页面任何地方按 ${MOD}+V`}</small>
                </span>
              </button>
            </div>
          )}

          <div className={'mat' + (has ? ' on' : '')}>
            {has && (
              <div className="mat-head">
                <span className="kind" data-kind={det.kind}>
                  <span className="kind-pre">认出来是 </span><b>{det.label}</b>
                  {det.meta ? <span className="meta"> · {det.meta}</span> : null}
                </span>
                <span className="mat-a">
                  <button type="button" className="mini" onClick={fromClipboard}>换一段</button>
                  <button type="button" className="mini x" onClick={clear} aria-label="清空">✕</button>
                </span>
              </div>
            )}
            <textarea
              ref={matRef}
              data-material
              className="mat-in"
              value={material}
              onChange={(e) => { setMaterial(e.target.value); setEdited(null) }}
              placeholder={has ? '' : touch ? '……或者长按这里，粘贴 / 直接打字' : '……或者直接粘贴 / 打字在这里'}
              aria-label="要处理的内容"
              spellCheck={false}
            />
            {has && material.length > 24000 && (
              <p className="warn">这段很长（{Math.round(material.length / 1000)}k 字符），有的 AI 一次装不下，必要时分几次问。</p>
            )}
          </div>

          {!has && (
            <div className="try">
              <span className="try-l">没东西可贴？试试：</span>
              {EXAMPLES.map((x) => (
                <button key={x.label} type="button" className="chip soft" onClick={() => takeIn(x.text, { autoCopy: false })}>
                  {x.label}
                </button>
              ))}
            </div>
          )}

          {has && (
            <>
              <div className="block">
                <div className="block-h">
                  <h2>拿去做什么</h2>
                  <span className="hint-r">点一下 = 复制这一版</span>
                </div>
                <div className="intents" role="group" aria-label="用途">
                  {intents.map((it, i) => {
                    const on = it.id === intent
                    const done = on && fresh
                    return (
                      <button
                        key={it.id}
                        type="button"
                        className={'intent' + (on ? ' on' : '') + (done ? ' done' : '')}
                        aria-pressed={on}
                        onClick={() => choose(it.id)}
                      >
                        {done && <span className="tick" aria-hidden="true">✓</span>}
                        {it.label}
                        {i === 0 && <span className="rec">推荐</span>}
                        {!touch && i < 9 && <kbd>{i + 1}</kbd>}
                      </button>
                    )
                  })}
                </div>
                <p className="what">{info.hint}</p>
              </div>

              <div className="block">
                <label className="note">
                  <span className="note-l">补一句 <small>（可选）</small></span>
                  <input
                    type="text"
                    value={note}
                    onChange={(e) => { setNote(e.target.value); setEdited(null) }}
                    placeholder={info.note}
                    enterKeyHint="done"
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.metaKey && !e.ctrlKey) (e.target as HTMLInputElement).blur() }}
                  />
                </label>
              </div>
            </>
          )}

          {!has && (
            <footer className="foot">
              <label className="switch">
                <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
                <span className="sw" aria-hidden="true" />
                <span>贴进来就自动复制推荐的那一版</span>
              </label>
              <p>全部只存在这台设备上，不上传。{!touch && ` ${MOD}+V 贴入 · 1–9 选用途 · ${MOD}+↵ 复制`}</p>
              <p className="ver">{__BUILD_SHA__ === 'offline' ? '离线单文件版' : `v${__BUILD_SHA__} · ${__BUILD_TIME__}`}</p>
            </footer>
          )}
        </section>

        {has && (
          <section className="right">
            <div className="out">
              <div className="out-h">
                <span className="out-t">
                  Prompt <small>{size.toLocaleString('en-US')} 字符{edited !== null && ' · 手改过'}</small>
                </span>
                <span className="out-a">
                  <span className="seg" role="group" aria-label="格式">
                    <button type="button" aria-pressed={target === 'md'} className={target === 'md' ? 'on' : ''} onClick={() => { setTarget('md'); setEdited(null) }}>通用</button>
                    <button type="button" aria-pressed={target === 'xml'} className={target === 'xml' ? 'on' : ''} onClick={() => { setTarget('xml'); setEdited(null) }}>Claude</button>
                  </span>
                  {edited !== null && !editing && (
                    <button type="button" className="mini" onClick={() => { setEdited(null) }}>还原</button>
                  )}
                  <button type="button" className="mini" onClick={() => { if (editing) setEditing(false); else { setEdited(prompt); setEditing(true) } }}>
                    {editing ? '改好了' : '手改'}
                  </button>
                </span>
              </div>
              {editing ? (
                <textarea
                  className="out-edit"
                  value={prompt}
                  onChange={(e) => setEdited(e.target.value)}
                  aria-label="手改 Prompt"
                  autoFocus
                  spellCheck={false}
                />
              ) : (
                <Preview text={prompt} target={target} fresh={fresh} pulse={pulse} onCopy={() => void copyNow()} />
              )}
            </div>

            <div className="bar">
              <div className="bar-row">
                <button
                  type="button"
                  className={'copy' + (fresh ? ' done' : '')}
                  onClick={() => void copyNow()}
                  key={fresh ? 'done-' + pulse : 'idle'}
                >
                  <span className="copy-t">{fresh ? '✓ 已复制，去粘贴吧' : copied ? '复制新版本' : '复制 Prompt'}</span>
                  <span className="copy-s">
                    {fresh ? `剪贴板里是「${info.label}」这一版` : `${info.label} · ${target === 'xml' ? 'Claude 格式' : '通用格式'}${copied ? ' · 刚改过' : ''}`}
                  </span>
                </button>
                {'share' in navigator && (
                  <button type="button" className="share" onClick={share} aria-label="分享到别的 App">
                    <ShareIcon />
                  </button>
                )}
              </div>
              <div className="go" aria-label="复制并打开">
                <span className="go-l">复制并打开</span>
                {OPENERS.map((o) => (
                  <a
                    key={o.id}
                    className="go-a"
                    href={o.href(o.id === 'chatgpt' || o.id === 'claude' ? q : '')}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={() => void copyNow()}
                  >
                    {o.label}
                  </a>
                ))}
              </div>
            </div>
          </section>
        )}
      </main>

      {sheet && <History items={history} onPick={reuse} onForget={forget} onForgetAll={forgetAll} onClose={() => setSheet(false)} />}

      <div className="toast-wrap" aria-live="polite">
        {toast && (
          <div className="toast" key={toast.id}>
            <span>{toast.msg}</span>
            {toast.undo && (
              <button type="button" onClick={() => { toast.undo?.(); setToast(null) }}>撤销</button>
            )}
          </div>
        )}
      </div>
      <span className="sr" aria-live="polite">{fresh ? '已复制' : ''}</span>
    </div>
  )
}

// ---------------------------------------------------------------- 最近

function History(props: {
  items: Item[]
  onPick: (it: Item) => void
  onForget: (id: string) => void
  onForgetAll: () => void
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null
    ref.current?.focus()
    document.body.classList.add('locked')
    return () => { document.body.classList.remove('locked'); prev?.focus?.() }
  }, [])
  return (
    <div className="scrim" onClick={props.onClose}>
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label="最近"
        tabIndex={-1}
        ref={ref}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sheet-h">
          <h2>最近复制过的</h2>
          <button type="button" className="mini x" onClick={props.onClose} aria-label="关闭">✕</button>
        </div>
        {props.items.length === 0 ? (
          <p className="none">还没有。复制过的会留在这儿，同一段材料换个用途再问，点一下就回来了。</p>
        ) : (
          <ul className="hist">
            {props.items.map((it) => (
              <li key={it.id}>
                <button type="button" className="hist-b" onClick={() => props.onPick(it)}>
                  <span className="hist-m">
                    <b>{intentInfo(it.intent, { kind: it.kind }).label}</b>
                    <span> · {SHORT[it.kind] ?? ''} · {ago(it.ts)}</span>
                  </span>
                  <span className="hist-t">{it.material.replace(/\s+/g, ' ').slice(0, 90)}</span>
                  {it.note && <span className="hist-n">补：{it.note}</span>}
                </button>
                <button type="button" className="mini x" onClick={() => props.onForget(it.id)} aria-label="删掉这条">✕</button>
              </li>
            ))}
          </ul>
        )}
        {props.items.length > 0 && (
          <button type="button" className="link" onClick={props.onForgetAll}>全部清空</button>
        )}
      </div>
    </div>
  )
}

const SHORT: Partial<Record<Kind, string>> = {
  url: '链接', error: '报错', code: '代码', table: '表格', chat: '聊天', email: '邮件', message: '消息',
  notes: '纪要', questions: '问题清单', ask: '问题', list: '清单', article: '长文', short: '一句话', text: '文字',
}

// ---------------------------------------------------------------- 新版本

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

function ClipIcon() {
  return (
    <svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="6" y="4" width="12" height="17" rx="2.5" />
      <path d="M9 4.5V3.8A1.8 1.8 0 0 1 10.8 2h2.4A1.8 1.8 0 0 1 15 3.8v.7" />
      <path d="M12 9v7m0 0-3-3m3 3 3-3" />
    </svg>
  )
}

function ShareIcon() {
  return (
    <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 15V3m0 0L8 7m4-4 4 4" />
      <path d="M7 10H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7a2 2 0 0 0-2-2h-1" />
    </svg>
  )
}
