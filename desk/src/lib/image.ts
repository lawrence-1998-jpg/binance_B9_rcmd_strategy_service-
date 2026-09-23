/**
 * 截图进来之后的两件事：
 *   - 压一份小的存进卡片（数据库一条最多 256 KiB，base64 还要再胖三分之一），
 *     够看清字，也够「重新整理」时再给 Claude 读一次；
 *   - 原图直接交给 Claude（平台会自己缩到 1.2 百万像素左右）。
 */

/** 存进卡片的那份，base64 之后不超过这么大 */
const KEEP_MAX = 150_000

export function isImage(f: File | Blob | null | undefined): f is Blob {
  return !!f && /^image\/(png|jpe?g|webp|gif|heic|heif)$/i.test(f.type)
}

async function bitmap(b: Blob): Promise<ImageBitmap | HTMLImageElement> {
  if ('createImageBitmap' in window) {
    try { return await createImageBitmap(b) } catch { /* 走下面的老路 */ }
  }
  return new Promise((ok, no) => {
    const url = URL.createObjectURL(b)
    const im = new Image()
    im.onload = () => { URL.revokeObjectURL(url); ok(im) }
    im.onerror = () => { URL.revokeObjectURL(url); no(new Error('读不了这张图')) }
    im.src = url
  })
}

/**
 * 压成 JPEG data URL：宽不超过 760、高不超过 2400（长截图照样看得清字），
 * 质量从 0.72 往下试，直到小于 KEEP_MAX
 */
export async function shrink(b: Blob): Promise<string> {
  const src = await bitmap(b)
  const w0 = 'naturalWidth' in src ? src.naturalWidth : src.width
  const h0 = 'naturalHeight' in src ? src.naturalHeight : src.height
  let scale = Math.min(1, 760 / w0, 2400 / h0)
  for (let round = 0; round < 4; round++) {
    const c = document.createElement('canvas')
    c.width = Math.max(1, Math.round(w0 * scale))
    c.height = Math.max(1, Math.round(h0 * scale))
    const g = c.getContext('2d')!
    g.fillStyle = '#fff'
    g.fillRect(0, 0, c.width, c.height)
    g.drawImage(src as CanvasImageSource, 0, 0, c.width, c.height)
    for (const q of [0.72, 0.6, 0.5, 0.4]) {
      const url = c.toDataURL('image/jpeg', q)
      if (url.length <= KEEP_MAX) return url
    }
    scale *= 0.75
  }
  throw new Error('图太大，压不下来')
}

export function dataUrlToBlob(url: string): Blob {
  const [head, body] = url.split(',')
  const type = head.match(/data:([^;]+)/)?.[1] ?? 'image/jpeg'
  const bin = atob(body)
  const arr = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i)
  return new Blob([arr], { type })
}
