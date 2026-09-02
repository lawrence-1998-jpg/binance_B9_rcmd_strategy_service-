import { useMemo, useRef, useState } from 'react'
import { update, useStore } from '../lib/store'
import { buildPrompt, parseOutline, TARGETS, DEPTHS, type Depth, type Target } from '../lib/prompt'
import { copyText } from '../lib/copy'
import { Section, Chip } from '../components/ui'
import { IcClose, IcCopy } from '../components/icons'

/**
 * 提纲 → Prompt。
 * 输入你要问的几条，出一段能直接贴给 Claude Code / GPT 的调研 prompt。
 * 生成是纯本地的模板拼装，不联网、不调模型，所以飞行模式也能用。
 */
export function PromptTool({ onClose, toast }: { onClose: () => void; toast: (t: string) => void }) {
  const draft = useStore((x) => x.promptDraft)
  const [showOut, setShowOut] = useState(false)
  const out = useRef<HTMLTextAreaElement>(null)

  const prompt = useMemo(() => buildPrompt(draft), [draft])
  const count = parseOutline(draft.outline).length

  function patch(p: Partial<typeof draft>) {
    update((x) => ({ ...x, promptDraft: { ...x.promptDraft, ...p } }))
  }

  async function copy() {
    if (!prompt) return
    const ok = await copyText(prompt)
    if (ok) { toast('复制好了，去贴给它'); return }
    // 剪贴板没权限：把文本选中，让人自己复制
    setShowOut(true)
    setTimeout(() => { out.current?.focus(); out.current?.select() }, 50)
    toast('已选中，长按复制')
  }

  return (
    <div className="sheet" role="dialog" aria-modal="true" aria-label="提纲转 Prompt">
      <div className="sheet-in">
        <div className="sheet-head">
          <span className="eyebrow">提纲 → Prompt</span>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭"><IcClose /></button>
        </div>

        <p className="sub" style={{ color: 'var(--ink-2)', marginTop: 'var(--s3)' }}>
          把你要问的几条写下来，出一段能直接贴走的调研 prompt。
          模板里带了防编数字的约束——这类问题模型最爱一本正经给假百分比。
        </p>

        <Section label="提纲" meta={count ? `${count} 条` : '一行一条'} />
        <textarea
          className="field"
          rows={5}
          value={draft.outline}
          onChange={(e) => patch({ outline: e.target.value })}
          placeholder={'一行一条，比如：\n抖音有没有出现过投稿流失，怎么解决的\n作者流量反馈占多少流量，怎么做的'}
          style={{ fontFamily: 'var(--f-cjk)', lineHeight: 1.6 }}
        />

        <Section label="调研对象" meta="选填" />
        <input
          className="field" value={draft.subject} placeholder="比如：抖音"
          onChange={(e) => patch({ subject: e.target.value })}
        />

        <Section label="我的处境" meta="填了效果好很多" />
        <textarea
          className="field" rows={2} value={draft.context}
          placeholder="一句话说清你为什么问这个，比如：我在给一个 UGC 社区做投稿量下滑的诊断"
          onChange={(e) => patch({ context: e.target.value })}
        />

        <Section label="贴给谁" />
        <div className="chips">
          {TARGETS.map((t) => (
            <Chip key={t.key} tap on={draft.target === t.key} onClick={() => patch({ target: t.key as Target })}>
              {t.label}
            </Chip>
          ))}
        </div>
        <p className="sub" style={{ color: 'var(--ink-3)', marginTop: 'var(--s2)' }}>
          {TARGETS.find((t) => t.key === draft.target)?.hint}
        </p>

        <Section label="要多深" />
        <div className="chips">
          {DEPTHS.map((d) => (
            <Chip key={d.key} tap on={draft.depth === d.key} onClick={() => patch({ depth: d.key as Depth })}>
              {d.label}
            </Chip>
          ))}
        </div>
        <p className="sub" style={{ color: 'var(--ink-3)', marginTop: 'var(--s2)' }}>
          {DEPTHS.find((d) => d.key === draft.depth)?.hint}
        </p>

        <div className="sheet-foot">
          <button type="button" className="btn wide" onClick={() => void copy()} disabled={!prompt}>
            <IcCopy /> 复制 Prompt
          </button>
          <button
            type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s2)' }}
            onClick={() => setShowOut((v) => !v)} disabled={!prompt}
          >
            {showOut ? '收起' : `先看看长什么样（${prompt.length} 字）`}
          </button>
        </div>

        {showOut && (
          <textarea
            ref={out}
            className="field"
            rows={16}
            readOnly
            value={prompt}
            onFocus={(e) => e.currentTarget.select()}
            style={{ marginTop: 'var(--s3)', fontFamily: 'var(--f-mono)', fontSize: '10.5px', lineHeight: 1.55 }}
          />
        )}

        <div style={{ height: 'var(--s7)' }} />
      </div>
    </div>
  )
}
