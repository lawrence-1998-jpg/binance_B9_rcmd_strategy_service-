import { useMemo, useState } from 'react'
import { update, useStore, uid } from '../lib/store'
import { DOMAINS, NOTE_KINDS, type Domain, type NoteKind, type Task } from '../lib/types'
import * as D from '../lib/date'
import { Section, Check, Chip, Empty, Segmented, GrowText } from '../components/ui'
import { autoDraft } from '../lib/diary'
import { askConfirm } from '../lib/confirm'
import { IcGear, IcNote } from '../components/icons'
import type { Route } from '../components/TabBar'

const ORDER: Domain[] = ['consult', 'byte', 'us', 'me']

export function Review({ go, onSettings, toast }: { go: (r: Route) => void; onSettings: () => void; toast: (t: string) => void }) {
  const s = useStore((x) => x)
  const today = D.key()
  const tomorrow = D.key(new Date(Date.now() + 86400000))
  const [tab, setTab] = useState<'today' | 'line'>('today')
  const stored = s.entries.find((e) => e.date === today)
  const entry = stored ?? { date: today, lines: autoDraft(s, today), auto: true, updatedAt: 0 }
  const [tmTitle, setTmTitle] = useState('')
  const [tmDomain, setTmDomain] = useState<Domain>('consult')
  const [showAllPending, setShowAllPending] = useState(false)

  const tasks = s.tasks.filter((t) => t.date === today)
  const done = tasks.filter((t) => t.done)
  const left = tasks.filter((t) => !t.done)
  const pending = s.notes.filter((n) => !n.handled)
  const tmTasks = s.tasks.filter((t) => t.date === tomorrow)

  // 近 7 天完成的事按领域分布 —— 看的是「时间花在哪条线上」
  const since = D.key(new Date(Date.now() - 6 * 86400000))
  const week = s.tasks.filter((t) => t.done && t.date >= since)
  const byDomain = ORDER.map((d) => ({ d, n: week.filter((t) => t.domain === d).length })).filter((x) => x.n > 0)
  const weekTotal = week.length

  function saveEntry(lines: [string, string, string], auto: boolean) {
    update((x) => ({
      ...x,
      entries: [...x.entries.filter((e) => e.date !== today), { date: today, lines, auto, updatedAt: Date.now() }],
    }))
  }

  function classify(id: string, kind: NoteKind) {
    update((x) => ({ ...x, notes: x.notes.map((n) => (n.id === id ? { ...n, kind } : n)) }))
  }

  function addTomorrow() {
    const t = tmTitle.trim()
    if (!t) return
    update((x) => ({ ...x, tasks: [...x.tasks, { id: uid(), title: t, domain: tmDomain, done: false, date: tomorrow }] }))
    setTmTitle('')
  }

  // 「明天再来」只在天黑之后说得通。白天什么都没勾就丢这句，
  // 既不准确也泄气 —— 平静优先的意思是不制造亏欠感。
  const headline = tasks.length === 0
    ? '今天没记事'
    : done.length === tasks.length
      ? '三件都做完了'
      : done.length > 0
        ? '今天挺好'
        : D.isEvening() ? '明天再来' : '今天还长'

  return (
    <div className="screen">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginTop: 'var(--s3)' }}>
        <div>
          <p className="eyebrow">{D.longCN()} · 收尾</p>
          <h1 className="h1">{headline}</h1>
        </div>
        <button type="button" className="icon-btn" onClick={onSettings} aria-label="设置"><IcGear /></button>
      </div>
      <p className="sub quiet" style={{ marginTop: 'var(--s2)' }}>
        完成 {done.length} 件，记了 {s.notes.filter((n) => D.key(new Date(n.createdAt)) === today).length} 条
        {weekTotal ? `，这周一共做完 ${weekTotal} 件。` : '。'}
      </p>

      <Segmented<'today' | 'line'>
        value={tab}
        onChange={setTab}
        options={[
          { key: 'today', label: '今天' },
          { key: 'line', label: '时间轴' },
        ]}
      />

      {tab === 'line' ? <Timeline /> : <>

      {/* 完成情况：没做完的排在完成的后面，并且已经自动顺延 —— 不制造亏欠感 */}
      <Section label="今天" meta={tasks.length ? `${done.length} / ${tasks.length}` : undefined} />
      <div className={tasks.length ? 'card flush' : 'card'}>
        {tasks.length === 0 ? (
          <p className="sub quiet" style={{ margin: 0 }}>今天没有列三件事。也没关系。</p>
        ) : (
          [...done, ...left].map((t) => (
            <Check
              key={t.id}
              done={t.done}
              bar={t.domain}
              title={t.title}
              sub={t.done ? undefined : '顺延到明天'}
              onToggle={() => update((x) => ({ ...x, tasks: x.tasks.map((y) => (y.id === t.id ? { ...y, done: !y.done } : y)) }))}
            />
          ))
        )}
      </div>
      {left.length > 0 && (
        <button type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s2)' }}
          onClick={() => {
            update((x) => ({ ...x, tasks: x.tasks.map((y) => (y.date === today && !y.done ? { ...y, date: tomorrow } : y)) }))
            toast(`${left.length} 件挪到明天`)
          }}>
          把没做完的挪到明天
        </button>
      )}

      {weekTotal > 0 && (
        <>
          <Section label="这周花在哪" meta={`${weekTotal} 件`} />
          <div className="card">
            <div style={{ display: 'flex', height: 10, borderRadius: 999, overflow: 'hidden', background: 'var(--well)' }}>
              {byDomain.map(({ d, n }) => (
                <i key={d} style={{ width: `${(n / weekTotal) * 100}%`, background: DOMAINS[d].color, display: 'block' }} />
              ))}
            </div>
            <div className="chips" style={{ marginTop: 'var(--s3)' }}>
              {byDomain.map(({ d, n }) => (
                <Chip key={d} tone={d}>{DOMAINS[d].short} {n}</Chip>
              ))}
            </div>
          </div>
        </>
      )}

      {/* 速记的出口 —— 这里清不掉，速记就会变成垃圾桶 */}
      <Section label="待归类" meta={pending.length ? `${pending.length} 条` : '清空了'} />
      <div className={pending.length ? 'card flush' : 'card'}>
        {pending.length === 0 ? (
          <Empty icon={<IcNote />} title="都处理完了" sub="速记没有积压。" />
        ) : (
          (showAllPending ? pending : pending.slice(0, 8)).map((n) => (
            <div key={n.id} style={{ padding: '12px 0', borderTop: '1px solid var(--line)' }}>
              <p className="row-t" style={{ margin: 0 }}>{n.text}</p>
              <p className="row-s">{D.relTime(n.createdAt)}</p>
              <div className="chips" style={{ marginTop: 'var(--s2)' }}>
                {NOTE_KINDS.map((k) => (
                  <Chip key={k.key} tap on={n.kind === k.key} tone={k.key === 'us' ? 'us' : undefined}
                    onClick={() => classify(n.id, k.key)}>
                    {k.mark} {k.label}
                  </Chip>
                ))}
                <Chip tap onClick={() => {
                  update((x) => ({ ...x, notes: x.notes.map((y) => (y.id === n.id ? { ...y, handled: true } : y)) }))
                }}>归档</Chip>
                {n.kind !== 'us' && (
                  <Chip tap onClick={() => {
                    update((x) => ({
                      ...x,
                      notes: x.notes.map((y) => (y.id === n.id ? { ...y, handled: true } : y)),
                      tasks: [...x.tasks, { id: uid(), title: n.text, domain: 'me' as Domain, done: false, date: tomorrow }],
                    }))
                    toast('变成明天的事了')
                  }}>→ 明天做</Chip>
                )}
              </div>
            </div>
          ))
        )}
        {pending.length > 8 && (
          <button type="button" className="btn quiet small wide" style={{ margin: 'var(--s3) 0' }}
            onClick={() => setShowAllPending((v) => !v)}>
            {showAllPending ? '收起' : `还有 ${pending.length - 8} 条，全部展开`}
          </button>
        )}
      </div>

      <Section label="今天这三句" meta={entry.auto ? '自动写的，可以改' : '你改过了'} />
      <div className="card">
        {([0, 1, 2] as const).map((i) => (
          <GrowText
            key={i}
            style={i ? { marginTop: 'var(--s2)' } : undefined}
            value={entry.lines[i]}
            maxLength={500}
            aria-label={`第 ${i + 1} 句`}
            placeholder={['今天做了什么', '心里是什么感觉', '明天先做什么'][i]}
            onChange={(v) => {
              const lines = [...entry.lines] as [string, string, string]
              lines[i] = v
              saveEntry(lines, false)
            }}
          />
        ))}
        <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s3)' }}>
          <button
            type="button" className="btn quiet small" style={{ flex: 1 }}
            onClick={() => {
              // 已经手写过就必须问一句：这三句话是今天唯一不可再生的东西，
              // 自动草稿随时能再生成，覆盖了就换不回来
              if (entry.auto) { saveEntry(autoDraft(s, today), true); toast('重写了一遍'); return }
              askConfirm({
                title: '用自动草稿覆盖你写的三句话？',
                detail: '你手写的内容会被替换掉，撤销不了。',
                confirmLabel: '覆盖',
                onYes: () => { saveEntry(autoDraft(s, today), true); toast('重写了一遍') },
              })
            }}
          >按今天的事重写</button>
        </div>
      </div>

      <Section label="明天的三件事" meta={`${tmTasks.length} / 3`} />
      <div className={tmTasks.length ? 'card flush' : 'card'}>
        {tmTasks.length === 0 ? (
          <p className="sub quiet" style={{ margin: 0 }}>睡前定好明天，早上就不用想了。</p>
        ) : (
          tmTasks.map((t) => (
            <Check key={t.id} done={t.done} bar={t.domain} title={t.title}
              onToggle={() => update((x) => ({ ...x, tasks: x.tasks.map((y) => (y.id === t.id ? { ...y, done: !y.done } : y)) }))} />
          ))
        )}
      </div>
      {tmTasks.length < 3 && (
        <div className="card" style={{ marginTop: 'var(--s2)' }}>
          <input className="field" value={tmTitle} placeholder="明天先做什么"
            onChange={(e) => setTmTitle(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') addTomorrow() }} />
          <div className="chips" style={{ marginTop: 'var(--s3)' }}>
            {ORDER.map((d) => (
              <Chip key={d} tap on={tmDomain === d} tone={tmDomain === d ? undefined : d} onClick={() => setTmDomain(d)}>
                {DOMAINS[d].short}
              </Chip>
            ))}
          </div>
          <button type="button" className="btn wide" style={{ marginTop: 'var(--s3)' }} onClick={addTomorrow} disabled={!tmTitle.trim()}>
            定下来
          </button>
        </div>
      )}

      <button type="button" className="btn ghost wide" style={{ marginTop: 'var(--s6)' }} onClick={() => go('today')}>
        回今日
      </button>
      </>}
    </div>
  )
}

