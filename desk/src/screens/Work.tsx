import { useState } from 'react'
import { update, useStore, uid } from '../lib/store'
import { DOMAINS, stageOf, stagesFor, isLive, type Engagement, type Inquiry as Q, type Status } from '../lib/types'
import * as D from '../lib/date'
import { askConfirm } from '../lib/confirm'
import { Section, Dot, Chip, Progress, Empty, Segmented, GrowText } from '../components/ui'
import { IcNote, IcTrash, IcWand, IcCopy } from '../components/icons'
import { Inquiry, splitOutline } from './Inquiry'
import { buildPrompt, splitAnswer } from '../lib/prompt'
import { copyText } from '../lib/copy'
import { buildBrief } from '../lib/brief'

type Line = 'consult' | 'byte'

export function Work({ toast, onPromptTool }: { toast: (t: string) => void; onPromptTool: () => void }) {
  const s = useStore((x) => x)
  const [line, setLine] = useState<Line>('consult')
  const [open, setOpen] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [client, setClient] = useState('')
  const [openQ, setOpenQ] = useState<string | null>(null)
  const [outlineFor, setOutlineFor] = useState<string | null>(null)
  const [outline, setOutline] = useState('')
  const [pasteFor, setPasteFor] = useState<string | null>(null)
  const [pasted, setPasted] = useState('')
  const [leftover, setLeftover] = useState<string | null>(null)

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

  // 搁置 / 不查了的不算在分母里 —— 否则「我决定不查了」会让进度永远差一截
  const qOf = (id: string) => s.inquiries.filter((q) => q.engagementId === id && isLive(q))
  const done = (id: string) => qOf(id).filter((q) => stageOf(q) === 'concluded').length
  // 进度不再手填。以前那个百分比是拍脑袋的数，现在它等于「有结论的条数 / 总条数」——
  // 这个数说的是真事
  const pct = (id: string) => { const n = qOf(id).length; return n ? (done(id) / n) * 100 : 0 }

  function patch(id: string, p: Partial<Engagement>) {
    update((x) => ({ ...x, engagements: x.engagements.map((e) => (e.id === id ? { ...e, ...p, updatedAt: Date.now() } : e)) }))
  }

  return (
    <>
    <div className="screen">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginTop: 'var(--s3)' }}>
        <div>
          <p className="eyebrow">两条线</p>
          <h1 className="h1">工作</h1>
        </div>
        <button type="button" className="icon-btn" onClick={onPromptTool} aria-label="Prompt 管理器">
          <IcWand />
        </button>
      </div>

      <Segmented<Line>
        value={line}
        onChange={(v) => { setLine(v); setOpen(null) }}
        options={[
          // 选中态是实心底，要用 *-solid 变体：原色上放浅色 13px 字只有 3.4:1
          { key: 'consult', label: '咨询顾问', color: 'var(--consult-solid)' },
          { key: 'byte', label: '字节产品', color: 'var(--byte-solid)' },
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
                  <Chip tone={line}>{qOf(e.id).length ? `${done(e.id)} / ${qOf(e.id).length}` : `${e.progress}%`}</Chip>
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
                  <Progress value={pct(e.id)} color={DOMAINS[line].color} />
                </div>

                <div className="row-s" style={{ display: 'flex', justifyContent: 'space-between', marginTop: 'var(--s2)' }}>
                  <span>{qOf(e.id).length
                    ? `${done(e.id)} / ${qOf(e.id).length} 条有结论`
                    : (e.next ? `下一步 ${e.next}` : '还没拆提纲')}</span>
                  <span>{D.relTime(e.updatedAt)}</span>
                </div>
              </button>

              {/* 调研线 —— 这是把「状态牌」变成「流水线」的地方 */}
              <Flow
                onPasteSet={() => { setPasteFor(e.id); setPasted(''); setLeftover(null) }}
                eng={e}
                onOpenQ={setOpenQ}
                onAddOutline={() => { setOutlineFor(e.id); setOutline('') }}
                toast={toast}
              />

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

                  {qOf(e.id).length === 0 && (<>
                  {/* 只在还没拆提纲时才手填。拆了之后进度 = 有结论条数 / 总条数，
                      那个数是真的；再留一个手填的滑块只会和它打架 */}
                  <p className="eyebrow" style={{ marginTop: 'var(--s4)' }}>进度 {e.progress}%</p>
                  <input
                    type="range" min={0} max={100} step={5} value={e.progress}
                    style={{ width: '100%', marginTop: 'var(--s2)', accentColor: DOMAINS[line].color }}
                    onChange={(ev) => patch(e.id, { progress: Number(ev.target.value) })}
                    aria-label="进度"
                  />
                  </>)}

                  <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s4)' }}>
                    <button type="button" className="btn quiet small" style={{ flex: 1 }}
                      onClick={() => { patch(e.id, { archived: true }); setOpen(null); toast('已归档') }}>
                      归档
                    </button>
                    <button type="button" className="btn ghost small" style={{ flex: '0 0 auto', color: 'var(--alert)' }}
                      onClick={() => askConfirm({
                        title: `删掉「${e.name}」？`,
                        detail: '阶段、卡点、下一步都会一起没，撤销不了。只是想让它从列表消失的话，用旁边的「归档」。',
                        onYes: () => {
                          update((x) => ({ ...x, engagements: x.engagements.filter((y) => y.id !== e.id) }))
                          setOpen(null); toast('已删除')
                        },
                      })} aria-label="删除">
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

      <button type="button" className="btn ghost wide" style={{ marginTop: 'var(--s6)' }} onClick={onPromptTool}>
        Prompt 管理器 →
      </button>

      <p className="sub quiet" style={{ marginTop: 'var(--s4)', textAlign: 'center' }}>
        提纲进去，材料出来。中间四步都能在手机上走完，AI 那一步去 Claude Code 或 GPT 里跑。
      </p>
    </div>

    {openQ && (() => {
      const q = s.inquiries.find((x) => x.id === openQ)
      if (!q) return null
      return <Inquiry q={q} eng={s.engagements.find((e) => e.id === q.engagementId)}
        onClose={() => setOpenQ(null)} toast={toast} />
    })()}

    {pasteFor && (() => {
      const live = s.inquiries.filter((q) => q.engagementId === pasteFor && isLive(q))
      return (
        <div className="sheet" role="dialog" aria-modal="true" aria-label="贴回整套结果">
          <div className="sheet-in">
            <div className="sheet-head">
              <span className="eyebrow">整套结果贴回来</span>
              <button type="button" className="icon-btn" onClick={() => setPasteFor(null)} aria-label="关闭">✕</button>
            </div>
            <p className="sub quiet" style={{ marginTop: 'var(--s3)' }}>
              把 AI 回的**一整段**原样贴进来。按题号自动分到下面这 {live.length} 条上，
              编号跟列表里的一致。<strong>不会覆盖已有的材料</strong>——同一条上原来有东西的话是追在后面。
            </p>
            <GrowText
              value={pasted} minRows={8} aria-label="整套结果"
              placeholder={'把 AI 回的整段贴这儿，形如：\n\n## 1. 第一个问题\n[事实] ……\n\n## 2. 第二个问题\n[推断] ……'}
              onChange={setPasted}
            />

            {leftover && (
              <div className="warn" style={{ marginTop: 'var(--s3)' }}>
                <p className="row-t" style={{ margin: 0 }}>有一段没归到任何一条</p>
                <p className="sub" style={{ marginTop: 'var(--s1)' }}>
                  多半是开头的前言或结尾的「还没搞清楚的」。没扔，放这儿了：
                </p>
                <pre className="leftover">{leftover}</pre>
                <button type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s2)' }}
                  onClick={() => { void copyText(leftover).then((ok) => toast(ok ? '复制好了' : '复制不了，长按选中')) }}>
                  <IcCopy /> 复制这段
                </button>
              </div>
            )}

            <div className="sheet-foot">
              <button type="button" className="btn wide" disabled={!pasted.trim()}
                onClick={() => {
                  const r = splitAnswer(pasted, live.length)
                  if (!r) {
                    // 认不出题号就明说，绝不瞎猜着往里塞 —— 塞错比不塞更糟
                    toast('看不出题号（要形如「## 1.」），没敢乱分')
                    return
                  }
                  let filled = 0
                  let appended = 0
                  update((x) => ({
                    ...x,
                    inquiries: x.inquiries.map((q) => {
                      const i = live.findIndex((y) => y.id === q.id)
                      if (i < 0 || !r.parts[i]) return q
                      const had = (q.findings ?? '').trim()
                      had ? appended++ : filled++
                      return {
                        ...q,
                        findings: had ? `${had}\n\n———\n\n${r.parts[i]}` : r.parts[i],
                        updatedAt: Date.now(),
                      }
                    }),
                  }))
                  setLeftover(r.rest || null)
                  toast(`分好了：${filled} 条填上${appended ? `，${appended} 条追加` : ''}`)
                  if (!r.rest) { setPasteFor(null); setPasted('') }
                }}>
                按题号分到各条
              </button>
              {leftover && (
                <button type="button" className="btn quiet wide" style={{ marginTop: 'var(--s2)' }}
                  onClick={() => { setPasteFor(null); setPasted(''); setLeftover(null) }}>
                  知道了，关掉
                </button>
              )}
            </div>
            <div style={{ height: 'var(--s6)' }} />
          </div>
        </div>
      )
    })()}

    {outlineFor && (
      <div className="sheet" role="dialog" aria-modal="true" aria-label="拆提纲">
        <div className="sheet-in">
          <div className="sheet-head">
            <span className="eyebrow">提纲拆成调研线</span>
            <button type="button" className="icon-btn" onClick={() => setOutlineFor(null)} aria-label="关闭">✕</button>
          </div>
          <p className="sub quiet" style={{ marginTop: 'var(--s3)' }}>
            一行一条。约访提纲、客户问的问题、自己列的疑点都行——
            每一条会变成一条能一路走到结论的调研线。
          </p>
          <GrowText
            value={outline} minRows={6} aria-label="提纲"
            placeholder={'比如：\n1、UGC 投稿用户流量下滑导致投稿流失，抖音出现过吗，怎么解决的\n2、抖音做作者流量反馈的流量占比大概多少，怎么做的'}
            onChange={setOutline}
          />
          <div className="sheet-foot">
            <button type="button" className="btn wide" disabled={!outline.trim()}
              onClick={() => {
                // 拆的同时就把每条的 prompt 生成好。
                // 她的原话是「贴进去它就能变成一套可以让我直接复制的」——
                // 拆完还要一条条点进去点「生成」，那就还是在让她伺候工具
                const eng = s.engagements.find((e) => e.id === outlineFor)
                const made = splitOutline(outline, outlineFor).map((q) => ({
                  ...q,
                  prompt: buildPrompt({
                    outline: q.question, subject: eng?.client ?? '',
                    context: s.promptDraft.context, target: s.promptDraft.target, depth: s.promptDraft.depth,
                  }),
                }))
                update((x) => ({ ...x, inquiries: [...x.inquiries, ...made] }))
                setOutlineFor(null); setOutline('')
                toast(`拆成 ${made.length} 条，Prompt 也一起生成好了`)
              }}>
              拆开
            </button>
          </div>
          <div style={{ height: 'var(--s6)' }} />
        </div>
      </div>
    )}
    </>
  )
}

