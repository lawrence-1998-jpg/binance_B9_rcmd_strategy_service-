/**
 * 读 JPEG 的拍摄时间。
 *
 * 只读日期，不碰方向——方向那件事各解码器行为不一致、自己处理会转错，
 * 已经放弃（见 media.ts 的注释）。日期没有这个歧义：文件里写的就是写的。
 *
 * 为什么值得读：不读的话所有照片都会被打上「今天」，
 * 一趟旅行的照片全挤在同一天，回忆卡和时间轴就没意义了。
 *
 * 注意：经过某些上传/转存管道的图片 EXIF 会被剥掉，这时返回 null。
 */
export async function readCaptureDate(file: Blob): Promise<string | null> {
  try {
    const buf = await file.slice(0, 256 * 1024).arrayBuffer()
    const v = new DataView(buf)
    if (v.getUint16(0) !== 0xffd8) return null

    let i = 2
    while (i < v.byteLength - 4) {
      if (v.getUint8(i) !== 0xff) { i++; continue }
      const marker = v.getUint8(i + 1)
      if (marker === 0xd8 || marker === 0xd9) { i += 2; continue }
      const len = v.getUint16(i + 2)
      if (marker === 0xe1 && v.getUint32(i + 4) === 0x45786966) {
        const tiff = i + 10
        const le = v.getUint16(tiff) === 0x4949
        const ifd0 = tiff + v.getUint32(tiff + 4, le)

        // 先找 ExifIFD 里的 DateTimeOriginal(0x9003)，退而求其次用 IFD0 的 DateTime(0x0132)
        const exifPtr = findTag(v, ifd0, tiff, le, 0x8769, 'long')
        if (typeof exifPtr === 'number') {
          const s = findTag(v, tiff + exifPtr, tiff, le, 0x9003, 'ascii')
          if (typeof s === 'string') return toKey(s)
        }
        const s0 = findTag(v, ifd0, tiff, le, 0x0132, 'ascii')
        if (typeof s0 === 'string') return toKey(s0)
        return null
      }
      i += 2 + len
    }
  } catch {
    /* 读不出来就返回 null，调用方自己兜底 */
  }
  return null
}

function findTag(
  v: DataView, ifd: number, tiff: number, le: boolean, want: number, kind: 'long' | 'ascii',
): number | string | null {
  try {
    const n = v.getUint16(ifd, le)
    for (let k = 0; k < n; k++) {
      const e = ifd + 2 + k * 12
      if (v.getUint16(e, le) !== want) continue
      if (kind === 'long') return v.getUint32(e + 8, le)
      const count = v.getUint32(e + 4, le)
      const at = count > 4 ? tiff + v.getUint32(e + 8, le) : e + 8
      let s = ''
      for (let j = 0; j < count - 1; j++) s += String.fromCharCode(v.getUint8(at + j))
      return s
    }
  } catch {
    /* 越界等等，当作没找到 */
  }
  return null
}

/** "2026:08:30 19:12:04" → "2026-08-30" */
function toKey(s: string): string | null {
  const m = s.match(/^(\d{4}):(\d{2}):(\d{2})/)
  if (!m) return null
  const y = Number(m[1])
  if (y < 1990 || y > 2100) return null
  return `${m[1]}-${m[2]}-${m[3]}`
}

/**
 * 拿不到 EXIF 时的兜底：文件修改时间。
 * 但 iOS 相册选图经常把它设成「刚刚」，所以只在明显是过去时才采信。
 */
export function fallbackDate(file: File): string | null {
  const t = file.lastModified
  if (!t) return null
  const twoDays = 2 * 86400000
  if (Date.now() - t < twoDays) return null
  const d = new Date(t)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
