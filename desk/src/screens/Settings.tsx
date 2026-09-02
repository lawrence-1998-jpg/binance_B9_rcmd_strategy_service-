import { useRef, useState } from 'react'
import { exportJSON, importJSON, resetToEmpty, useStore } from '../lib/store'
import { saveFile } from '../lib/save'
import * as D from '../lib/date'
import { Section } from '../components/ui'
import { IcClose } from '../components/icons'

export function Settings({ onClose, toast }: { onClose: () => void; toast: (t: string) => void }) {
  const s = useStore((x) => x)
  const [confirmClear, setConfirmClear] = useState(false)
  const [manual, setManual] = useState<string | null>(null)
  const file = useRef<HTMLInputElement>(null)

  const counts = [
    ['事项', s.tasks.length],
    ['速记', s.notes.length],
    ['在跑', s.engagements.filter((e) => !e.archived).length],
    ['日子', s.anniversaries.length],
  ] as const

  async function download() {
    const json = exportJSON()
    const outcome = await saveFile(`deskside-${D.key()}.json`, json)
    if (outcome === 'saved') { setManual(null); toast('导出好了'); return }
    if (outcome === 'declined') { toast('取消了'); return }
    // 这个环境不让页面存文件 —— 摊出来让人自己复制，不静默失败
    setManual(json)
  }

  async function pick(f: File | undefined) {
    if (!f) return
    const ok = importJSON(await f.text())
    toast(ok ? '导入成功' : '这个文件读不了')
  }

  return (
    <div className="sheet" role="dialog" aria-modal="true" aria-label="设置">
      <div className="sheet-in">
        <div className="sheet-head">
          <span className="eyebrow">设置</span>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭"><IcClose /></button>
        </div>

        <Section label="你的数据" meta="全部存在这台设备上" />
        <div className="card">
          <div style={{ display: 'flex', gap: 'var(--s5)', flexWrap: 'wrap' }}>
            {counts.map(([label, n]) => (
              <div key={label}>
                <div className="big" style={{ fontSize: '1.5rem' }}>{n}</div>
                <div className="row-s">{label}</div>
              </div>
            ))}
          </div>
          <p className="sub" style={{ marginTop: 'var(--s4)', color: 'var(--ink-2)' }}>
            数据只存在这台设备的浏览器里，不上传任何地方。换设备、清缓存都会没——
            所以每周导出一次。
          </p>
          <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s4)' }}>
            <button type="button" className="btn" style={{ flex: 1 }} onClick={() => void download()}>导出 JSON</button>
            <button type="button" className="btn quiet" style={{ flex: 1 }} onClick={() => file.current?.click()}>导入</button>
          </div>
          <input ref={file} type="file" accept="application/json" hidden
            onChange={(e) => { void pick(e.target.files?.[0]); e.target.value = '' }} />

          {manual && (
            <div style={{ marginTop: 'var(--s4)' }}>
              <p className="sub" style={{ color: 'var(--ink-2)', marginBottom: 'var(--s2)' }}>
                这个环境不允许网页直接存文件。下面是你的全部数据，<strong>长按全选复制</strong>，
                贴到备忘录或任何地方存着；要恢复时用旁边的「导入」。
              </p>
              <textarea
                className="field" rows={6} readOnly value={manual}
                onFocus={(e) => e.currentTarget.select()}
                style={{ fontFamily: 'var(--f-mono)', fontSize: '10px', lineHeight: 1.5 }}
              />
              <button type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s2)' }}
                onClick={() => setManual(null)}>收起</button>
            </div>
          )}
        </div>

        <Section label="重来一次" />
        <div className="card">
          <p className="sub" style={{ margin: 0, color: 'var(--ink-2)' }}>
            首次打开时装的是示例数据（客户 A、推荐位改版这些）。看懂了每块放什么之后，
            清空它，换成你自己的。
          </p>
          {confirmClear ? (
            <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s4)' }}>
              <button type="button" className="btn" style={{ flex: 1, background: 'var(--alert)' }}
                onClick={() => { resetToEmpty(); setConfirmClear(false); toast('清空了'); onClose() }}>
                确认清空，不可撤销
              </button>
              <button type="button" className="btn quiet" onClick={() => setConfirmClear(false)}>算了</button>
            </div>
          ) : (
            <button type="button" className="btn ghost wide" style={{ marginTop: 'var(--s4)', color: 'var(--alert)' }}
              onClick={() => setConfirmClear(true)}>
              清空全部数据
            </button>
          )}
        </div>

        <Section label="关于" />
        <div className="card">
          <p className="row-t" style={{ margin: 0 }}>案头 Deskside v1</p>
          <p className="sub" style={{ marginTop: 'var(--s1)', color: 'var(--ink-2)' }}>
            四条线：咨询顾问 · 字节产品 · 我们俩 · 我自己。<br />
            视觉沿用 Organic 设计系统，按手机重构。<br />
            设计与实现说明见仓库 <span className="mono">docs/prd/deskside-mobile-workbench.html</span>。
          </p>
        </div>

        <div style={{ height: 'var(--s7)' }} />
      </div>
    </div>
  )
}
