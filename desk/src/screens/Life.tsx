import { useState } from 'react'
import { update, useStore, uid } from '../lib/store'
import type { TripTodo, Wish } from '../lib/types'
import * as D from '../lib/date'
import { Section, Chip, Check, Empty, Progress, Segmented, InlineAdd } from '../components/ui'
import { askConfirm } from '../lib/confirm'
import { Photos } from '../components/Photos'
import { SPARKS } from '../data/sparks'
import { IcLife, IcTrip, IcTrash } from '../components/icons'

type Tab = 'us' | 'trip'
const WHO: Record<Wish['who'], string> = { him: '他想的', me: '我想的', both: '一起' }
const KIND: Record<TripTodo['kind'], string> = { book: '要订', plan: '要定', pack: '要带' }

export function Life({ toast }: { toast: (t: string) => void }) {
  const s = useStore((x) => x)
  const [tab, setTab] = useState<Tab>('us')

  return (
    <div className="screen">
      <p className="eyebrow" style={{ marginTop: 'var(--s3)' }}>不上班的那部分</p>
      <h1 className="h1">生活</h1>

      <Segmented<Tab>
        value={tab}
        onChange={setTab}
        options={[
          { key: 'us', label: '我们俩', color: 'var(--us-solid)' },
          { key: 'trip', label: s.trip.title?.trim() || '假期', color: 'var(--us-solid)' },
        ]}
      />

      {tab === 'us' ? <Us toast={toast} /> : <Trip toast={toast} />}
    </div>
  )
}

/* ---------------------------------------------------------------- 我们俩 */

