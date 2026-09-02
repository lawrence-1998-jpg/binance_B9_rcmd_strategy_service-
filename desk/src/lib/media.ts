/**
 * 照片存储。
 *
 * 为什么不放 localStorage：它只有约 5MB，且只能存字符串，
 * 图片转 base64 还要再膨胀 33%。几张照片就撑爆了。
 * 所以图片本体走 IndexedDB（存 Blob，配额是几百 MB 量级），
 * localStorage 里只留 id 和文字说明。
 *
 * ⚠️ iOS Safari 会清掉「7 天没访问」的站点数据，但**添加到主屏幕的 PWA 不在此列**。
 * 这是「一定要添加到主屏幕」的实质理由，不只是为了好看。
 */

const DB_NAME = 'deskside-media'
const STORE = 'photos'
const VERSION = 1

let dbp: Promise<IDBDatabase> | null = null

function db(): Promise<IDBDatabase> {
  if (dbp) return dbp
  dbp = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, VERSION)
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE)
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
  return dbp
}

function tx<T>(mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return db().then(
    (d) =>
      new Promise<T>((resolve, reject) => {
        const t = d.transaction(STORE, mode)
        const req = run(t.objectStore(STORE))
        req.onsuccess = () => resolve(req.result)
        req.onerror = () => reject(req.error)
      }),
  )
}

export async function putPhoto(id: string, blob: Blob): Promise<void> {
  await tx('readwrite', (s) => s.put(blob, id) as IDBRequest<IDBValidKey>)
}

export async function getPhoto(id: string): Promise<Blob | null> {
  try {
    return (await tx<Blob | undefined>('readonly', (s) => s.get(id))) ?? null
  } catch {
    return null
  }
}

export async function delPhoto(id: string): Promise<void> {
  try {
    await tx('readwrite', (s) => s.delete(id) as unknown as IDBRequest<undefined>)
  } catch {
    /* 删不掉也不该让界面崩 */
  }
}

/** 存储用量，给设置页显示用 */
export async function usage(): Promise<{ used: number; quota: number } | null> {
  try {
    const e = await navigator.storage?.estimate?.()
    if (!e) return null
    return { used: e.usage ?? 0, quota: e.quota ?? 0 }
  } catch {
    return null
  }
}

/**
 * 存之前先缩。手机直出照片动辄 4MB，几十张就把配额吃光了。
 * 用 <img> 而不是 createImageBitmap：Safari 对 HEIC 的解码走系统编解码器，
 * <img> 这条路更稳。
 */
export function downscale(file: File, max = 1600, quality = 0.82): Promise<Blob> {
  return draw(file, max, quality)
}

/** 把已存的图再转 90°，用于「拍歪了」这种情况 */
export async function rotatePhoto(id: string, quarterTurns = 1): Promise<boolean> {
  const blob = await getPhoto(id)
  if (!blob) return false
  try {
    const out = await draw(blob, 4000, 0.85, quarterTurns)
    await putPhoto(id, out)
    return true
  } catch {
    return false
  }
}

/**
 * 解码 → 可选旋转 → 压缩。
 *
 * 关于 EXIF 方向：**故意不自己处理**。
 * 手机照片把「该转多少度」写在 EXIF 里，现代浏览器（iOS Safari 13.4+、Chrome 81+）
 * 在 <img> 上会自动摆正。我试过自己接管，结果发现解码器的行为无法可靠探测——
 * 实测同一个 Chromium 对合成的 orientation=6 测试图会摆正，对真实 iPhone 照片却不会。
 * 在这种情况下自作主张，只会在某些浏览器上把照片转两次，
 * 而那是**写进存储的永久错误**，比不转更糟。
 *
 * 所以：解码交给浏览器，转错了由用户点「转 90°」修一下。
 * 简单、可预测、最坏情况可恢复。
 */
async function draw(file: Blob, max: number, quality: number, extraTurns = 0): Promise<Blob> {
  const img = await loadImg(file)
  const w = img.naturalWidth
  const h = img.naturalHeight

  const turns = ((extraTurns % 4) + 4) % 4
  const swap = turns === 1 || turns === 3
  const outW = swap ? h : w
  const outH = swap ? w : h

  const scale = Math.min(1, max / Math.max(outW, outH))
  const cw = Math.round(outW * scale)
  const ch = Math.round(outH * scale)

  const canvas = document.createElement('canvas')
  canvas.width = cw
  canvas.height = ch
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('无法处理这张图')

  ctx.translate(cw / 2, ch / 2)
  ctx.rotate((turns * Math.PI) / 2)
  const dw = swap ? ch : cw
  const dh = swap ? cw : ch
  ctx.drawImage(img, -dw / 2, -dh / 2, dw, dh)

  return await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('无法处理这张图'))), 'image/jpeg', quality),
  )
}

function loadImg(file: Blob): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => { URL.revokeObjectURL(url); resolve(img) }
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('读不了这张图')) }
    img.src = url
  })
}
