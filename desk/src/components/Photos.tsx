import { useRef, useState } from 'react'
import { update, useStore, uid } from '../lib/store'
import { downscale, putPhoto, delPhoto, rotatePhoto } from '../lib/media'
import { readCaptureDate, fallbackDate } from '../lib/exifdate'
import { usePhotoURL } from '../lib/usePhoto'
import { askConfirm } from '../lib/confirm'
import * as D from '../lib/date'
import { Section } from './ui'
import { IcPlus, IcClose, IcTrash, IcRotate } from './icons'

function Tile({ id, caption, rev, onOpen }: { id: string; caption: string; rev: number; onOpen: () => void }) {
  const url = usePhotoURL(id, rev)
  return (
    <button type="button" className="ptile" onClick={onOpen} aria-label={caption || '照片'}>
      {url && <img src={url} alt={caption || ''} />}
      {caption && <span className="ptile-note">{caption}</span>}
    </button>
  )
}

export function Photos({ toast }: { toast: (t: string) => void }) {
  const photos = useStore((x) => x.photos)
  const file = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [prog, setProg] = useState<{ done: number; total: number } | null>(null)

  const current = photos.find((p) => p.id === open) ?? null

  // 按拍摄日期分组，一趟旅行才读得出是一趟旅行
  const groups = (() => {
    const m = new Map<string, typeof photos>()
    for (const p of photos) m.set(p.date, [...(m.get(p.date) ?? []), p])
    return [...m.entries()]
      .sort((a, b) => b[0].localeCompare(a[0]))
      .map(([date, items]) => ({ date, items }))
  })()

  async function add(files: FileList | null) {
    if (!files || files.length === 0) return
    const list = Array.from(files)
    // 一张 5MB 的照片解码 + 压缩要两秒多，十张就是二十几秒。
    // 只显示「处理中」的话，人不知道走到哪、也不知道有没有漏，所以报进度。
    setProg({ done: 0, total: list.length })
    let ok = 0
    const failed: string[] = []
    for (const f of list) {
      try {
        // 先拿拍摄日期：不这么做的话整趟旅行的照片都会被打上「今天」
        const date = (await readCaptureDate(f)) ?? fallbackDate(f) ?? D.key()
        const blob = await downscale(f)
        const id = uid()
        await putPhoto(id, blob)
        update((x) => ({
          ...x,
          photos: [{ id, caption: '', date, createdAt: Date.now() }, ...x.photos],
        }))
        ok++
      } catch {
        failed.push(f.name)  // 单张失败不中断其余的，但要说出来是哪张
      }
      setProg((s) => (s ? { ...s, done: s.done + 1 } : s))
    }
    setProg(null)
    if (ok && failed.length) toast(`加了 ${ok} 张，${failed.length} 张读不了`)
    else if (ok) toast(`加了 ${ok} 张`)
    else toast('这些图读不了')
  }

  return (
    <>
      <Section label="照片" domain="us" meta={photos.length ? `${photos.length} 张` : undefined} />
      <div className="pgrid">
        <button type="button" className="padd" onClick={() => file.current?.click()} disabled={!!prog}>
          <IcPlus />
          <span>{prog ? `${prog.done} / ${prog.total}` : '加照片'}</span>
        </button>
        {groups.length > 0 && groups[0].items.map((p) => (
          <Tile key={p.id} id={p.id} caption={p.caption} rev={p.rev ?? 0} onOpen={() => setOpen(p.id)} />
        ))}
      </div>
      {groups.slice(1).map((g) => (
        <div key={g.date}>
          <p className="row-s" style={{ margin: 'var(--s4) 0 var(--s2)' }}>{D.archiveCN(g.date)} · {g.items.length} 张</p>
          <div className="pgrid">
            {g.items.map((p) => (
              <Tile key={p.id} id={p.id} caption={p.caption} rev={p.rev ?? 0} onOpen={() => setOpen(p.id)} />
            ))}
          </div>
        </div>
      ))}
      <input
        ref={file} type="file" accept="image/*" multiple hidden
        onChange={(e) => { void add(e.target.files); e.target.value = '' }}
      />
      {photos.length === 0 && (
        <p className="sub quiet" style={{ marginTop: 'var(--s2)' }}>
          照片只存在这台设备上，不上传任何地方。存之前会自动压到 1600px，省空间。
        </p>
      )}

      {current && (
        <div className="sheet" role="dialog" aria-modal="true" aria-label="照片">
          <div className="sheet-in">
            <div className="sheet-head">
              <span className="eyebrow">{D.archiveCN(current.date)}</span>
              <button type="button" className="icon-btn" onClick={() => setOpen(null)} aria-label="关闭"><IcClose /></button>
            </div>
            <Big id={current.id} caption={current.caption} rev={current.rev ?? 0} />
            <input
              type="date" className="field" style={{ marginTop: 'var(--s4)' }}
              value={current.date} aria-label="拍摄日期"
              onChange={(e) => {
                // 清空日期框会给出空串。照片必须有日期，否则会掉进一个没名字的
                // 分组里，时间轴上也排不进去 —— 清空时保持原值，不接受空。
                const v = e.target.value
                if (!v) return
                update((x) => ({
                  ...x, photos: x.photos.map((y) => (y.id === current.id ? { ...y, date: v } : y)),
                }))
              }}
            />
            <textarea
              className="field" rows={2} style={{ marginTop: 'var(--s2)' }}
              value={current.caption}
              placeholder="这天发生了什么？想说什么？"
              onChange={(e) => update((x) => ({
                ...x, photos: x.photos.map((y) => (y.id === current.id ? { ...y, caption: e.target.value } : y)),
              }))}
            />
            <div className="sheet-foot">
              <button
                type="button" className="btn quiet wide"
                onClick={() => {
                  void rotatePhoto(current.id, 1).then((ok) => {
                    if (!ok) { toast('转不动这张'); return }
                    update((x) => ({
                      ...x, photos: x.photos.map((y) => (y.id === current.id ? { ...y, rev: (y.rev ?? 0) + 1 } : y)),
                    }))
                  })
                }}
              ><IcRotate /> 转 90°</button>
              <button
                type="button" className="btn ghost wide" style={{ marginTop: 'var(--s2)', color: 'var(--alert)' }}
                onClick={() => askConfirm({
                  title: '删掉这张照片？',
                  detail: '原图不在这里，删了就真的没了。想留着先去设置里导出备份。',
                  onYes: () => {
                    void delPhoto(current.id)
                    update((x) => ({ ...x, photos: x.photos.filter((y) => y.id !== current.id) }))
                    setOpen(null); toast('删掉了')
                  },
                })}
              >
                <IcTrash /> 删掉这张
              </button>
            </div>
            <div style={{ height: 'var(--s6)' }} />
          </div>
        </div>
      )}
    </>
  )
}

function Big({ id, caption, rev }: { id: string; caption: string; rev: number }) {
  const url = usePhotoURL(id, rev)
  if (!url) return <div className="pview" style={{ aspectRatio: '4/3' }} />
  return <img className="pview" src={url} alt={caption || '照片'} />
}
