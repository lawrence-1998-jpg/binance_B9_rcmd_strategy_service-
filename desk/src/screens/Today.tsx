import { useState } from 'react'
import { get, update, useStore, uid } from '../lib/store'
import { DOMAINS, type Domain } from '../lib/types'
import * as D from '../lib/date'
import { askConfirm } from '../lib/confirm'
import { Section, Check, Chip, Empty, Progress, InstallNotice } from '../components/ui'
import { usePhotoURL } from '../lib/usePhoto'
import { IcNote, IcTrip } from '../components/icons'
import type { Route } from '../components/TabBar'

const ORDER: Domain[] = ['consult', 'byte', 'us', 'me']

export function Today({ go, onCapture, toast }: { go: (r: Route) => void; onCapture: () => void; toast: (t: string) => void }) {
  const today = D.key()
  const s = useStore((x) => x)
  const [editFocus, setEditFocus] = useState(false)
  const [draft, setDraft] = useState('')
  const [openTask, setOpenTask] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newDomain, setNewDomain] = useState<Domain>('consult')

  const tasks = s.tasks.filter((t) => t.date === today)
  const doneCount = tasks.filter((t) => t.done).length
  const focus = s.focus[today] ?? ''
  const full = tasks.length >= 3

  const nextMeeting = s.meetings
    .filter((m) => m.date > today || (m.date === today && D.minutesUntil(m.date, m.start) > -60))
    .sort((a, b) => (a.date + a.start).localeCompare(b.date + b.start))[0]

  const live = s.engagements.filter((e) => !e.archived)
  const anniv = s.anniversaries
    .map((a) => ({ a, n: D.nextAnniversary(a.date) }))
    .sort((x, y) => x.n.days - y.n.days)[0]
  const wish = s.wishes.find((w) => !w.done)
  // 一天固定一张，不每次进来都换 —— 回忆不该像老虎机
  const memory = s.photos.length
    ? s.photos[Math.floor(Date.now() / 86400000) % s.photos.length]
    : null

  // 没定日期就整块不出现。parse('') 会兜底成今天，不判断的话
  // 「清空全部数据」之后首屏会冒出一个「就是今天 09/02 – 09/02」的假期
  const tripSet = D.isDateKey(s.trip.start) && D.isDateKey(s.trip.end)
  const tripLeft = tripSet ? D.daysUntil(s.trip.start) : 0
  const tripOver = tripSet && D.daysUntil(s.trip.end) < 0
  const tripOn = tripSet && !tripOver && tripLeft <= 60

  function saveFocus() {
    const v = draft.trim()
    update((x) => ({ ...x, focus: { ...x.focus, [today]: v } }))
    setEditFocus(false)
  }

  function addTask() {
    const t = newTitle.trim()
    if (!t) { setAdding(false); return }
    update((x) => ({ ...x, tasks: [...x.tasks, { id: uid(), title: t, domain: newDomain, done: false, date: today }] }))
    setNewTitle('')
    setAdding(false)
  }

  return (
    <div className="screen">
      <InstallNotice />
      <p className="eyebrow" style={{ marginTop: 'var(--s3)' }}>{D.longCN()}</p>
      <h1 className="h1">{D.greeting()}</h1>

      {/* ① 今天的重心 —— 全屏唯一的深色反底块。一天只允许一句。 */}
      {editFocus ? (
        <div className="focus">
          <div className="focus-k">今天的重心</div>
          <input
            autoFocus
            className="field"
            style={{ background: 'rgba(245,234,216,.12)', color: 'var(--ground)', marginTop: 'var(--s2)' }}
            value={draft}
            placeholder="今天最重要的一件事是……"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') saveFocus(); if (e.key === 'Escape') setEditFocus(false) }}
          />
          <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s2)' }}>
            <button type="button" className="btn small" style={{ flex: 1 }} onClick={saveFocus}>定下来</button>
            <button type="button" className="btn small quiet" style={{ flex: 0, paddingInline: 'var(--s5)' }} onClick={() => setEditFocus(false)}>取消</button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className={`focus${focus ? '' : ' is-empty'}`}
          onClick={() => { setDraft(focus); setEditFocus(true) }}
        >
          <div className="focus-k">今天的重心</div>
          <div className={`focus-v${focus ? '' : ' hint'}`}>{focus || '写今天最重要的那件事'}</div>
        </button>
      )}

      {/* ② 今日三件事 —— 硬上限 3 */}
      <Section label="今日三件事" meta={tasks.length ? `${doneCount} / ${tasks.length} 完成` : '还没定'} />
      <div className={tasks.length ? 'card flush' : 'card'}>
        {tasks.length === 0 ? (
          <Empty
            icon={<IcNote />}
            title="今天还没定"
            sub="先写一件最想推进的事。剩下两件可以晚点补。"
            action={<button type="button" className="btn" onClick={() => setAdding(true)}>写第一件</button>}
          />
        ) : (
          tasks.map((t) => (
            <div key={t.id}>
              <Check
                done={t.done}
                bar={t.domain}
                title={t.title}
                right={t.est ? `${t.est}m` : undefined}
                moreOpen={openTask === t.id}
                onMore={() => setOpenTask(openTask === t.id ? null : t.id)}
                onToggle={() => update((x) => ({ ...x, tasks: x.tasks.map((y) => (y.id === t.id ? { ...y, done: !y.done } : y)) }))}
              />
              {openTask === t.id && (
                <div className="chips" style={{ padding: '0 0 12px 31px' }}>
                  <Chip tap onClick={() => {
                    const tm = new Date(); tm.setDate(tm.getDate() + 1)
                    update((x) => ({ ...x, tasks: x.tasks.map((y) => (y.id === t.id ? { ...y, date: D.key(tm), done: false } : y)) }))
                    setOpenTask(null); toast('推到明天了')
                  }}>推到明天</Chip>
                  <Chip tap onClick={() => askConfirm({
                    title: '删掉这件事？',
                    detail: t.title,
                    onYes: () => {
                      update((x) => ({ ...x, tasks: x.tasks.filter((y) => y.id !== t.id) }))
                      setOpenTask(null); toast('已删除')
                    },
                  })}>删掉</Chip>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {tasks.length > 0 && !full && (
        adding ? (
          <div className="card" style={{ marginTop: 'var(--s2)' }}>
            <input
              autoFocus className="field" value={newTitle} placeholder="第几件事？"
              onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') addTask(); if (e.key === 'Escape') setAdding(false) }}
            />
            <div className="chips" style={{ marginTop: 'var(--s3)' }}>
              {ORDER.map((d) => (
                <Chip key={d} tone={newDomain === d ? undefined : d} on={newDomain === d} tap onClick={() => setNewDomain(d)}>
                  {DOMAINS[d].short}
                </Chip>
              ))}
            </div>
            <button type="button" className="btn wide" style={{ marginTop: 'var(--s3)' }} onClick={addTask}>加进来</button>
          </div>
        ) : (
          <button type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s2)' }} onClick={() => setAdding(true)}>
            ＋ 还能加 {3 - tasks.length} 件
          </button>
        )
      )}

      <div className="grid two" style={{ marginTop: 0 }}>
        <div>
          {/* ③ 下一场 */}
          <Section label="下一场" meta={nextMeeting ? whenLabel(nextMeeting.date, nextMeeting.start, today) : '空'} />
          <div className="card">
            {nextMeeting ? (
              <div className="row">
                <i className="dbar" style={{ background: DOMAINS[nextMeeting.domain].color }} />
                <span className="grow">
                  <span className="row-t">{nextMeeting.title}</span>
                  <span className="row-s">
                    {nextMeeting.date === today ? '今天' : D.shortCN(nextMeeting.date)} {nextMeeting.start}
                    {nextMeeting.end ? `–${nextMeeting.end}` : ''}
                    {nextMeeting.note ? ` · ${nextMeeting.note}` : ''}
                  </span>
                </span>
              </div>
            ) : (
              <p className="sub quiet" style={{ margin: 0 }}>接下来没有安排。</p>
            )}
          </div>

          {/* ④ 两条线 */}
          <Section label="两条线" meta={live.length ? `${live.length} 件在跑` : undefined} />
          {live.length === 0 ? (
            // 两张写着「0 件在跑 · 都没卡」的卡片占掉一屏，说的却是「什么都没有」。
            // 空的时候要么别占地方，要么给个入口——不能又占地方又不说事
            <button type="button" className="card" style={{ width: '100%', textAlign: 'left' }} onClick={() => go('work')}>
              <span className="row-t">还没有在跑的事</span>
              <span className="row-s">去「工作」加上手上的项目和需求 →</span>
            </button>
          ) : (
          <button type="button" className="card" style={{ width: '100%', textAlign: 'left' }} onClick={() => go('work')}>
            {(['consult', 'byte'] as const).map((d, i) => {
              const list = live.filter((e) => e.domain === d)
              const stuck = list.filter((e) => e.blocker).length
              return (
                <div className="row" key={d} style={i ? undefined : { marginTop: 0 }}>
                  <i className="dbar" style={{ background: DOMAINS[d].color }} />
                  <span className="grow">
                    <span className="row-t">{DOMAINS[d].label}</span>
                    <span className="row-s">{list.length} 件在跑{stuck ? ` · ${stuck} 件卡住` : ' · 都没卡'}</span>
                  </span>
                  {stuck > 0 && <i className="dot dot-warn" aria-label="有卡住的" />}
                </div>
              )
            })}
          </button>
          )}
        </div>

        <div>
          {/* ⑤ 我们俩 */}
          <Section label="我们俩" domain="us" meta={memory ? '那天的我们' : anniv ? `${anniv.n.days} 天后` : undefined} />
          <button type="button" className="card" style={{ width: '100%', textAlign: 'left' }} onClick={() => go('life')}>
            {memory ? (
              <>
                <Memory id={memory.id} rev={memory.rev ?? 0} />
                <span className="row-s" style={{ marginTop: 'var(--s3)' }}>{D.archiveCN(memory.date)}</span>
                <p className="row-t" style={{ margin: '2px 0 0', fontWeight: 600 }}>
                  {memory.caption || '那天的我们'}
                </p>
                {anniv && (
                  <p className="sub quiet" style={{ margin: '6px 0 0' }}>
                    {anniv.a.label} 还有 {anniv.n.days} 天
                  </p>
                )}
              </>
            ) : anniv ? (
              <>
                <span className="row-s" style={{ marginTop: 0 }}>{anniv.a.label}</span>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
                  <span className="big" style={{ color: 'var(--us-text)' }}>{anniv.n.days}</span>
                  <span className="sub">天后 · 第 {anniv.n.nth} 年</span>
                </div>
              </>
            ) : wish ? (
              <>
                <span className="row-s" style={{ marginTop: 0 }}>想一起做的事</span>
                <p className="row-t" style={{ margin: '4px 0 0' }}>{wish.text}</p>
                <p className="sub quiet" style={{ margin: '6px 0 0' }}>去「生活」加上你们的纪念日 →</p>
              </>
            ) : (
              <p className="sub quiet" style={{ margin: 0 }}>去「生活」加上你们的日子 →</p>
            )}
          </button>

          {/* ⑥ 国庆（时令模块，假期结束自动消失） */}
          {tripOn && (
            <>
              <Section label={s.trip.title || '假期'} domain="us" meta={`${s.trip.todos.filter((t) => t.done).length} / ${s.trip.todos.length} 备好`} />
              <button type="button" className="card" style={{ width: '100%', textAlign: 'left' }} onClick={() => go('life')}>
                <div className="row" style={{ marginTop: 0 }}>
                  <IcTrip />
                  <span className="grow">
                    <span className="row-t">
                      {tripLeft > 0 ? `还有 ${tripLeft} 天` : tripLeft === 0 ? '就是今天' : '假期中'}
                    </span>
                    <span className="row-s">{D.shortCN(s.trip.start)} – {D.shortCN(s.trip.end)}</span>
                  </span>
                </div>
                <div style={{ marginTop: 'var(--s3)' }}>
                  <Progress
                    value={s.trip.todos.length ? (s.trip.todos.filter((t) => t.done).length / s.trip.todos.length) * 100 : 0}
                    color="var(--us)"
                  />
                </div>
              </button>
            </>
          )}
        </div>
      </div>

      {D.isEvening() && (
        <button type="button" className="btn ghost wide" style={{ marginTop: 'var(--s6)' }} onClick={() => go('review')}>
          今天到这儿 · 去收尾
        </button>
      )}

      <button type="button" className="sr" onClick={onCapture}>记一笔</button>
    </div>
  )
}

/** 右侧只说「还有多久」；具体日期时间在卡片副行里，别两处重复 */
function whenLabel(date: string, start: string, today: string): string {
  if (date !== today) {
    const d = D.daysUntil(date)
    return d === 1 ? '明天' : `${d} 天后`
  }
  const m = D.minutesUntil(date, start)
  if (m < 0) return '进行中'
  return `${D.humanMinutes(m)}后`
}

export function todayTaskCount(): number {
  const t = D.key()
  return get().tasks.filter((x) => x.date === t).length
}

/** 今日屏上的回忆缩略图 */
function Memory({ id, rev }: { id: string; rev: number }) {
  const url = usePhotoURL(id, rev)
  return (
    <span
      style={{
        display: 'block', width: '100%', aspectRatio: '4/3',
        borderRadius: 'var(--r-inner)', overflow: 'hidden', background: 'var(--well)',
      }}
    >
      {url && <img src={url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
    </span>
  )
}