function Us({ toast }: { toast: (t: string) => void }) {
  const s = useStore((x) => x)
  const [adding, setAdding] = useState(false)
  // 用天数当种子：同一天进来看到的是同一张，点一下才换
  const [spark, setSpark] = useState(() => Math.floor(Date.now() / 86400000))
  const [label, setLabel] = useState('')
  const [date, setDate] = useState('')
  const [countUp, setCountUp] = useState(false)
  const [showAllMoments, setShowAllMoments] = useState(false)

  const list = s.anniversaries
    .map((a) => ({ a, n: D.nextAnniversary(a.date) }))
    .sort((x, y) => x.n.days - y.n.days)

  const heard = s.notes.filter((n) => n.kind === 'us' && !n.handled)

  function add() {
    if (!label.trim() || !date) return
    update((x) => ({
      ...x,
      anniversaries: [...x.anniversaries, { id: uid(), label: label.trim(), date, recurring: true, countUp }],
    }))
    setLabel(''); setDate(''); setCountUp(false); setAdding(false)
    toast('记上了')
  }

  return (
    <>
      <Section label="日子" domain="us" meta={list.length ? `${list.length} 个` : undefined} />
      {list.length === 0 ? (
        <div className="card">
          <Empty
            tone="us"
            icon={<IcLife />}
            title="加上你们的日子"
            sub="在一起的那天、结婚纪念日、他的生日。填一个就够开始。"
            action={<button type="button" className="btn" style={{ background: 'var(--us)' }} onClick={() => setAdding(true)}>加第一个</button>}
          />
        </div>
      ) : (
        <div className="grid two">
          {list.map(({ a, n }) => {
            const together = Math.max(0, D.daysBetween(D.parse(a.date), new Date()))
            return (
              <div className="card" key={a.id} style={{ marginTop: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                  <span className="row-s" style={{ marginTop: 0 }}>{a.label}</span>
                  <button type="button" className="tap-del" aria-label={`删除 ${a.label}`}
                    onClick={() => askConfirm({
                      title: `删掉「${a.label}」？`,
                      detail: '这个日子会从列表里消失，撤销不了。',
                      onYes: () => {
                        update((x) => ({ ...x, anniversaries: x.anniversaries.filter((y) => y.id !== a.id) }))
                        toast('删掉了')
                      },
                    })}><IcTrash /></button>
                </div>
                {a.countUp ? (
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
                    <span className="big" style={{ color: 'var(--us-text)' }}>{together}</span>
                    <span className="sub">天了</span>
                  </div>
                ) : (
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
                    <span className="big" style={{ color: 'var(--us-text)' }}>{n.days}</span>
                    <span className="sub">{n.days === 0 ? '就是今天' : `天后 · 第 ${n.nth} 年`}</span>
                  </div>
                )}
                <p className="row-s" style={{ marginTop: 'var(--s2)' }}>{D.archiveCN(a.date)} 起</p>
              </div>
            )
          })}
        </div>
      )}

      {adding ? (
        <div className="card" style={{ marginTop: 'var(--s3)' }}>
          <input autoFocus className="field" value={label} placeholder="叫什么？比如：在一起 / 结婚 / 他生日"
            onChange={(e) => setLabel(e.target.value)} />
          <input type="date" className="field" style={{ marginTop: 'var(--s2)' }} value={date}
            onChange={(e) => setDate(e.target.value)} aria-label="日期" />
          <div className="chips" style={{ marginTop: 'var(--s3)' }}>
            <Chip tap on={!countUp} onClick={() => setCountUp(false)}>倒数到下一次</Chip>
            <Chip tap on={countUp} onClick={() => setCountUp(true)}>数已经多少天</Chip>
          </div>
          <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s3)' }}>
            <button type="button" className="btn" style={{ flex: 1, background: 'var(--us)' }} onClick={add} disabled={!label.trim() || !date}>记上</button>
            <button type="button" className="btn quiet" onClick={() => setAdding(false)}>取消</button>
          </div>
        </div>
      ) : list.length > 0 ? (
        <button type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s3)' }} onClick={() => setAdding(true)}>
          ＋ 再加一个
        </button>
      ) : null}

      <Photos toast={toast} />

      {/* 聊天启发：离线的一副牌。两个人都累到不想说话的晚上，用来起个头 */}
      <Section label="今晚聊点什么" domain="us" meta="点一下换一张" />
      <button
        type="button" className="spark" style={{ width: '100%', textAlign: 'left' }}
        onClick={() => setSpark((n) => n + 1)}
      >
        <span className="spark-q">{SPARKS[spark % SPARKS.length]}</span>
      </button>

      {/* 想对他说的话 */}
      <Section label="想对他说" domain="us" meta={s.moments.length ? `${s.moments.length} 条` : undefined} />
      {s.moments.length > 0 && (
        <div className="card">
          {(showAllMoments ? s.moments : s.moments.slice(0, 6)).map((m, i) => (
            <div key={m.id} className="row" style={i ? undefined : { marginTop: 0 }}>
              <span className="grow">
                <span className="row-t" style={{ fontWeight: 400, lineHeight: 1.5 }}>{m.text}</span>
                <span className="row-s">{D.relTime(m.createdAt)}</span>
              </span>
              <button
                type="button" className="tap-del" aria-label="删掉这句"
                onClick={() => askConfirm({
                  title: '删掉这句话？',
                  detail: m.text.slice(0, 40),
                  onYes: () => update((x) => ({ ...x, moments: x.moments.filter((y) => y.id !== m.id) })),
                })}
              ><IcTrash /></button>
            </div>
          ))}
          {s.moments.length > 6 && (
            <button type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s3)' }}
              onClick={() => setShowAllMoments((v) => !v)}>
              {showAllMoments ? '收起' : `还有 ${s.moments.length - 6} 句，全部展开`}
            </button>
          )}
        </div>
      )}
      <InlineAdd
        cta="写一句"
        placeholder="今天想对他说的一句话"
        onAdd={(text) => {
          update((x) => ({ ...x, moments: [{ id: uid(), text, createdAt: Date.now() }, ...x.moments] }))
          toast('记下了 ♡')
        }}
      />

      {/* 他提过的 —— 速记里标了「给老公」的都汇到这儿 */}
      <Section label="他提过的" domain="us" meta={heard.length ? `${heard.length} 条` : '空'} />
      <div className={heard.length ? 'card flush' : 'card'}>
        {heard.length === 0 ? (
          <p className="sub quiet" style={{ margin: 0 }}>
            听见他说想要什么，用中间那个 ＋ 记一笔，选「给老公」，就会出现在这里。
          </p>
        ) : (
          heard.map((n) => (
            <Check
              key={n.id}
              done={false}
              title={n.text}
              sub={D.relTime(n.createdAt)}
              onToggle={() => {
                update((x) => ({ ...x, notes: x.notes.map((y) => (y.id === n.id ? { ...y, handled: true } : y)) }))
                toast('搞定了 ♡')
              }}
            />
          ))
        )}
      </div>

      {/* 想一起做的事 */}
      <Section label="想一起做的事" domain="us" meta={`${s.wishes.filter((w) => w.done).length} / ${s.wishes.length}`} />
      <div className={s.wishes.length ? 'card flush' : 'card'}>
        {s.wishes.length === 0 ? (
          <p className="sub quiet" style={{ margin: 0 }}>还没写。想到一件就加一件。</p>
        ) : (
          s.wishes.map((w) => (
            <Check
              key={w.id}
              done={w.done}
              title={w.text}
              right={WHO[w.who]}
              onToggle={() => {
                update((x) => ({ ...x, wishes: x.wishes.map((y) => (y.id === w.id ? { ...y, done: !y.done } : y)) }))
                if (!w.done) toast('做到了 ♡')
              }}
            />
          ))
        )}
      </div>
      <InlineAdd
        cta="再想一件"
        placeholder="想和他一起做什么"
        onAdd={(text) => update((x) => ({ ...x, wishes: [...x.wishes, { id: uid(), text, who: 'both', done: false, createdAt: Date.now() }] }))}
      />
    </>
  )
}

