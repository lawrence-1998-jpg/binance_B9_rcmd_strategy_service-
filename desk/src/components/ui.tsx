import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { DOMAINS, type Domain, type Status } from '../lib/types'
import { IcMore } from './icons'
import { useConfirm, dismissConfirm } from '../lib/confirm'
import { shouldPromptInstall, dismissNotice } from '../lib/install'
import { useUpdate, applyUpdate } from '../lib/update'
import { onRescue, rescuedRaw, dropRescue } from '../lib/store'
import { askConfirm } from '../lib/confirm'
import { saveFile } from '../lib/save'
import * as D from '../lib/date'

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
              // 44 是触控下限；选中态的底走 *-solid 变体——
              // 原色 #c67139 上放浅色 13px 字只有 3.41:1，读不清
              flex: 1, minHeight: 'var(--tap)', borderRadius: 'var(--r-pill)',
              fontSize: 'var(--t-body)', fontWeight: 700,
              background: on ? (o.color ?? 'var(--consult-solid)') : 'transparent',
              color: on ? 'var(--on-solid)' : 'var(--ink-2)',
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

/**
 * 确认框。只给不可撤销的操作用——弹得太勤，人就会闭着眼点「确定」，
 * 那时它就一点用都没有了。
 */
export function ConfirmDialog() {
  const ask = useConfirm()
  if (!ask) return null
  return (
    <div className="scrim" onClick={dismissConfirm}>
      <div className="dialog" role="alertdialog" aria-modal="true" aria-label={ask.title}
        onClick={(e) => e.stopPropagation()}>
        <p className="dialog-t">{ask.title}</p>
        {ask.detail && <p className="dialog-s">{ask.detail}</p>}
        <div className="dialog-acts">
          <button type="button" className="btn quiet" style={{ flex: 1 }} onClick={dismissConfirm}>算了</button>
          <button type="button" className="btn danger" style={{ flex: 1 }} autoFocus
            onClick={() => { ask.onYes(); dismissConfirm() }}>
            {ask.confirmLabel ?? '删掉'}
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * 会跟着内容长高的多行输入。
 *
 * 固定 rows={2} 的话，写超过两行就只能在框里滚——而「今天这三句」是每天
 * 真的要回头看的东西，看不全等于白写。resize 手柄在手机上又点不到，
 * 所以只能由代码来量。
 */
export function GrowText({
  value, onChange, placeholder, minRows = 2, maxLength, style, ...rest
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  minRows?: number
  maxLength?: number
  style?: CSSProperties
} & { 'aria-label'?: string }) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [value])
  return (
    <textarea
      {...rest}
      ref={ref}
      className="field grow-y"
      rows={minRows}
      maxLength={maxLength}
      value={value}
      placeholder={placeholder}
      style={style}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

/**
 * 「先添加到主屏幕」。
 *
 * 不是普通的安装引导。iOS 上 Safari 标签页和主屏 App 是**两份隔离的存储**，
 * 在浏览器里写的日记、存的照片，装到主屏幕之后一条都看不到；而且只在
 * Safari 里用的话，7 天不打开就会被系统清掉。
 *
 * 她只能先在 Safari 里打开这个链接——默认路径就是错的那条。
 * 所以这句话必须赶在她开始往里写东西**之前**说，晚了就只能靠导出救。
 */
export function InstallNotice() {
  const [show, setShow] = useState(shouldPromptInstall)
  if (!show) return null
  return (
    <div className="install">
      <p className="install-t">先把它加到主屏幕，再开始记</p>
      <p className="install-s">
        iPhone 上，<strong>浏览器里的数据和主屏 App 是两份，互相看不见</strong>。
        现在在浏览器里记的东西，装好之后一条都不会带过去。
        而且浏览器里 7 天不打开，系统会把数据清掉。
      </p>
      <p className="install-s" style={{ marginTop: 'var(--s2)' }}>
        底部<strong>分享</strong>按钮 → <strong>添加到主屏幕</strong>，然后从桌面图标进来。
      </p>
      <button type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s4)' }}
        onClick={() => { dismissNotice(); setShow(false) }}>
        知道了，先在浏览器里看看
      </button>
    </div>
  )
}

/**
 * 「有新版本」。
 *
 * 只有一种情况会浮出来：她正用着的时候后台装好了新版（多半是从后台切回前台
 * 那一下查到的）。刚打开就查到的那种不走这里——直接换掉了，不打扰。
 *
 * 做成一整条可点的，而不是一句话加一个小「更新」链接：她多半是单手、
 * 走在路上点的，整条 44px 高的横幅比一个链接好点太多。
 */
export function UpdatePill() {
  const { ready, applying } = useUpdate()
  useEffect(() => {
    // 浮出来的时候把 toast 抬高一档，两个都在拇指区，不能叠在一起
    document.body.classList.toggle('has-update', ready)
    return () => document.body.classList.remove('has-update')
  }, [ready])
  if (!ready) return null
  return (
    <button type="button" className="update-pill" disabled={applying} onClick={applyUpdate}>
      {applying ? (
        // 换一次要几秒。这几秒不说话的话，看着就是点了没反应
        <span className="update-t">正在换……</span>
      ) : (
        <>
          <span className="update-t">有新版本</span>
          <span className="update-a">点一下换过来</span>
        </>
      )}
    </button>
  )
}

/**
 * 「上次有一份数据没读出来」。
 *
 * 出现的条件很窄，但后果最重：存着的那串东西解析不了（截断、被别的
 * 东西写坏、版本字段没了），以前的做法是直接回到示例数据，然后
 * 一动就把示例数据盖回去 —— 她那本日记就这么没了，一句话都没有。
 *
 * 现在原始那串字节被原样留着。这条横幅的唯一任务是让她**先把它导出去**，
 * 所以「导出那份」是主按钮，删除得她自己确认 —— 那一步不可逆，
 * 而这份东西可能是她仅剩的一份。
 */
export function RescueNotice({ toast }: { toast: (t: string) => void }) {
  const [raw, setRaw] = useState<string | null>(null)
  useEffect(() => onRescue(setRaw), [])
  if (!raw) return null

  async function save() {
    const data = rescuedRaw()
    if (!data) return
    const out = await saveFile(`案头-读不出来的那份-${D.key().replace(/-/g, '')}.json`, data)
    toast(out === 'saved' ? '存下来了，先收好' : out === 'declined' ? '取消了' : '存不了，去设置页手动复制')
  }

  return (
    <div className="rescue" role="alert">
      <p className="rescue-t">上次有一份数据没读出来</p>
      <p className="rescue-s">
        存着的东西解析不了，界面先回到了示例数据。
        <strong>原来那份没有删，原样留着。</strong>
        先把它导出去存好，再决定怎么办 —— 别在导出之前清空数据。
      </p>
      <div className="rescue-acts">
        <button type="button" className="btn small" onClick={() => void save()}>导出那份</button>
        <button type="button" className="btn small quiet"
          onClick={() => askConfirm({
            title: '删掉那份读不出来的数据？',
            detail: '删了就真没了，没有别的副本。确认你已经导出并存好了。',
            confirmLabel: '删掉',
            onYes: dropRescue,
          })}>
          存好了，删掉
        </button>
      </div>
    </div>
  )
}
