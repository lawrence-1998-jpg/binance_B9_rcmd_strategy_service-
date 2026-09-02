import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { DOMAINS, type Domain, type Status } from '../lib/types'
import { IcMore } from './icons'

export function Section({ label, meta, domain }: { label: string; meta?: ReactNode; domain?: Domain }) {
  return (
    <div className="sect">
      <span className="sect-l">
        {domain && <i className="sect-bar" style={{ background: DOMAINS[domain].color }} />}
        <span className="eyebrow">{label}</span>
      </span>
      {meta != null && <span className="sect-r">{meta}</span>}
    </div>
  )
}

export function Dot({ status }: { status: Status }) {
  const label = status === 'ok' ? '正常' : status === 'warn' ? '需要注意' : '阻塞'
  return <i className={`dot dot-${status}`} role="img" aria-label={label} />
}

export function Chip({
  children, on, tone, onClick, tap,
}: { children: ReactNode; on?: boolean; tone?: Domain; onClick?: () => void; tap?: boolean }) {
  const style = on
    ? undefined
    : tone
      ? { background: DOMAINS[tone].tint, color: DOMAINS[tone].deep }
      : undefined
  const cls = `chip${on ? ' on' : ''}${tap ? ' tap' : ''}`
  if (!onClick) return <span className={cls} style={style}>{children}</span>
  return (
    <button type="button" className={cls} style={style} onClick={onClick} aria-pressed={!!on}>
      {children}
    </button>
  )
}

export function Progress({ value, color }: { value: number; color?: string }) {
  const v = Math.max(0, Math.min(100, value))
  return (
    <div className="prog" role="progressbar" aria-valuenow={v} aria-valuemin={0} aria-valuemax={100}>
      <i style={{ width: `${v}%`, background: color ?? 'var(--consult)' }} />
    </div>
  )
}

/**
 * 清单行。整行点一下 = 完成 —— 这是清单的主操作，不能让位给别的。
 * 「推迟 / 删除」这类次要动作走右边独立的 ⋯ 按钮，不塞进 label 里
 * （塞进去就得 preventDefault，勾选会被吃掉）。
 */
export function Check({
  done, title, sub, right, onToggle, bar, onMore, moreOpen,
}: {
  done: boolean; title: ReactNode; sub?: ReactNode; right?: ReactNode
  onToggle: () => void; bar?: Domain; onMore?: () => void; moreOpen?: boolean
}) {
  return (
    <div className="check-row">
      <label className={`check${done ? ' done' : ''}`}>
        <input type="checkbox" checked={done} onChange={onToggle} />
        <span className="box" />
        {bar && <i className="dbar" style={{ background: DOMAINS[bar].color }} />}
        <span className="grow">
          <span className="check-t">{title}</span>
          {sub && <span className="row-s">{sub}</span>}
        </span>
        {right && <span className="row-s check-right">{right}</span>}
      </label>
      {onMore && (
        <button type="button" className="more" onClick={onMore} aria-expanded={!!moreOpen} aria-label="更多操作">
          <IcMore />
        </button>
      )}
    </div>
  )
}

export function Empty({ icon, title, sub, action, tone }: {
  icon: ReactNode; title: string; sub?: string; action?: ReactNode; tone?: Domain
}) {
  return (
    <div className="empty" style={tone ? ({ '--empty-tone': DOMAINS[tone].color } as CSSProperties) : undefined}>
      {icon}
      <p className="empty-t">{title}</p>
      {sub && <p className="empty-s">{sub}</p>}
      {action && <div style={{ marginTop: 'var(--s4)' }}>{action}</div>}
    </div>
  )
}

/** 行内新增：点一下变成输入框，回车提交，Esc 取消。手机上少一次跳转。 */
export function InlineAdd({
  placeholder, onAdd, cta,
}: { placeholder: string; onAdd: (text: string) => void; cta: string }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const ref = useRef<HTMLInputElement>(null)

  useEffect(() => { if (open) ref.current?.focus() }, [open])

  function submit() {
    const t = text.trim()
    if (!t) { setOpen(false); return }
    onAdd(t)
    setText('')
    ref.current?.focus()
  }

  if (!open) {
    return (
      <button type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s2)' }} onClick={() => setOpen(true)}>
        ＋ {cta}
      </button>
    )
  }
  return (
    <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s2)' }}>
      <input
        ref={ref}
        className="field pill"
        value={text}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
          if (e.key === 'Escape') { setText(''); setOpen(false) }
        }}
        onBlur={() => { if (!text.trim()) setOpen(false) }}
      />
      <button type="button" className="btn small" onClick={submit} style={{ flex: '0 0 auto' }}>存</button>
    </div>
  )
}

export function Toast({ text }: { text: string | null }) {
  if (!text) return null
  return <div className="toast" role="status">{text}</div>
}

export function useToast() {
  const [text, setText] = useState<string | null>(null)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  function show(t: string) {
    setText(t)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setText(null), 1800)
  }
  return { text, show }
}

/** 分段控制：工作台里两处用到（咨询/字节、我们俩/国庆） */
export function Segmented<T extends string>({
  value, options, onChange,
}: { value: T; options: { key: T; label: string; color?: string }[]; onChange: (v: T) => void }) {
  return (
    <div style={{ display: 'flex', gap: 6, background: 'var(--well)', padding: 4, borderRadius: 'var(--r-pill)', marginTop: 'var(--s4)' }}>
      {options.map((o) => {
        const on = o.key === value
        return (
          <button
            key={o.key}
            type="button"
            onClick={() => onChange(o.key)}
            aria-pressed={on}
            style={{
              flex: 1, minHeight: 36, borderRadius: 'var(--r-pill)',
              fontSize: 'var(--t-body)', fontWeight: 700,
              background: on ? (o.color ?? 'var(--consult)') : 'transparent',
              color: on ? '#fdf8ef' : 'var(--ink-2)',
              transition: 'background var(--d-micro) var(--ease), color var(--d-micro) var(--ease)',
            }}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
