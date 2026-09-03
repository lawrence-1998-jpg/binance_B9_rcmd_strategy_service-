import { useEffect, useRef, useState } from 'react'
import { resetToEmpty, useStore } from '../lib/store'
import { buildBackup, restoreBackup, backupName, humanBytes } from '../lib/backup'
import { pruneOrphans, usage } from '../lib/media'
import { isStandalone } from '../lib/install'
import { saveFile } from '../lib/save'
import { Section } from '../components/ui'
import { IcClose } from '../components/icons'

type Busy = { what: string; done: number; total: number } | null

export function Settings({ onClose, toast }: { onClose: () => void; toast: (t: string) => void }) {
  const s = useStore((x) => x)
  const [confirmClear, setConfirmClear] = useState(false)
  const [confirmImport, setConfirmImport] = useState<File | null>(null)
  const [manual, setManual] = useState<string | null>(null)
  const [busy, setBusy] = useState<Busy>(null)
  const [space, setSpace] = useState<{ used: number; quota: number } | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const standalone = isStandalone()

  useEffect(() => { void usage().then(setSpace) }, [])

  const counts = [
    ['事项', s.tasks.length],
    ['速记', s.notes.length],
    ['照片', s.photos.length],
    ['日子', s.anniversaries.length],
  ] as const

  async function download() {
    setBusy({ what: '正在打包照片', done: 0, total: s.photos.length })
    const r = await buildBackup((done, total) => setBusy({ what: '正在打包照片', done, total }))
    setBusy(null)
    const outcome = await saveFile(backupName(), r.json)
    const note = `${r.photos} 张照片 · ${humanBytes(r.bytes)}${r.failed ? ` · ${r.failed} 张读不出来` : ''}`
    if (outcome === 'saved') { setManual(null); toast(`导出好了（${note}）`); return }
    if (outcome === 'declined') { toast('取消了'); return }
    setManual(r.json)
    toast(`这个环境存不了文件（${note}）`)
  }

  async function doImport(f: File) {
    setConfirmImport(null)
    setBusy({ what: '正在还原照片', done: 0, total: 0 })
    const r = await restoreBackup(await f.text(), (done, total) => setBusy({ what: '正在还原照片', done, total }))
    setBusy(null)
    if (!r.ok) { toast(r.reason ?? '这个文件读不了'); return }
    toast(r.failed ? `导入好了，${r.photos} 张照片，${r.failed} 张失败` : `导入好了（${r.photos} 张照片）`)
  }

  async function clearAll() {
    // localStorage 和 IndexedDB 是两处存储，只清前者会留下一堆永远访问不到、
    // 也永远删不掉的照片字节，一直占着配额
    resetToEmpty()
    try { await pruneOrphans([]) } catch { /* 清不掉不该挡住这步 */ }
    setConfirmClear(false)
    toast('清空了')
    onClose()
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
          {space && space.quota > 0 && (
            <p className="row-s" style={{ marginTop: 'var(--s3)' }}>
              已用 {humanBytes(space.used)} / 可用 {humanBytes(space.quota)}
            </p>
          )}
          <p className="sub" style={{ marginTop: 'var(--s4)' }}>
            数据只存在这台设备上，不上传任何地方。换设备、清缓存都会没——
            所以每周导出一次。<strong>导出的文件包含照片本体</strong>，
            换手机时导入就能全部还回来。
          </p>
          {!standalone && (
            <p className="sub" style={{ marginTop: 'var(--s3)', color: 'var(--alert)' }}>
              你现在是在浏览器里打开的。iPhone 上浏览器和主屏 App 的数据是
              <strong>两份、互相看不见</strong>，而且浏览器里 7 天不打开会被系统清掉。
              长期用请从主屏幕图标进。
            </p>
          )}

          {busy && (
            <p className="row-s" style={{ marginTop: 'var(--s3)' }}>
              {busy.what} {busy.total ? `${busy.done} / ${busy.total}` : '…'}
            </p>
          )}

          <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s4)' }}>
            <button type="button" className="btn" style={{ flex: 1 }} disabled={!!busy} onClick={() => void download()}>
              导出备份
            </button>
            <button type="button" className="btn quiet" style={{ flex: 1 }} disabled={!!busy} onClick={() => file.current?.click()}>
              导入
            </button>
          </div>
          <input ref={file} type="file" accept="application/json" hidden
            onChange={(e) => { const f = e.target.files?.[0]; if (f) setConfirmImport(f); e.target.value = '' }} />

          {confirmImport && (
            <div className="warn" style={{ marginTop: 'var(--s4)' }}>
              <p className="row-t" style={{ margin: 0 }}>导入会覆盖现在的全部数据</p>
              <p className="sub" style={{ marginTop: 'var(--s1)' }}>
                当前有 {s.tasks.length} 条事项、{s.entries.length} 天日记、{s.photos.length} 张照片，
                导入后会被这个文件里的内容替换，<strong>不可撤销</strong>。
                建议先「导出备份」存一份再导入。
              </p>
              <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s3)' }}>
                <button type="button" className="btn danger" style={{ flex: 1 }} onClick={() => void doImport(confirmImport)}>
                  确认导入，覆盖现有数据
                </button>
                <button type="button" className="btn quiet" onClick={() => setConfirmImport(null)}>算了</button>
              </div>
            </div>
          )}

          {manual && (
            <div style={{ marginTop: 'var(--s4)' }}>
              <p className="sub" style={{ marginBottom: 'var(--s2)' }}>
                这个环境不允许网页直接存文件。下面是你的全部数据，<strong>长按全选复制</strong>，
                贴到备忘录或任何地方存着；要恢复时用旁边的「导入」。
              </p>
              <textarea
                className="field" rows={6} readOnly value={manual}
                onFocus={(e) => e.currentTarget.select()}
                style={{ fontFamily: 'var(--f-mono)', fontSize: 'var(--t-meta)', lineHeight: 1.5 }}
              />
              <button type="button" className="btn quiet small wide" style={{ marginTop: 'var(--s2)' }}
                onClick={() => setManual(null)}>收起</button>
            </div>
          )}
        </div>

        <Section label="重来一次" />
        <div className="card">
          <p className="sub" style={{ margin: 0 }}>
            首次打开时装的是示例数据（客户 A、推荐位改版这些）。看懂了每块放什么之后，
            清空它，换成你自己的。
          </p>
          {confirmClear ? (
            <div className="warn" style={{ marginTop: 'var(--s4)' }}>
              <p className="row-t" style={{ margin: 0 }}>会删掉全部内容，包括 {s.photos.length} 张照片</p>
              <p className="sub" style={{ marginTop: 'var(--s1)' }}>
                日记、纪念日、照片一起没，<strong>没有回收站，也撤销不了</strong>。
                想留就先「导出备份」。
              </p>
              <div style={{ display: 'flex', gap: 'var(--s2)', marginTop: 'var(--s3)' }}>
                <button type="button" className="btn danger" style={{ flex: 1 }} onClick={() => void clearAll()}>
                  确认清空
                </button>
                <button type="button" className="btn quiet" onClick={() => setConfirmClear(false)}>算了</button>
              </div>
            </div>
          ) : (
            <button type="button" className="btn ghost wide danger-text" style={{ marginTop: 'var(--s4)' }}
              onClick={() => setConfirmClear(true)}>
              清空全部数据
            </button>
          )}
        </div>

        <Section label="关于" />
        <div className="card">
          <p className="row-t" style={{ margin: 0 }}>案头 Deskside v1</p>
          <p className="sub" style={{ marginTop: 'var(--s1)' }}>
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
