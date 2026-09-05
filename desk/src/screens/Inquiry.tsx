import { useState } from 'react'
import { update, useStore, uid } from '../lib/store'
import {
  CONFIDENCE, stagesFor, stageOf,
  type Fact, type Inquiry as Q, type Engagement, type Kind,
} from '../lib/types'
import { buildPrompt, buildInterviewGuide } from '../lib/prompt'
import { copyText } from '../lib/copy'
import { askConfirm } from '../lib/confirm'
import { GrowText, Section, Segmented } from '../components/ui'
import { IcClose, IcCopy, IcTrash } from '../components/icons'

/**
 * 一条调研线的四步。
 *
 * 提纲里的一条问题进来，出去的时候是一句能写进材料的结论。
 * 中间每一步的产出都留在原地：prompt 存着、材料贴回来、
 * 抄到的数字带着出处、查的时候用过的词记下来。
 *
 * 两条路走同一条流水线：拿去问 AI，或者拿去问人（约访）。
 * 第二站产出的东西完全不同 —— 给人的提纲是能照着念的，不是堆约束的。
 */
export function Inquiry({
  q, eng, onClose, toast,
}: { q: Q; eng: Engagement | undefined; onClose: () => void; toast: (t: string) => void }) {
  const s = useStore((x) => x)
  const [full, setFull] = useState(false)
  const kind: Kind = q.kind ?? 'ai'
  const steps = stagesFor(q)
  const idx = steps.findIndex((x) => x.key === stageOf(q))
  const isTalk = kind === 'interview'

  function patch(p: Partial<Q>) {
    update((x) => ({
      ...x,
      inquiries: x.inquiries.map((y) => (y.id === q.id ? { ...y, ...p, updatedAt: Date.now() } : y)),
    }))
  }

  function make() {
    const spec = {
      outline: q.question,
      subject: eng?.client ?? '',
      context: s.promptDraft.context,
      target: s.promptDraft.target,
      depth: s.promptDraft.depth,
    }
    patch({ prompt: isTalk ? buildInterviewGuide(spec) : buildPrompt(spec) })
    setFull(true)
    toast(isTalk ? '访谈提纲好了' : '生成好了，可以复制去问了')
  }

  /** 换路子的时候，第二站的产出要重做 —— 给模型的和给人的是两种东西 */
  function switchKind(k: Kind) {
    if (k === kind) return
    const spec = {
      outline: q.question, subject: eng?.client ?? '',
      context: s.promptDraft.context, target: s.promptDraft.target, depth: s.promptDraft.depth,
    }
    patch({ kind: k, prompt: q.prompt ? (k === 'interview' ? buildInterviewGuide(spec) : buildPrompt(spec)) : undefined })
  }

  return (
    <div className="sheet" role="dialog" aria-modal="true" aria-label="调研线">
      <div className="sheet-in">
        <div className="sheet-head">
          <span className="eyebrow">{eng?.name ?? '调研'}</span>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭"><IcClose /></button>
        </div>

        {q.closed && (
          <div className="warn" style={{ marginTop: 'var(--s3)' }}>
            <p className="row-t" style={{ margin: 0 }}>
              {q.closed === 'parked' ? '这条先搁着了' : '这条决定不查了'}
            </p>
            <p className="sub" style={{ marginTop: 'var(--s1)' }}>
              不算进这个项目的进度里。出材料时会照实列在「没搞清楚的」下面。
            </p>
            <button type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s3)' }}
              onClick={() => { patch({ closed: undefined }); toast('重新放回盘子里') }}>
              重新打开
            </button>
          </div>
        )}

        <ol className="flow">
          {steps.map((st, i) => (
            <li key={st.key} className={`flow-i${q.closed ? ' off' : i < idx ? ' done' : i === idx ? ' now' : ''}`}>
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
          <div style={{ marginTop: 'var(--s3)' }}>
            <Segmented
              value={kind}
              options={[
                { key: 'ai', label: '查资料' },
                { key: 'interview', label: '约访谈' },
              ]}
              onChange={switchKind}
            />
          </div>
        </div>

        {/* ② Prompt / 访谈提纲 */}
        <Section label={isTalk ? '② 访谈提纲' : '② 拿去问 AI'} meta={q.prompt ? '已生成' : undefined} />
        <div className="card">
          {q.prompt ? (
            <>
              <div className="pbody" style={{ maxHeight: full ? 'none' : 190, overflow: 'hidden' }}>{q.prompt}</div>
              <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s3)' }}>
                <button type="button" className="btn small" style={{ flex: 1 }}
                  onClick={() => { void copyText(q.prompt!).then((ok) => toast(ok ? '复制好了' : '复制不了，长按选中')) }}>
                  <IcCopy /> 一键复制
                </button>
                <button type="button" className="btn quiet small" onClick={() => setFull((v) => !v)}>
                  {full ? '收起' : '看全文'}
                </button>
              </div>
              <button type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s2)' }} onClick={make}>
                按现在的问题重新生成
              </button>
            </>
          ) : (
            <>
              <p className="sub quiet" style={{ margin: 0 }}>
                {isTalk
                  ? '照访谈的套路生成：开场、每题的追问、收尾那句「还有什么我没问到的」，以及访谈后 10 分钟内要补的三件事。'
                  : <>照四条硬约束生成——最要紧的是<strong>不许编数字</strong>：没有公开来源就必须写「没有公开数据」，再给带推导的区间估算并标注。</>}
              </p>
              <button type="button" className="btn wide" style={{ marginTop: 'var(--s3)' }}
                disabled={!q.question.trim()} onClick={make}>
                {isTalk ? '生成访谈提纲' : '生成 Prompt'}
              </button>
            </>
          )}
        </div>

        {/* ③ 材料 */}
        <Section label={isTalk ? '③ 访谈记录' : '③ 把结果贴回来'} meta={q.findings ? `${q.findings.length} 字` : undefined} />
        <div className="card">
          <GrowText
            value={q.findings ?? ''}
            minRows={4}
            aria-label={isTalk ? '访谈记录' : '研究结果'}
            placeholder={isTalk
              ? '他原话怎么说的就怎么记。别急着总结——总结是下一步的事。'
              : 'AI 给的原文贴这里。原样贴，先别删——删过的东西回头想核对就没了。'}
            onChange={(v) => patch({ findings: v })}
          />
        </div>

        <Keywords q={q} patch={patch} all={s.inquiries} />
        <Facts q={q} patch={patch} toast={toast} />

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
          {!q.closed && (
            <div style={{ display: 'flex', gap: 'var(--s2)' }}>
              <button type="button" className="btn quiet small" style={{ flex: 1 }}
                onClick={() => { patch({ closed: 'parked' }); toast('先搁着了') }}>
                先搁着
              </button>
              <button type="button" className="btn quiet small" style={{ flex: 1 }}
                onClick={() => { patch({ closed: 'dropped' }); toast('不查了') }}>
                不查了
              </button>
            </div>
          )}
          <button type="button" className="btn ghost wide danger-text" style={{ marginTop: 'var(--s2)' }}
            onClick={() => askConfirm({
              title: '删掉这条调研？',
              detail: `「${q.question.slice(0, 24)}」连同 prompt、贴回来的材料和 ${q.facts?.length ?? 0} 条数据一起没，撤销不了。只是暂时不查的话，用「先搁着」。`,
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

/**
 * 关键词。
 *
 * 她的原话：「复制完之后，我可能还能对他做一些关键词记录」。
 * 用处是回头找得回来 —— 三周后写报告时，「当时是搜什么词搜到的」
 * 比那段材料本身还难想起来。
 *
 * 建议词从她自己以前用过的里出，不是我编的分类：
 * 研究仓库那套的经验是受控词表比自由填好，而这里唯一可信的词表
 * 就是她自己的用词。
 */
function Keywords({ q, patch, all }: { q: Q; patch: (p: Partial<Q>) => void; all: Q[] }) {
  const [text, setText] = useState('')
  const list = q.keywords ?? []
  const used = [...new Set(all.flatMap((x) => x.keywords ?? []))].filter((k) => !list.includes(k)).slice(0, 8)

  function add(k: string) {
    const v = k.trim()
    if (!v || list.includes(v)) { setText(''); return }
    patch({ keywords: [...list, v] })
    setText('')
  }

  return (
    <>
      <Section label="关键词" meta={list.length ? `${list.length} 个` : undefined} />
      <div className="card">
        {list.length > 0 && (
          <div className="kw-row" style={{ marginBottom: 'var(--s3)' }}>
            {list.map((k) => (
              <button key={k} type="button" className="kw on"
                onClick={() => patch({ keywords: list.filter((x) => x !== k) })}
                aria-label={`删掉关键词 ${k}`}>
                {k} ✕
              </button>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', gap: 'var(--s2)' }}>
          <input
            className="field" style={{ flex: 1 }} value={text} aria-label="加关键词"
            placeholder="搜过的词、材料的主题……"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(text) } }}
          />
          <button type="button" className="btn small" aria-label="加上这个关键词"
            disabled={!text.trim()} onClick={() => add(text)}>加</button>
        </div>
        {used.length > 0 && (
          <div className="kw-row" style={{ marginTop: 'var(--s3)' }}>
            <span className="sub quiet" style={{ marginRight: 'var(--s1)' }}>用过的：</span>
            {used.map((k) => (
              <button key={k} type="button" className="kw" onClick={() => add(k)}>＋ {k}</button>
            ))}
          </div>
        )}
      </div>
    </>
  )
}

/**
 * 记下来的数据。
 *
 * 这是「不许编数字」那条硬约束的另一半：prompt 逼模型把没出处的数字标出来，
 * 这里逼我自己在抄下一个数字时，同时写清它是什么、哪儿来的、有多信。
 *
 * 因为这些数字最后会出现在给客户的材料里。到那时候，
 * 「15%」和「某篇 2023 年报道说约 15%，中等置信」是两回事。
 */
function Facts({ q, patch, toast }: { q: Q; patch: (p: Partial<Q>) => void; toast: (t: string) => void }) {
  const list = q.facts ?? []
  const [open, setOpen] = useState(false)
  const [f, setF] = useState<Omit<Fact, 'id'>>({ value: '', what: '', source: '', confidence: 'mid' })

  function save() {
    if (!f.value.trim() || !f.what.trim()) return
    patch({ facts: [...list, { ...f, id: uid() }] })
    setF({ value: '', what: '', source: '', confidence: 'mid' })
    setOpen(false)
    toast('记下了')
  }

  return (
    <>
      <Section label="记下来的数据" meta={list.length ? `${list.length} 条` : undefined} />
      <div className="card">
        {list.map((x) => (
          <div key={x.id} className="fact">
            <div className="fact-h">
              <span className="fact-v">{x.value}</span>
              <span className={`fact-c c-${x.confidence}`}>
                {CONFIDENCE.find((c) => c.key === x.confidence)?.label} 置信
              </span>
              <button type="button" className="tap-del" aria-label="删掉这条数据"
                onClick={() => askConfirm({
                  title: '删掉这条数据？',
                  detail: `「${x.value} · ${x.what}」删了就没了。`,
                  onYes: () => patch({ facts: list.filter((y) => y.id !== x.id) }),
                })}>
                <IcTrash />
              </button>
            </div>
            <p className="fact-w">{x.what}</p>
            <p className={`fact-s${x.source.trim() ? '' : ' none'}`}>
              {x.source.trim() || '没有出处 —— 材料里会照实标出来'}
            </p>
          </div>
        ))}

        {open ? (
          <div style={{ marginTop: list.length ? 'var(--s4)' : 0 }}>
            <input className="field" value={f.value} aria-label="数字或事实"
              placeholder="约 15% / 2021 年上线 / 三档"
              onChange={(e) => setF({ ...f, value: e.target.value })} />
            <input className="field" style={{ marginTop: 'var(--s2)' }} value={f.what} aria-label="它是什么"
              placeholder="它是什么？比如「作者流量反馈的流量占比」"
              onChange={(e) => setF({ ...f, what: e.target.value })} />
            <input className="field" style={{ marginTop: 'var(--s2)' }} value={f.source} aria-label="出处"
              placeholder="哪儿来的？没有就空着，材料里会照实说"
              onChange={(e) => setF({ ...f, source: e.target.value })} />
            <div style={{ marginTop: 'var(--s3)' }}>
              <Segmented
                value={f.confidence}
                options={CONFIDENCE.map((c) => ({ key: c.key, label: c.label }))}
                onChange={(c) => setF({ ...f, confidence: c })}
              />
            </div>
            <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s3)' }}>
              <button type="button" className="btn small" style={{ flex: 1 }}
                disabled={!f.value.trim() || !f.what.trim()} onClick={save}>记下来</button>
              <button type="button" className="btn quiet small" onClick={() => setOpen(false)}>算了</button>
            </div>
          </div>
        ) : (
          <button type="button" className="btn quiet small wide" style={{ marginTop: list.length ? 'var(--s3)' : 0 }}
            onClick={() => setOpen(true)}>
            ＋ 记一个数字
          </button>
        )}
      </div>
    </>
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