/* ---------------------------------------------------------------- 假期 */

function Trip({ toast }: { toast: (t: string) => void }) {
  const s = useStore((x) => x)
  const t = s.trip
  const [editDates, setEditDates] = useState(false)
  const [addDay, setAddDay] = useState(false)
  // 改过行程日期之后再点「排一天」，默认值要跟着走。useState 的初始值只用一次，
  // 所以这里存「用户有没有手动选过」，没选过就跟随 trip.start
  const [dDate, setDDate] = useState<string | null>(null)
  const [dTitle, setDTitle] = useState('')

  // 没定日期就不要装作有假期。parse('') 会兜底成今天，倒数会显示「就是今天」，
  // 比空着更让人困惑
  const planned = D.isDateKey(t.start) && D.isDateKey(t.end)
  const left = planned ? D.daysUntil(t.start) : 0
  const over = planned && D.daysUntil(t.end) < 0
  const done = t.todos.filter((x) => x.done).length
  // 结束早于开始（手滑输错）时长度会是负数，显示成「-2 天假」
  const len = planned ? Math.max(1, D.daysBetween(D.parse(t.start), D.parse(t.end)) + 1) : 0

  if (!planned) {
    return (
      <>
        <Section label="假期" domain="us" />
        <div className="card">
          <Empty
            tone="us"
            icon={<IcTrip />}
            title="还没定假期"
            sub="定下哪天走哪天回，这里就会开始倒数，要订的要带的也有地方放。"
            action={
              <button type="button" className="btn" style={{ background: 'var(--us-solid)' }}
                onClick={() => {
                  const today = D.key()
                  const week = D.key(new Date(Date.now() + 6 * 86400000))
                  update((x) => ({ ...x, trip: { ...x.trip, title: x.trip.title || '假期', start: today, end: week } }))
                  toast('定好了，改一下日期')
                }}>
                定一个
              </button>
            }
          />
        </div>
      </>
    )
  }

  return (
    <>
      <Section label="倒数" domain="us" meta={`${len} 天假`} />
      <div className="card">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <span className="big" style={{ fontSize: '3rem', color: 'var(--us-text)' }}>
            {over ? '0' : Math.max(left, 0)}
          </span>
          <span className="sub" style={{ fontSize: 'var(--t-title)', fontWeight: 700 }}>
            {over ? '已经结束' : left > 0 ? '天后出发' : left === 0 ? '就是今天' : '假期中'}
          </span>
        </div>
        {editDates ? (
          <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s3)', flexWrap: 'wrap' }}>
            <input type="date" className="field" style={{ flex: 1, minWidth: 130 }} value={t.start} aria-label="开始"
              onChange={(e) => update((x) => ({ ...x, trip: { ...x.trip, start: e.target.value } }))} />
            <input type="date" className="field" style={{ flex: 1, minWidth: 130 }} value={t.end} aria-label="结束"
              onChange={(e) => update((x) => ({ ...x, trip: { ...x.trip, end: e.target.value } }))} />
            <button type="button" className="btn small quiet wide" onClick={() => setEditDates(false)}>好了</button>
          </div>
        ) : (
          <button type="button" className="row-s" style={{ marginTop: 'var(--s3)' }} onClick={() => setEditDates(true)}>
            {D.shortCN(t.start)} – {D.shortCN(t.end)} · 点这里改
          </button>
        )}
        <div style={{ marginTop: 'var(--s3)' }}>
          <Progress value={t.todos.length ? (done / t.todos.length) * 100 : 0} color="var(--us)" />
        </div>
        <p className="row-s" style={{ marginTop: 'var(--s2)' }}>{done} / {t.todos.length} 件已备好</p>
      </div>

      <Section label="出发前" domain="us" meta={done === t.todos.length && t.todos.length ? '都备好了' : undefined} />
      <div className={t.todos.length ? 'card flush' : 'card'}>
        {t.todos.length === 0 ? (
          <p className="sub quiet" style={{ margin: 0 }}>还没有要办的事。</p>
        ) : (
          t.todos.map((td) => (
            <Check
              key={td.id}
              done={td.done}
              title={td.text}
              right={`${KIND[td.kind]} · ${td.owner === 'me' ? '我' : td.owner === 'him' ? '他' : '一起'}`}
              onToggle={() => update((x) => ({
                ...x, trip: { ...x.trip, todos: x.trip.todos.map((y) => (y.id === td.id ? { ...y, done: !y.done } : y)) },
              }))}
            />
          ))
        )}
      </div>
      <InlineAdd
        cta="加一件要办的"
        placeholder="还要订什么、带什么"
        onAdd={(text) => update((x) => ({
          ...x, trip: { ...x.trip, todos: [...x.trip.todos, { id: uid(), text, kind: 'plan', owner: 'both', done: false }] },
        }))}
      />

      <Section label="行程" domain="us" meta={t.days.length ? `${t.days.length} 天已排` : '还是空的'} />
      {t.days.length === 0 ? (
        <div className="card">
          <Empty
            tone="us"
            icon={<IcTrip />}
            title="还没排行程"
            sub="不用一次排完。先落一天，剩下的路上再说。"
            action={<button type="button" className="btn" style={{ background: 'var(--us)' }} onClick={() => setAddDay(true)}>排第一天</button>}
          />
        </div>
      ) : (
        <div className="grid two">
          {[...t.days].sort((a, b) => a.date.localeCompare(b.date)).map((d) => (
            <div className="card" key={d.id} style={{ marginTop: 0 }}>
              <div className="row" style={{ marginTop: 0 }}>
                <i className="dbar" style={{ background: 'var(--us)' }} />
                <span className="grow">
                  <span className="row-t">{d.title}</span>
                  <span className="row-s">{D.shortCN(d.date)}</span>
                </span>
                <button type="button" className="tap-del" aria-label={`删除 ${d.title}`}
                  onClick={() => askConfirm({
                    title: `删掉「${d.title}」这天？`,
                    detail: d.detail ? `写好的安排也会一起没：${d.detail.slice(0, 30)}` : '撤销不了。',
                    onYes: () => {
                      update((x) => ({ ...x, trip: { ...x.trip, days: x.trip.days.filter((y) => y.id !== d.id) } }))
                      toast('删掉了')
                    },
                  })}><IcTrash /></button>
              </div>
              <textarea
                className="field" rows={2} style={{ marginTop: 'var(--s3)' }}
                value={d.detail} placeholder="这天想干嘛"
                onChange={(e) => update((x) => ({
                  ...x, trip: { ...x.trip, days: x.trip.days.map((y) => (y.id === d.id ? { ...y, detail: e.target.value } : y)) },
                }))}
              />
            </div>
          ))}
        </div>
      )}

      {addDay ? (
        <div className="card" style={{ marginTop: 'var(--s3)' }}>
          <input type="date" className="field" value={dDate ?? t.start} min={t.start} max={t.end}
            onChange={(e) => setDDate(e.target.value)} aria-label="哪天" />
          <input autoFocus className="field" style={{ marginTop: 'var(--s2)' }} value={dTitle}
            placeholder="这天叫什么？比如：出发 / 海边 / 回程"
            onChange={(e) => setDTitle(e.target.value)} />
          <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s3)' }}>
            <button type="button" className="btn" style={{ flex: 1, background: 'var(--us)' }} disabled={!dTitle.trim()}
              onClick={() => {
                update((x) => ({ ...x, trip: { ...x.trip, days: [...x.trip.days, { id: uid(), date: dDate ?? x.trip.start, title: dTitle.trim(), detail: '' }] } }))
                setDTitle(''); setAddDay(false)
              }}>排上</button>
            <button type="button" className="btn quiet" onClick={() => setAddDay(false)}>取消</button>
          </div>
        </div>
      ) : t.days.length > 0 ? (
        <button type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s3)' }} onClick={() => setAddDay(true)}>
          ＋ 再排一天
        </button>
      ) : null}
    </>
  )
}
