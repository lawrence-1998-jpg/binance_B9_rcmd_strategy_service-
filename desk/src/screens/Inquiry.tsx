import { useState } from 'react'
import { update, useStore, uid } from '../lib/store'
import { STAGES, stageOf, type Inquiry as Q, type Engagement } from '../lib/types'
import { buildPrompt } from '../lib/prompt'
import { copyText } from '../lib/copy'
import { askConfirm } from '../lib/confirm'
import { GrowText, Section } from '../components/ui'
import { IcClose, IcCopy, IcTrash } from '../components/icons'

/**
 * 一条调研线的四步。
 *
 * 这一屏是整个东西从「备忘录」变成「工作台」的地方：
 * 提纲里的一条问题进来，出去的时候是一句能写进材料的结论，
 * 中间每一步的产出都留在原地——prompt 不再只丢剪贴板，
 * 研究结果有地方回来，结论跟着问题走。
 *
 * 四步之间不强制：可以跳着填（有时候答案就在脑子里，不用查）。
 * 但默认顺序是给「不知道下一步该干嘛」的时候看的。
 */
export function Inquiry({
  q, eng, onClose, toast,
}: { q: Q; eng: Engagement | undefined; onClose: () => void; toast: (t: string) => void }) {
  const s = useStore((x) => x)
  const [gen, setGen] = useState(false)
  const stage = stageOf(q)
  const idx = STAGES.findIndex((x) => x.key === stage)

  function patch(p: Partial<Q>) {
    update((x) => ({
      ...x,
      inquiries: x.inquiries.map((y) => (y.id === q.id ? { ...y, ...p, updatedAt: Date.now() } : y)),
    }))
  }

  function makePrompt() {
    // 复用「提纲 → Prompt」那套模板和它的四条硬约束——最要紧的是「不许编数字」。
    // 主题默认取客户/方向名，处境取 engagement 的阶段，都能改
    const text = buildPrompt({
      outline: q.question,
      subject: eng?.client ?? '',
      context: s.promptDraft.context,
      target: s.promptDraft.target,
      depth: s.promptDraft.depth,
    })
    patch({ prompt: text })
    setGen(true)
    toast('生成好了，可以复制去问了')
  }

  return (
    <div className="sheet" role="dialog" aria-modal="true" aria-label="调研线">
      <div className="sheet-in">
        <div className="sheet-head">
          <span className="eyebrow">{eng?.name ?? '调研'}</span>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭"><IcClose /></button>
        </div>

        {/* 四步的进度条：看一眼就知道这条走到哪、下一步是什么 */}
        <ol className="flow">
          {STAGES.map((st, i) => (
            <li key={st.key} className={`flow-i${i < idx ? ' done' : i === idx ? ' now' : ''}`}>
              <i className="flow-d">{i < idx ? '✓' : i + 1}</i>
              <span>{st.label}</span>
            </li>
          ))}
        </ol>

        {/* ① 问题 */}
        <Section label="① 要搞清楚的" />
        <div className="card">
          <GrowText
            value={q.question}
            aria-label="问题"
            placeholder="一句话说清要搞清楚什么"
            onChange={(v) => patch({ question: v })}
          />
        </div>

        {/* ② Prompt */}
        <Section label="② 拿去问 AI" meta={q.prompt ? '已生成' : undefined} />
        <div className="card">
          {q.prompt ? (
            <>
              <div className="pbody" style={{ maxHeight: gen ? 'none' : 190, overflow: 'hidden', position: 'relative' }}>
                {q.prompt}
              </div>
              <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s3)' }}>
                <button type="button" className="btn small" style={{ flex: 1 }}
                  onClick={() => { void copyText(q.prompt!).then((ok) => toast(ok ? '复制好了，去 Claude Code 粘上' : '复制不了，长按选中')) }}>
                  <IcCopy /> 一键复制
                </button>
                <button type="button" className="btn quiet small" onClick={() => setGen((v) => !v)}>
                  {gen ? '收起' : '看全文'}
                </button>
              </div>
              <button type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s2)' }} onClick={makePrompt}>
                按现在的问题重新生成
              </button>
            </>
          ) : (
            <>
              <p className="sub quiet" style={{ margin: 0 }}>
                照四条硬约束生成——最要紧的是<strong>不许编数字</strong>：
                没有公开来源就必须写「没有公开数据」，再给带推导的区间估算并标注。
              </p>
              <button type="button" className="btn wide" style={{ marginTop: 'var(--s3)' }}
                disabled={!q.question.trim()} onClick={makePrompt}>
                生成 Prompt
              </button>
            </>
          )}
        </div>

        {/* ③ 结果 */}
        <Section label="③ 把结果贴回来" meta={q.findings ? `${q.findings.length} 字` : undefined} />
        <div className="card">
          <GrowText
            value={q.findings ?? ''}
            minRows={4}
            aria-label="研究结果"
            placeholder="AI 给的原文贴这里。原样贴，先别删——删过的东西回头想核对就没了。"
            onChange={(v) => patch({ findings: v })}
          />
        </div>

        {/* ④ 结论 */}
        <Section label="④ 你的一句话" meta={q.conclusion ? '这条完成了' : undefined} />
        <div className="card">
          <p className="sub quiet" style={{ margin: '0 0 var(--s2)' }}>
            上面那堆是材料，这一句才是你的。写进材料里的是这句。
          </p>
          <GrowText
            value={q.conclusion ?? ''}
            aria-label="结论"
            placeholder="所以呢？一句话。"
            onChange={(v) => patch({ conclusion: v })}
          />
        </div>

        <div className="sheet-foot">
          <button type="button" className="btn ghost wide danger-text"
            onClick={() => askConfirm({
              title: '删掉这条调研？',
              detail: `「${q.question.slice(0, 24)}」连同生成的 prompt 和贴回来的材料一起没，撤销不了。`,
              onYes: () => {
                update((x) => ({ ...x, inquiries: x.inquiries.filter((y) => y.id !== q.id) }))
                onClose(); toast('删掉了')
              },
            })}>
            <IcTrash /> 删掉这条
          </button>
        </div>
        <div style={{ height: 'var(--s7)' }} />
      </div>
    </div>
  )
}

/** 把一段提纲拆成若干条调研线，挂到一个 engagement 下 */
export function splitOutline(outline: string, engagementId: string): Q[] {
  return outline
    .split('\n')
    .map((l) => l.replace(/^\s*(?:\d+[.、)]|[-*·])\s*/, '').trim())
    .filter(Boolean)
    .map((question) => ({
      id: uid(), engagementId, question,
      createdAt: Date.now(), updatedAt: Date.now(),
    }))
}