/* ---------------------------------------------------------------- 时间轴 */

function Timeline() {
  const s = useStore((x) => x)

  /**
   * 一次遍历建索引，而不是在渲染循环里 filter。
   *
   * 原来每条时间轴都对 tasks 和 photos 各扫一遍全量：记满一年、
   * 攒下上千条任务之后就是每次渲染几十万次迭代，在手机上是能感觉到的卡。
   * 日记是要一直往前攒的东西，这里不能写成 O(天数 × 任务数)。
   */
  const { months, total } = useMemo(() => {
    const doneByDate = new Map<string, Task[]>()
    for (const t of s.tasks) {
      if (!t.done) continue
      const a = doneByDate.get(t.date)
      if (a) a.push(t)
      else doneByDate.set(t.date, [t])
    }
    const photoCount = new Map<string, number>()
    for (const p of s.photos) photoCount.set(p.date, (photoCount.get(p.date) ?? 0) + 1)

    const days = [...s.entries]
      .filter((e) => D.isDateKey(e.date))
      .sort((a, b) => b.date.localeCompare(a.date))

    // 按月分组：攒够三个月之后，一条通到底的列表就没法定位了
    const byMonth = new Map<string, typeof days>()
    for (const e of days) {
      const k = e.date.slice(0, 7)
      const a = byMonth.get(k)
      if (a) a.push(e)
      else byMonth.set(k, [e])
    }

    return {
      total: days.length,
      months: [...byMonth.entries()].map(([key, entries]) => ({
        key,
        label: D.monthCN(key),
        entries: entries.map((e) => ({
          e,
          done: doneByDate.get(e.date) ?? [],
          photos: photoCount.get(e.date) ?? 0,
        })),
      })),
    }
  }, [s.entries, s.tasks, s.photos])

  if (total === 0) {
    return (
      <>
        <Section label="时间轴" />
        <div className="card">
          <Empty
            icon={<IcNote />}
            title="还没有记录"
            sub="每天在「今天」那栏留下三句话，这里就会长出一条时间轴。"
          />
        </div>
      </>
    )
  }

  return (
    <>
      <Section label="时间轴" meta={`${total} 天`} />
      {months.map((m) => (
        <div key={m.key}>
          {/* 吸顶：往回翻的时候得一直知道自己在哪个月 */}
          <div className="tl-month">
            <span>{m.label}</span>
            <span className="tl-month-n">记了 {m.entries.length} 天</span>
          </div>
          <div className="tl">
            {m.entries.map(({ e, done, photos }) => {
              const dist = ORDER
                .map((d) => ({ d, n: done.filter((t) => t.domain === d).length }))
                .filter((x) => x.n > 0)
              return (
                <div className="tl-item" key={e.date}>
                  <div className="tl-date">
                    <span>{D.archiveCN(e.date)}</span>
                    {done.length > 0 && <span>· 完成 {done.length}</span>}
                    {photos > 0 && <span>· {photos} 张照片</span>}
                  </div>
                  <div className="tl-lines">
                    {e.lines.filter(Boolean).map((l, i) => <p key={i}>{l}</p>)}
                  </div>
                  {dist.length > 0 && (
                    <div className="tl-bar">
                      {dist.map(({ d, n }) => (
                        <i key={d} style={{ width: `${(n / done.length) * 100}%`, background: DOMAINS[d].color, display: 'block' }} />
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </>
  )
}
