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
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      const scale = Math.min(1, max / Math.max(img.width, img.height))
      const w = Math.round(img.width * scale)
      const h = Math.round(img.height * scale)
      const canvas = document.createElement('canvas')
      canvas.width = w
      canvas.height = h
      const ctx = canvas.getContext('2d')
      if (!ctx) { reject(new Error('无法处理这张图')); return }
      ctx.drawImage(img, 0, 0, w, h)
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error('无法处理这张图'))),
        'image/jpeg',
        quality,
      )
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('读不了这张图'))
    }
    img.src = url
  })
}
