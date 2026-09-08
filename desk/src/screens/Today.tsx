import { useState } from 'react'
import { get, update, useStore, uid } from '../lib/store'
import { DOMAINS, type Domain } from '../lib/types'
import * as D from '../lib/date'
import { askConfirm } from '../lib/confirm'
import { Section, Check, Chip, Empty, InstallNotice } from '../components/ui'
import { IcNote, IcWand } from '../components/icons'
import promptData from '../data/prompts.json'
import type { Route } from '../components/TabBar'

const ORDER: Domain[] = ['consult', 'byte', 'us', 'me']
const PROMPT_N = promptData.items.length
const PART_N = promptData.parts.length

export function Today({ go, onCapture, onPromptTool, toast }: { go: (r: Route) => void; onCapture: () => void; onPromptTool: () => void; toast: (t: string) => void }) {
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

      {/* 主角。
          首页原来是六段堆叠的仪表盘（重心/三件事/下一场/两条线/我们俩/国庆），
          每一段都要人去喂；而她天天真正用的 Prompt 管理器，藏在另一个 tab
          角落的一个图标里。她的原话是「太不好用了」。
          所以首页改成简介式的入口，把她最常用的那件事摆在第一屏。 */}
      <button type="button" className="hero" onClick={onPromptTool}>
        <span className="hero-h">
          <IcWand />
          <span className="hero-t">Prompt 管理器</span>
          <span className="hero-n">{PROMPT_N} 条 · {PART_N} 个零件</span>
        </span>
        <span className="hero-s">
          开工 · 救火 · 交付验收 · 取数 · 调研 · 成本 · 写东西 · 通用<br />
          占位符在 App 里填好再复制；叮嘱语和附录可以挂上去一起走。
        </span>
      </button>

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
              autoFocus className="field" value={newTitle} placeholder="还要做什么？"
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

      {/* 样例。
          「一份好报告长什么样」——这是她自己做过的那份持币者波动研究，
          第七节把六个混杂因素逐个列出来（币种人气 / 周末节律 / 时区错位 /
          被动曝光 / 前日惯性 / 严格因果），最后老实说了不能给因果。
          放在这儿是给写材料时当尺子用的，不是装饰。 */}
      <Section label="样例" meta="你自己做过的" />
      {/* target=_blank 是必须的：主屏 PWA 是 standalone 窗口，没有浏览器的返回键。
          同窗口跳过去她就困在报告里出不来了，只能杀掉 App 重进 */}
      <a className="card gocard sample" href="./sample-report.html" target="_blank" rel="noopener">
        <span className="row-t">一份好报告长什么样</span>
        <span className="row-s">
          持币者会对波动做出反应吗 —— 研究设计 → 剂量反应 → 时序 → 异质性 → 策略含义 →
          <strong>已排除与未排除</strong>
        </span>
        <span className="gocard-go">打开看 →</span>
      </a>

      {/* 复盘的常驻入口。
          它从底栏下去了（位子让给了 Prompt 管理器），所以这条不能再只在
          傍晚出现 —— 那样白天就没有任何一条路能走到复盘。
          内容一条没少，只是入口从底栏挪到了这儿。 */}
      <Section label="复盘" meta={D.isEvening() ? '今天到这儿' : undefined} />
      <button type="button" className="card gocard" onClick={() => go('review')}>
        <span className="row-t">{D.isEvening() ? '今天到这儿 · 去收尾' : '今天这三句 · 时间轴'}</span>
        <span className="row-s">写完今天的三句话，翻以前的每一天</span>
        <span className="gocard-go">去复盘 →</span>
      </button>

      <button type="button" className="sr" onClick={onCapture}>记一笔</button>
    </div>
  )
}

export function todayTaskCount(): number {
  const t = D.key()
  return get().tasks.filter((x) => x.date === t).length
}
