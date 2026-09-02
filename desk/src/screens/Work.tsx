import { useState } from 'react'
import { update, useStore, uid } from '../lib/store'
import { DOMAINS, type Engagement, type Status } from '../lib/types'
import * as D from '../lib/date'
import { Section, Dot, Chip, Progress, Empty, Segmented } from '../components/ui'
import { IcNote, IcTrash } from '../components/icons'

type Line = 'consult' | 'byte'

export function Work({ toast }: { toast: (t: string) => void }) {
  const s = useStore((x) => x)
  const [line, setLine] = useState<Line>('consult')
  const [open, setOpen] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [client, setClient] = useState('')

  const list = s.engagements.filter((e) => e.domain === line && !e.archived)
  const stuck = list.filter((e) => e.blocker).length

  function add() {
    const n = name.trim()
    if (!n) { setAdding(false); return }
    update((x) => ({
      ...x,
      engagements: [...x.engagements, {
        id: uid(), name: n, domain: line, client: client.trim() || undefined,
        stage: '刚开始', blocker: '', status: 'ok', progress: 0,
        next: '', updatedAt: Date.now(),
      }],
    }))
    setName(''); setClient(''); setAdding(false)
  }

  function patch(id: string, p: Partial<Engagement>) {
    update((x) => ({ ...x, engagements: x.engagements.map((e) => (e.id === id ? { ...e, ...p, updatedAt: Date.now() } : e)) }))
  }

  return (
    <div className="screen">
      <p className="eyebrow" style={{ marginTop: 'var(--s3)' }}>两条线</p>
      <h1 className="h1">工作</h1>

      <Segmented<Line>
        value={line}
        onChange={(v) => { setLine(v); setOpen(null) }}
        options={[
          { key: 'consult', label: '咨询顾问', color: 'var(--consult)' },
          { key: 'byte', label: '字节产品', color: 'var(--byte)' },
        ]}
      />

      <Section
        label={DOMAINS[line].label}
        domain={line}
        meta={list.length ? (stuck ? `${stuck} 件卡住` : '都没卡') : undefined}
      />

      {list.length === 0 ? (
        <div className="card">
          <Empty
            tone={line}
            icon={<IcNote />}
            title={line === 'consult' ? '还没有客户项目' : '还没有需求'}
            sub="加一件正在推进的事。手机上只看状态，细节回电脑改。"
            action={<button type="button" className="btn" style={{ background: DOMAINS[line].color }} onClick={() => setAdding(true)}>加一件</button>}
          />
        </div>
      ) : (
        <div className="grid two">
          {list.map((e) => (
            <div className="card" key={e.id} style={{ marginTop: 0 }}>
              <button
                type="button"
                style={{ width: '100%', textAlign: 'left' }}
                onClick={() => setOpen(open === e.id ? null : e.id)}
                aria-expanded={open === e.id}
              >
                <div className="row" style={{ marginTop: 0 }}>
                  <Dot status={e.status} />
                  <span className="grow">
                    <span className="row-t">{e.name}</span>
                    <span className="row-s">{e.client ? `${e.client} · ` : ''}{e.stage}</span>
                  </span>
                  <Chip tone={line}>{e.progress}%</Chip>
                </div>

                {/* 卡点是这一屏真正的主角，不是进度 */}
                <p
                  style={{
                    margin: 'var(--s3) 0 0', fontSize: 'var(--t-body)', fontWeight: 600,
                    color: e.blocker ? 'var(--alert)' : 'var(--ok-deep)',
                  }}
                >
                  {e.blocker ? `卡在：${e.blocker}` : '没卡住'}
                </p>

                <div style={{ marginTop: 'var(--s3)' }}>
                  <Progress value={e.progress} color={DOMAINS[line].color} />
                </div>

                <div className="row-s" style={{ display: 'flex', justifyContent: 'space-between', marginTop: 'var(--s2)' }}>
                  <span>{e.next ? `下一步 ${e.next}` : '下一步待定'}{e.nextDate ? ` · ${D.shortCN(e.nextDate)}` : ''}</span>
                  <span>{D.relTime(e.updatedAt)}</span>
                </div>
              </button>

              {open === e.id && (
                <div style={{ marginTop: 'var(--s4)', paddingTop: 'var(--s4)', borderTop: '1px solid var(--line)' }}>
                  <p className="eyebrow">改状态</p>
                  <div className="chips" style={{ marginTop: 'var(--s2)' }}>
                    {(['ok', 'warn', 'bad'] as Status[]).map((st) => (
                      <Chip key={st} tap on={e.status === st} onClick={() => patch(e.id, { status: st })}>
                        {st === 'ok' ? '正常' : st === 'warn' ? '要注意' : '阻塞'}
                      </Chip>
                    ))}
                  </div>

                  <p className="eyebrow" style={{ marginTop: 'var(--s4)' }}>卡在哪</p>
                  <input
                    className="field" style={{ marginTop: 'var(--s2)' }}
                    value={e.blocker} placeholder="不卡就留空"
                    onChange={(ev) => patch(e.id, { blocker: ev.target.value })}
                  />

                  <p className="eyebrow" style={{ marginTop: 'var(--s4)' }}>阶段</p>
                  <input
                    className="field" style={{ marginTop: 'var(--s2)' }}
                    value={e.stage} placeholder="现在做到哪一步"
                    onChange={(ev) => patch(e.id, { stage: ev.target.value })}
                  />

                  <p className="eyebrow" style={{ marginTop: 'var(--s4)' }}>下一步</p>
                  <input
                    className="field" style={{ marginTop: 'var(--s2)' }}
                    value={e.next} placeholder="下一个动作是什么"
                    onChange={(ev) => patch(e.id, { next: ev.target.value })}
                  />

                  <p className="eyebrow" style={{ marginTop: 'var(--s4)' }}>进度 {e.progress}%</p>
                  <input
                    type="range" min={0} max={100} step={5} value={e.progress}
                    style={{ width: '100%', marginTop: 'var(--s2)', accentColor: DOMAINS[line].color }}
                    onChange={(ev) => patch(e.id, { progress: Number(ev.target.value) })}
                    aria-label="进度"
                  />

                  <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s4)' }}>
                    <button type="button" className="btn quiet small" style={{ flex: 1 }}
                      onClick={() => { patch(e.id, { archived: true }); setOpen(null); toast('已归档') }}>
                      归档
                    </button>
                    <button type="button" className="btn ghost small" style={{ flex: '0 0 auto', color: 'var(--alert)' }}
                      onClick={() => {
                        update((x) => ({ ...x, engagements: x.engagements.filter((y) => y.id !== e.id) }))
                        setOpen(null); toast('已删除')
                      }} aria-label="删除">
                      <IcTrash />
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {adding ? (
        <div className="card" style={{ marginTop: 'var(--s3)' }}>
          <input autoFocus className="field" value={name} placeholder={line === 'consult' ? '项目叫什么' : '需求叫什么'}
            onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') add() }} />
          <input className="field" style={{ marginTop: 'var(--s2)' }} value={client}
            placeholder={line === 'consult' ? '客户（选填）' : '方向 / 团队（选填）'}
            onChange={(e) => setClient(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') add() }} />
          <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s3)' }}>
            <button type="button" className="btn" style={{ flex: 1 }} onClick={add}>加进来</button>
            <button type="button" className="btn quiet" style={{ flex: '0 0 auto' }} onClick={() => setAdding(false)}>取消</button>
          </div>
        </div>
      ) : list.length > 0 ? (
        <button type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s3)' }} onClick={() => setAdding(true)}>
          ＋ 加一件
        </button>
      ) : null}

      <p className="sub" style={{ marginTop: 'var(--s6)', color: 'var(--ink-3)', textAlign: 'center' }}>
        手机上只改状态和卡点。真正的活儿回电脑做。
      </p>
    </div>
  )
}
