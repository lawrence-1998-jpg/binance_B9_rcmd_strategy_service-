import { useRef, useState } from 'react'
import { update, useStore, uid } from '../lib/store'
import { downscale, putPhoto, delPhoto, rotatePhoto } from '../lib/media'
import { usePhotoURL } from '../lib/usePhoto'
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
  const [busy, setBusy] = useState(false)

  const current = photos.find((p) => p.id === open) ?? null

  async function add(files: FileList | null) {
    if (!files || files.length === 0) return
    setBusy(true)
    let ok = 0
    for (const f of Array.from(files)) {
      try {
        const blob = await downscale(f)
        const id = uid()
        await putPhoto(id, blob)
        update((x) => ({
          ...x,
          photos: [{ id, caption: '', date: D.key(), createdAt: Date.now() }, ...x.photos],
        }))
        ok++
      } catch {
        /* 单张失败不该中断其余的 */
      }
    }
    setBusy(false)
    toast(ok ? `加了 ${ok} 张` : '这些图读不了')
  }

  return (
    <>
      <Section label="照片" domain="us" meta={photos.length ? `${photos.length} 张` : undefined} />
      <div className="pgrid">
        <button type="button" className="padd" onClick={() => file.current?.click()} disabled={busy}>
          <IcPlus />
          <span>{busy ? '处理中' : '加照片'}</span>
        </button>
        {photos.map((p) => (
          <Tile key={p.id} id={p.id} caption={p.caption} rev={p.rev ?? 0} onOpen={() => setOpen(p.id)} />
        ))}
      </div>
      <input
        ref={file} type="file" accept="image/*" multiple hidden
        onChange={(e) => { void add(e.target.files); e.target.value = '' }}
      />
      {photos.length === 0 && (
        <p className="sub" style={{ color: 'var(--ink-3)', marginTop: 'var(--s2)' }}>
          照片只存在这台设备上，不上传任何地方。存之前会自动压到 1600px，省空间。
        </p>
      )}

      {current && (
        <div className="sheet" role="dialog" aria-modal="true" aria-label="照片">
          <div className="sheet-in">
            <div className="sheet-head">
              <span className="eyebrow">{D.shortCN(current.date)}</span>
              <button type="button" className="icon-btn" onClick={() => setOpen(null)} aria-label="关闭"><IcClose /></button>
            </div>
            <Big id={current.id} caption={current.caption} rev={current.rev ?? 0} />
            <textarea
              className="field" rows={2} style={{ marginTop: 'var(--s4)' }}
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
                onClick={() => {
                  void delPhoto(current.id)
                  update((x) => ({ ...x, photos: x.photos.filter((y) => y.id !== current.id) }))
                  setOpen(null); toast('删掉了')
                }}
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
