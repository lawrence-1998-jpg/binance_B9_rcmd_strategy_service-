import { useMemo, useRef, useState } from 'react'
import { update, useStore, uid } from '../lib/store'
import { askConfirm } from '../lib/confirm'
import { buildPrompt, parseOutline, TARGETS, DEPTHS, type Depth, type Target } from '../lib/prompt'
import { copyText } from '../lib/copy'
import { Section, Chip, Empty } from '../components/ui'
import { IcClose, IcBack, IcCopy, IcNote, IcTrash, IcWand } from '../components/icons'
import data from '../data/prompts.json'

interface Builtin { id: string; cat: string; catName: string; title: string; body: string; note: string }
const BUILTIN = (data.items as Builtin[])
const CATS = Array.from(new Map(BUILTIN.map((b) => [b.cat, b.catName])).entries())

type View = { kind: 'list' } | { kind: 'item'; id: string } | { kind: 'gen' } | { kind: 'new' }

export function Prompts({ onClose, toast }: { onClose: () => void; toast: (t: string) => void }) {
  const mine = useStore((x) => x.myPrompts)
  const uses = useStore((x) => x.promptUses)
  const [view, setView] = useState<View>({ kind: 'list' })
  const [q, setQ] = useState('')
  const [cat, setCat] = useState<string | null>(null)

  const all = useMemo(
    () => [
      ...mine.map((m) => ({ id: m.id, cat: '我', catName: '我加的', title: m.title, body: m.body, note: '' })),
      ...BUILTIN,
    ],
    [mine],
  )

  const shown = useMemo(() => {
    const kw = q.trim().toLowerCase()
    return all
      .filter((p) => (cat ? p.cat === cat : true))
      .filter((p) => (kw ? (p.title + p.body + p.catName).toLowerCase().includes(kw) : true))
      .sort((a, b) => (uses[b.id] ?? 0) - (uses[a.id] ?? 0))
  }, [all, q, cat, uses])

  async function copy(id: string, body: string) {
    const ok = await copyText(body)
    update((x) => ({ ...x, promptUses: { ...x.promptUses, [id]: (x.promptUses[id] ?? 0) + 1 } }))
    toast(ok ? '复制好了，去贴给它' : '复制失败，长按选中吧')
  }

  if (view.kind === 'gen') return <Generator onBack={() => setView({ kind: 'list' })} onClose={onClose} toast={toast} />
  if (view.kind === 'new') return <NewPrompt onBack={() => setView({ kind: 'list' })} onClose={onClose} toast={toast} />

  if (view.kind === 'item') {
    const p = all.find((x) => x.id === view.id)
    if (!p) return null
    const isMine = mine.some((m) => m.id === p.id)
    return (
      <div className="sheet" role="dialog" aria-modal="true" aria-label={p.title}>
        <div className="sheet-in">
          <div className="sheet-head">
            <button type="button" className="icon-btn" style={{ marginLeft: -8 }} onClick={() => setView({ kind: 'list' })} aria-label="返回"><IcBack /></button>
            <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭"><IcClose /></button>
          </div>
          <p className="eyebrow" style={{ marginTop: 'var(--s2)' }}>{p.cat === '我' ? '我加的' : `${p.cat} · ${p.catName}`}</p>
          <h1 className="h1" style={{ fontSize: 'var(--t-focus)' }}>{p.title}</h1>

          <div className="pbody" style={{ marginTop: 'var(--s4)' }}>{p.body}</div>

          {p.note && (
            <p className="sub" style={{ color: 'var(--ink-2)', marginTop: 'var(--s3)', lineHeight: 1.6 }}>{p.note}</p>
          )}
          {(uses[p.id] ?? 0) > 0 && (
            <p className="row-s" style={{ marginTop: 'var(--s3)' }}>复制过 {uses[p.id]} 次</p>
          )}

          <div className="sheet-foot">
            <button type="button" className="btn wide" onClick={() => void copy(p.id, p.body)}>
              <IcCopy /> 一键复制
            </button>
            {isMine && (
              <button
                type="button" className="btn ghost small wide" style={{ marginTop: 'var(--s2)', color: 'var(--alert)' }}
                onClick={() => askConfirm({
                  title: `删掉「${p.title}」？`,
                  detail: '自己写的 prompt 删了就没了，内置那批不受影响。',
                  onYes: () => {
                    update((x) => ({ ...x, myPrompts: x.myPrompts.filter((m) => m.id !== p.id) }))
                    setView({ kind: 'list' }); toast('删掉了')
                  },
                })}
              ><IcTrash /> 删掉</button>
            )}
          </div>
          <div style={{ height: 'var(--s6)' }} />
        </div>
      </div>
    )
  }

  return (
    <div className="sheet" role="dialog" aria-modal="true" aria-label="Prompt 管理器">
      <div className="sheet-in">
        <div className="sheet-head">
          <span className="eyebrow">Prompt · {all.length} 条</span>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭"><IcClose /></button>
        </div>

        <input
          className="field pill" style={{ marginTop: 'var(--s3)' }}
          value={q} placeholder="搜标题或内容"
          onChange={(e) => setQ(e.target.value)}
        />

        <div className="chips" style={{ marginTop: 'var(--s3)' }}>
          <Chip tap on={cat === null} onClick={() => setCat(null)}>全部</Chip>
          {mine.length > 0 && <Chip tap on={cat === '我'} onClick={() => setCat('我')}>我加的</Chip>}
          {CATS.map(([c, name]) => (
            <Chip key={c} tap on={cat === c} onClick={() => setCat(c)}>{name}</Chip>
          ))}
        </div>

        <Section label="工具" meta="现场生成" />
        <button type="button" className="pitem" onClick={() => setView({ kind: 'gen' })}>
          <span className="pitem-h">
            <span className="pitem-id"><IcWand /></span>
            <span className="pitem-t">提纲 → 调研 Prompt</span>
          </span>
          <span className="pitem-b">输入几条要问的，出一段带「不许编数字」约束的调研 prompt</span>
        </button>

        <Section label={cat ? (CATS.find((c) => c[0] === cat)?.[1] ?? '我加的') : '全部'} meta={`${shown.length} 条`} />
        {shown.length === 0 ? (
          <div className="card"><Empty icon={<IcNote />} title="没搜到" sub="换个词试试，或者自己加一条。" /></div>
        ) : (
          <div className="plist">
            {shown.map((p) => (
              <button key={p.id} type="button" className="pitem" onClick={() => setView({ kind: 'item', id: p.id })}>
                <span className="pitem-h">
                  <span className="pitem-id">{p.cat === '我' ? '★' : p.id}</span>
                  <span className="pitem-t">{p.title}</span>
                  {(uses[p.id] ?? 0) > 0 && <span className="row-s" style={{ flex: '0 0 auto' }}>{uses[p.id]}×</span>}
                </span>
                <span className="pitem-b">{p.body}</span>
              </button>
            ))}
          </div>
        )}

        <button type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s3)' }} onClick={() => setView({ kind: 'new' })}>
          ＋ 自己加一条
        </button>

        <p className="sub quiet" style={{ marginTop: 'var(--s4)', lineHeight: 1.6 }}>
          内置这 {BUILTIN.length} 条在构建时从仓库的 <span className="mono">docs/playbook/lawrence-prompt-list.md</span> 生成 ——
          改那份 md 再发布，这里就跟着变，不存第二份。
        </p>
        <div style={{ height: 'var(--s6)' }} />
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- 自建 */

function NewPrompt({ onBack, onClose, toast }: { onBack: () => void; onClose: () => void; toast: (t: string) => void }) {
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  return (
    <div className="sheet" role="dialog" aria-modal="true" aria-label="新建 Prompt">
      <div className="sheet-in">
        <div className="sheet-head">
          <button type="button" className="icon-btn" style={{ marginLeft: -8 }} onClick={onBack} aria-label="返回"><IcBack /></button>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭"><IcClose /></button>
        </div>
        <Section label="加一条" />
        <input className="field" value={title} placeholder="叫什么？比如：客户访谈提纲" onChange={(e) => setTitle(e.target.value)} />
        <textarea
          className="field" rows={10} style={{ marginTop: 'var(--s2)', fontFamily: 'var(--f-mono)', fontSize: 'var(--t-input)', lineHeight: 1.6 }}
          value={body} placeholder="把 prompt 正文贴进来" onChange={(e) => setBody(e.target.value)}
        />
        <div className="sheet-foot">
          <button
            type="button" className="btn wide" disabled={!title.trim() || !body.trim()}
            onClick={() => {
              update((x) => ({ ...x, myPrompts: [{ id: 'my-' + uid(), title: title.trim(), body: body.trim(), createdAt: Date.now() }, ...x.myPrompts] }))
              toast('加好了'); onBack()
            }}
          >存下来</button>
        </div>
        <div style={{ height: 'var(--s6)' }} />
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- 生成器 */

function Generator({ onBack, onClose, toast }: { onBack: () => void; onClose: () => void; toast: (t: string) => void }) {
  const draft = useStore((x) => x.promptDraft)
  const [showOut, setShowOut] = useState(false)
  const out = useRef<HTMLTextAreaElement>(null)
  const prompt = useMemo(() => buildPrompt(draft), [draft])
  const count = parseOutline(draft.outline).length

  function patch(p: Partial<typeof draft>) {
    update((x) => ({ ...x, promptDraft: { ...x.promptDraft, ...p } }))
  }

  async function copy() {
    if (!prompt) return
    const ok = await copyText(prompt)
    if (ok) { toast('复制好了，去贴给它'); return }
    setShowOut(true)
    setTimeout(() => { out.current?.focus(); out.current?.select() }, 50)
    toast('已选中，长按复制')
  }

  return (
    <div className="sheet" role="dialog" aria-modal="true" aria-label="提纲转 Prompt">
      <div className="sheet-in">
        <div className="sheet-head">
          <button type="button" className="icon-btn" style={{ marginLeft: -8 }} onClick={onBack} aria-label="返回"><IcBack /></button>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭"><IcClose /></button>
        </div>
        <p className="eyebrow" style={{ marginTop: 'var(--s2)' }}>提纲 → Prompt</p>
        <p className="sub" style={{ color: 'var(--ink-2)', marginTop: 'var(--s2)' }}>
          纯本地拼装，不联网不调模型。模板里带了防编数字的约束 —— 这类问题模型最爱一本正经给假百分比。
        </p>

        <Section label="提纲" meta={count ? `${count} 条` : '一行一条'} />
        <textarea
          className="field" rows={5} value={draft.outline}
          onChange={(e) => patch({ outline: e.target.value })}
          placeholder={'一行一条'}
          style={{ fontFamily: 'var(--f-cjk)', lineHeight: 1.6 }}
        />

        <Section label="调研对象" meta="选填" />
        <input className="field" value={draft.subject} placeholder="比如：抖音" onChange={(e) => patch({ subject: e.target.value })} />

        <Section label="我的处境" meta="填了效果好很多" />
        <textarea
          className="field" rows={2} value={draft.context}
          placeholder="一句话说清你为什么问这个"
          onChange={(e) => patch({ context: e.target.value })}
        />

        <Section label="贴给谁" />
        <div className="chips">
          {TARGETS.map((t) => (
            <Chip key={t.key} tap on={draft.target === t.key} onClick={() => patch({ target: t.key as Target })}>{t.label}</Chip>
          ))}
        </div>

        <Section label="要多深" />
        <div className="chips">
          {DEPTHS.map((d) => (
            <Chip key={d.key} tap on={draft.depth === d.key} onClick={() => patch({ depth: d.key as Depth })}>{d.label}</Chip>
          ))}
        </div>

        <div className="sheet-foot">
          <button type="button" className="btn wide" onClick={() => void copy()} disabled={!prompt}>
            <IcCopy /> 复制 Prompt
          </button>
          <button
            type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s2)' }}
            onClick={() => setShowOut((v) => !v)} disabled={!prompt}
          >{showOut ? '收起' : `先看看长什么样（${prompt.length} 字）`}</button>
        </div>

        {showOut && (
          <textarea
            ref={out} className="field" rows={16} readOnly value={prompt}
            onFocus={(e) => e.currentTarget.select()}
            style={{ marginTop: 'var(--s3)', fontFamily: 'var(--f-mono)', fontSize: 'var(--t-meta)', lineHeight: 1.55 }}
          />
        )}
        <div style={{ height: 'var(--s6)' }} />
      </div>
    </div>
  )
}
