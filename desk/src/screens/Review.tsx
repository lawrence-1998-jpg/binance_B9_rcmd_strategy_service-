import { useState } from 'react'
import { update, useStore, uid } from '../lib/store'
import { DOMAINS, NOTE_KINDS, type Domain, type NoteKind } from '../lib/types'
import * as D from '../lib/date'
import { Section, Check, Chip, Empty } from '../components/ui'
import { IcGear, IcNote } from '../components/icons'
import type { Route } from '../components/TabBar'

const ORDER: Domain[] = ['consult', 'byte', 'us', 'me']

export function Review({ go, onSettings, toast }: { go: (r: Route) => void; onSettings: () => void; toast: (t: string) => void }) {
  const s = useStore((x) => x)
  const today = D.key()
  const tomorrow = D.key(new Date(Date.now() + 86400000))
  const [log, setLog] = useState(() => s.logs.find((l) => l.date === today)?.text ?? '')
  const [tmTitle, setTmTitle] = useState('')
  const [tmDomain, setTmDomain] = useState<Domain>('consult')

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

  function saveLog() {
    update((x) => ({
      ...x,
      logs: [...x.logs.filter((l) => l.date !== today), { date: today, text: log.trim(), doneCount: done.length }],
    }))
    toast('记下了')
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
      <p className="sub" style={{ marginTop: 'var(--s2)' }}>
        完成 {done.length} 件，记了 {s.notes.filter((n) => D.key(new Date(n.createdAt)) === today).length} 条
        {weekTotal ? `，这周一共做完 ${weekTotal} 件。` : '。'}
      </p>

      {/* 完成情况：没做完的排在完成的后面，并且已经自动顺延 —— 不制造亏欠感 */}
      <Section label="今天" meta={tasks.length ? `${done.length} / ${tasks.length}` : undefined} />
      <div className={tasks.length ? 'card flush' : 'card'}>
        {tasks.length === 0 ? (
          <p className="sub" style={{ margin: 0, color: 'var(--ink-3)' }}>今天没有列三件事。也没关系。</p>
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
          pending.slice(0, 8).map((n) => (
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
      </div>

      <Section label="一句话日志" meta="选填" />
      <div className="card">
        <textarea className="field" rows={2} value={log} placeholder="今天最大的收获是……"
          onChange={(e) => setLog(e.target.value)} onBlur={saveLog} />
      </div>

      <Section label="明天的三件事" meta={`${tmTasks.length} / 3`} />
      <div className={tmTasks.length ? 'card flush' : 'card'}>
        {tmTasks.length === 0 ? (
          <p className="sub" style={{ margin: 0, color: 'var(--ink-3)' }}>睡前定好明天，早上就不用想了。</p>
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
    </div>
  )
}