/**
 * 一个 engagement 底下的调研线列表。
 *
 * 每行左边一个小圆点标着走到第几站，点进去就是那条线的四步。
 * 全部有结论之后，底下会出现「出材料」——从提纲进去，从材料出来，
 * 这条链闭合了才叫工作流。
 */
function Flow({
  eng, onOpenQ, onAddOutline, onPasteSet, toast,
}: {
  eng: Engagement
  onOpenQ: (id: string) => void
  onAddOutline: () => void
  onPasteSet: () => void
  toast: (t: string) => void
}) {
  const s = useStore((x) => x)
  const all = s.inquiries.filter((q) => q.engagementId === eng.id)
  const live = all.filter(isLive)
  const finished = live.filter((q) => stageOf(q) === 'concluded')

  if (all.length === 0) {
    return (
      <button type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s2)' }} onClick={onAddOutline}>
        ＋ 贴提纲，拆成调研线
      </button>
    )
  }

  return (
    <div style={{ marginTop: 'var(--s3)', paddingTop: 'var(--s3)', borderTop: '1px solid var(--line)' }}>
      {all.map((q) => {
        const st = stageOf(q)
        const steps = stagesFor(q)
        const i = steps.findIndex((x) => x.key === st)
        const n = live.indexOf(q) + 1
        return (
          <button key={q.id} type="button" className={`qrow${q.closed ? ' off' : ''}`} onClick={() => onOpenQ(q.id)}>
            <i className={`qdot s${i}`} aria-hidden="true">{q.closed ? '—' : steps[i].short}</i>
            <span className="grow">
              <span className="row-t">
                {/* 题号跟「整套 Prompt」里的编号是同一个，贴回来才对得上 */}
                {!q.closed && <span className="qn">{n}</span>}
                {q.question || '（还没写问题）'}
              </span>
              <span className="row-s">
                {q.closed === 'parked' ? '先搁着' : q.closed === 'dropped' ? '不查了' : steps[i].label}
                {q.kind === 'interview' ? ' · 访谈' : ''}
                {q.facts?.length ? ` · ${q.facts.length} 条数据` : ''}
                {q.conclusion ? ` · ${q.conclusion.slice(0, 16)}` : ''}
              </span>
              {!!q.keywords?.length && (
                <span className="kw-row">{q.keywords.slice(0, 4).map((k) => <i key={k} className="kw">{k}</i>)}</span>
              )}
            </span>
          </button>
        )
      })}

      {/* 整套：一次复制、一次贴回。她的活是「问一次拿一大段回来」，
          不是「一条一条问 n 次」——工具得按她的节奏来 */}
      <SetBar eng={eng} live={live} onPasteSet={onPasteSet} toast={toast} />

      <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s2)' }}>
        <button type="button" className="btn quiet small" style={{ flex: 1 }} onClick={onAddOutline}>＋ 再拆一段提纲</button>
        {finished.length > 0 && (
          <button type="button" className="btn small" style={{ flex: 1, background: 'var(--ok-solid)' }}
            onClick={() => { void copyText(buildBrief(eng, all)).then((ok) => toast(ok ? `${finished.length} 条结论已复制` : '复制不了，长按选中')) }}>
            <IcCopy /> 出材料
          </button>
        )}
      </div>
    </div>
  )
}

