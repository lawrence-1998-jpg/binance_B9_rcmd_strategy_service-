/**
 * 截图进来之后：压一份存进卡片 —— 看得清字，能复制出去贴给别的 AI，
 * 开了 Claude 也拿这一份去读（Claude 自己也会缩到 1568 像素以内，再大没用）。
 */

/** 存进卡片的那份，base64 之后不超过这么大（大约 450 KB） */
const KEEP_MAX = 600_000

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
 * 压成 JPEG data URL：宽不超过 1170（手机截图原宽）、高不超过 4000（长截图照样看得清字），
 * 质量从 0.8 往下试，直到小于 KEEP_MAX
 */
export async function shrink(b: Blob): Promise<string> {
  const src = await bitmap(b)
  const w0 = 'naturalWidth' in src ? src.naturalWidth : src.width
  const h0 = 'naturalHeight' in src ? src.naturalHeight : src.height
  let scale = Math.min(1, 1170 / w0, 4000 / h0)
  for (let round = 0; round < 4; round++) {
    const c = document.createElement('canvas')
    c.width = Math.max(1, Math.round(w0 * scale))
    c.height = Math.max(1, Math.round(h0 * scale))
    const g = c.getContext('2d')!
    g.fillStyle = '#fff'
    g.fillRect(0, 0, c.width, c.height)
    g.drawImage(src as CanvasImageSource, 0, 0, c.width, c.height)
    for (const q of [0.8, 0.7, 0.6, 0.5]) {
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

/**
 * 复制图片用：剪贴板只收 PNG。必须在点击里同步调用 copyImage，
 * 所以这里给的是一个 Promise<Blob>，由 ClipboardItem 自己等（Safari 只认这种写法）
 */
export async function toPng(url: string): Promise<Blob> {
  const src = await bitmap(dataUrlToBlob(url))
  const c = document.createElement('canvas')
  c.width = 'naturalWidth' in src ? src.naturalWidth : src.width
  c.height = 'naturalHeight' in src ? src.naturalHeight : src.height
  c.getContext('2d')!.drawImage(src as CanvasImageSource, 0, 0)
  return new Promise((ok, no) => c.toBlob((b) => (b ? ok(b) : no(new Error('转不成 PNG'))), 'image/png'))
}
