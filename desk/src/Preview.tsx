import { useMemo, useState } from 'react'
import type { Target } from './lib/shape'

/**
 * Prompt 预览。整张卡片就是复制按钮 —— 手指落在哪儿都行。
 *
 * 两处细节：
 * - 她在卡片上拖选了一段（只想要其中几行），松手时**不**触发整段复制，
 *   否则刚选好的那段会被整段 Prompt 顶掉。
 * - 材料那一段很长的话只露头几行。她刚贴进来，自己知道是什么；
 *   预览要让她一眼看到的是「我会让 AI 做什么」。复制的永远是全文。
 */

type Seg = { t: 'h' | 'dim' | 'tag' | 'txt'; s: string } | { t: 'more'; n: number }

const HEAD_LINES = 6
const FOLD_OVER = 10

function parse(text: string, target: Target, open: boolean): { segs: Seg[]; foldable: boolean } {
  const lines = text.split('\n')
  // 找材料那一段的起止行（不含围栏 / 标签本身）
  let a = -1, b = -1
  if (target === 'md') {
    const h = lines.findIndex((l) => l.startsWith('## 材料'))
    if (h >= 0 && /^`{3,}$/.test(lines[h + 1] ?? '')) {
      const f = lines[h + 1]
      const end = lines.indexOf(f, h + 2)
      if (end > 0) { a = h + 2; b = end }
    }
  } else {
    const m = lines[0]?.match(/^<(\w+) type="/)
    if (m) {
      const end = lines.indexOf(`</${m[1]}>`)
      if (end > 0) { a = 1; b = end }
    }
  }

  const out: Seg[] = []
  const push = (t: 'h' | 'dim' | 'tag' | 'txt', s: string) => {
    const last = out[out.length - 1]
    if (last && last.t === t && t === 'txt') (last as { s: string }).s += '\n' + s
    else out.push({ t, s })
  }
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i]
    if (a >= 0 && i >= a && i < b) {
      if (!open && b - a > FOLD_OVER && i === a + HEAD_LINES) {
        out.push({ t: 'more', n: b - a - HEAD_LINES })
        i = b - 1
        continue
      }
      push('txt', l)
      continue
    }
    if (target === 'md' && l.startsWith('## ')) push('h', l)
    else if (target === 'md' && /^`{3,}$/.test(l)) push('dim', l)
    else if (target === 'xml' && /^<\/?\w+(?:\s[^>]*)?>$/.test(l)) push('tag', l)
    else push('txt', l)
  }
  return { segs: out, foldable: a >= 0 && b - a > FOLD_OVER }
}

export function Preview(props: { text: string; target: Target; fresh: boolean; pulse: number; onCopy: () => void }) {
  const [open, setOpen] = useState(false)
  const { segs, foldable } = useMemo(() => parse(props.text, props.target, open), [props.text, props.target, open])

  return (
    <div
      className={'card' + (props.fresh ? ' fresh' : '')}
      role="button"
      tabIndex={0}
      aria-label="点一下复制整段 Prompt"
      onClick={() => {
        if (window.getSelection()?.toString()) return
        props.onCopy()
      }}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget) return
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); props.onCopy() }
      }}
    >
      <span className="card-hint" aria-hidden="true">{props.fresh ? '✓ 已复制' : '点任意处复制'}</span>
      <pre className="pv">
        {segs.map((g, i) =>
          g.t === 'more' ? (
            <button
              key={i}
              type="button"
              className="fold"
              onClick={(e) => { e.stopPropagation(); setOpen(true) }}
            >
              …… 还有 {g.n} 行（复制时一行不少），点这里展开
            </button>
          ) : g.t === 'txt' ? (
            <span key={i}>{g.s}{'\n'}</span>
          ) : (
            <span key={i} className={'pv-' + g.t}>{g.s}{'\n'}</span>
          ),
        )}
      </pre>
      {open && foldable && (
        <button type="button" className="fold up" onClick={(e) => { e.stopPropagation(); setOpen(false) }}>
          收起材料
        </button>
      )}
      {props.pulse > 0 && props.fresh && <span className="flash" key={props.pulse} aria-hidden="true" />}
    </div>
  )
}
