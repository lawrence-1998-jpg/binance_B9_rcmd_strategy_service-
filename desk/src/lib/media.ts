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
  dbp = new Promise<IDBDatabase>((resolve, reject) => {
    let req: IDBOpenDBRequest
    try {
      req = indexedDB.open(DB_NAME, VERSION)
    } catch (e) {
      reject(e); return
    }
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE)
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error ?? new Error('打不开照片库'))
    // 另一个标签页占着旧版本时 open 会一直挂着。不给期限的话调用方永远等下去
    req.onblocked = () => reject(new Error('照片库被另一个标签页占用'))
  })
  // 失败不能被永久缓存：隐私模式或一次偶发错误之后，下次还得能再试
  dbp.catch(() => { dbp = null })
  return dbp
}

function tx<T>(mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return db().then(
    (d) =>
      new Promise<T>((resolve, reject) => {
        let t: IDBTransaction
        try {
          t = d.transaction(STORE, mode)
        } catch (e) {
          reject(e); return
        }
        // 事务层的 abort 必须单独接：配额写满时浏览器 abort 整个事务，
        // 而不是给某个 request 发 error。只听 request 的话这个 Promise 永远不 settle，
        // 调用方就会卡在 await 上——界面看起来像死了。
        t.onabort = () => reject(t.error ?? new Error('照片存不下了'))
        t.onerror = () => reject(t.error ?? new Error('照片库出错'))
        const req = run(t.objectStore(STORE))
        req.onsuccess = () => resolve(req.result)
        req.onerror = () => reject(req.error ?? new Error('照片库出错'))
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

/** 库里所有照片的 id —— 用来找孤儿（blob 还在但元数据没了） */
export async function allPhotoIds(): Promise<string[]> {
  try {
    const keys = await tx<IDBValidKey[]>('readonly', (s) => s.getAllKeys())
    return keys.map(String)
  } catch {
    return []
  }
}

/**
 * 清掉元数据里已经没有的 blob。
 *
 * 会出现孤儿是因为两处存储无法原子地一起写：blob 落进 IndexedDB 之后
 * 才写 localStorage，中间失败（或「清空全部数据」只清了 localStorage）
 * 就会留下永远访问不到、也永远删不掉的字节，一直占着配额。
 */
export async function pruneOrphans(keep: string[]): Promise<number> {
  const live = new Set(keep)
  const all = await allPhotoIds()
  let n = 0
  for (const id of all) {
    if (!live.has(id)) { await delPhoto(id); n++ }
  }
  return n
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
    // 质量给到 0.92：转一次就重编码一次，按 0.85 连转四圈回到原位时
    // 已经肉眼可见地糊了。这里宁可多占点空间
    const out = await draw(blob, 1600, 0.92, quarterTurns)
    await putPhoto(id, out)
    return true
  } catch {
    return false
  }
}

/** Blob → data URL，导出备份时把照片一起带走 */
export function blobToDataURL(b: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result))
    r.onerror = () => reject(r.error ?? new Error('读不了这张图'))
    r.readAsDataURL(b)
  })
}

/** data URL → Blob，导入备份时还原照片 */
export async function dataURLToBlob(u: string): Promise<Blob> {
  const res = await fetch(u)
  return await res.blob()
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
  if (!w || !h) throw new Error('读不了这张图')

  const turns = ((extraTurns % 4) + 4) % 4
  const swap = turns === 1 || turns === 3
  const outW = swap ? h : w
  const outH = swap ? w : h

  const scale = Math.min(1, max / Math.max(outW, outH))
  const cw = Math.max(1, Math.round(outW * scale))
  const ch = Math.max(1, Math.round(outH * scale))

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

  try {
    return await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('无法处理这张图'))), 'image/jpeg', quality),
    )
  } finally {
    // iOS 对 canvas 占用的总内存有硬上限，连着导入十几张不主动释放就会开始返回空白。
    // 置零是公认的让 WebKit 立刻回收的写法
    canvas.width = 0
    canvas.height = 0
  }
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