/** 整套 Prompt = 把这个 engagement 下还在盘子上的问题合成一份，编号跟列表一致 */
export function setPromptOf(eng: Engagement, live: Q[], draft: { context: string; target: 'tooled' | 'plain'; depth: 'quick' | 'deep' }) {
  return buildPrompt({
    outline: live.map((q) => q.question).join('\n'),
    subject: eng.client ?? '',
    context: draft.context,
    target: draft.target,
    depth: draft.depth,
  })
}

function SetBar({
  eng, live, onPasteSet, toast,
}: {
  eng: Engagement
  live: Q[]
  onPasteSet: () => void
  toast: (t: string) => void
}) {
  const draft = useStore((x) => x.promptDraft)
  if (live.length === 0) return null
  return (
    <div className="setbar">
      <button type="button" className="btn small" style={{ flex: 1 }}
        onClick={() => {
          void copyText(setPromptOf(eng, live, draft)).then((ok) =>
            toast(ok ? `整套 Prompt 已复制（${live.length} 条），去问吧` : '复制不了，长按选中'))
        }}>
        <IcCopy /> 复制整套 · {live.length} 条
      </button>
      <button type="button" className="btn quiet small" style={{ flex: 1 }} onClick={onPasteSet}>
        贴回整套结果
      </button>
    </div>
  )
}
