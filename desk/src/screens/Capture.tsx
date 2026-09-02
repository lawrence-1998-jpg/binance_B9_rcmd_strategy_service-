import { useEffect, useRef, useState } from 'react'
import { update, useStore, uid } from '../lib/store'
import { NOTE_KINDS, type NoteKind } from '../lib/types'
import * as D from '../lib/date'
import { Chip } from '../components/ui'
import { askConfirm } from '../lib/confirm'
import { IcClose } from '../components/icons'

/**
 * 速记：全屏 sheet，不是第五个 tab。进来只有存或关两条路。
 * 关键设计：进来自动聚焦，分类可以完全跳过 —— 捕捉与整理分离。
 */
export function Capture({ onClose, toast }: { onClose: () => void; toast: (t: string) => void }) {
  const s = useStore((x) => x)
  const [text, setText] = useState('')
  const [kind, setKind] = useState<NoteKind | null>(null)
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    ref.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onClose, text])

  /**
   * 关掉之前先问一句 —— 但只在真写了点东西的时候。
   * 手机上返回手势太容易误触，刚想到的东西就这么没了；
   * 而这里的全部意义就是「想到什么先扔进来」，丢掉一条就是丢掉那个念头。
   * 只打了两三个字就不问了，不然反而变成骚扰。
   */
  function close() {
    if (text.trim().length < 8) { onClose(); return }
    askConfirm({
      title: '不存就走？',
      detail: `「${text.trim().slice(0, 30)}${text.trim().length > 30 ? '…' : ''}」会丢掉。`,
      confirmLabel: '丢掉',
      onYes: onClose,
    })
  }

  const todayCount = s.notes.filter((n) => D.key(new Date(n.createdAt)) === D.key()).length
  const pending = s.notes.filter((n) => !n.handled).length

  function save() {
    const t = text.trim()
    if (!t) { onClose(); return }
    update((x) => ({ ...x, notes: [{ id: uid(), text: t, kind, createdAt: Date.now(), handled: false }, ...x.notes] }))
    toast(kind === 'us' ? '记下了 ♡' : '记下了')
    onClose()
  }

  return (
    <div className="sheet" role="dialog" aria-modal="true" aria-label="记一笔">
      <div className="sheet-in">
        <div className="sheet-head">
          <span className="eyebrow">记一笔</span>
          <button type="button" className="icon-btn" onClick={close} aria-label="关闭"><IcClose /></button>
        </div>

        <textarea
          ref={ref}
          rows={4}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) save() }}
          placeholder="想到什么，先扔进来"
          style={{
            background: 'none', width: '100%', marginTop: 'var(--s5)',
            fontFamily: 'var(--f-cjk)', fontWeight: 700, fontSize: 'var(--t-focus)',
            lineHeight: 1.45, resize: 'none', outline: 'none',
          }}
        />

        <div className="chips" style={{ marginTop: 'var(--s4)' }}>
          {NOTE_KINDS.map((k) => (
            <Chip key={k.key} tap on={kind === k.key} tone={k.key === 'us' ? 'us' : undefined}
              onClick={() => setKind(kind === k.key ? null : k.key)}>
              {k.mark} {k.label}
            </Chip>
          ))}
        </div>
        <p className="sub quiet" style={{ marginTop: 'var(--s3)' }}>
          分类可以现在选，也可以晚上复盘时再补。
        </p>

        <div className="sheet-foot">
          <button type="button" className="btn wide" onClick={save} disabled={!text.trim()}>存下来</button>
          <p className="sub quiet" style={{ textAlign: 'center', marginTop: 'var(--s2)' }}>
            今天已记 {todayCount} 条 · 未处理 {pending} 条
          </p>
        </div>
      </div>
    </div>
  )
}
