import { get, importState, looksLikeBackup, type Backup } from './store'
import { getPhoto, putPhoto, blobToDataURL, dataURLToBlob, pruneOrphans } from './media'
import * as D from './date'

/**
 * 备份。
 *
 * 关键点：**照片必须一起带走**。
 * 之前的导出是 `JSON.stringify(state)`，而 state 里只有照片的 id 和说明，
 * 二进制在 IndexedDB 里，完全没被导出。设置页却写着「换设备、清缓存都会没，
 * 所以每周导出一次」——用户照做，换台手机一恢复，照片全没了，
 * 元数据还在，满屏破图。给了虚假的安全感，比不给备份更糟。
 *
 * 代价是文件会变大（每张压缩后约 200–400KB，base64 再涨 33%）。
 * 这个代价必须付：照片是这份数据里唯一真正不可再生的东西。
 */

export interface ExportResult {
  json: string
  photos: number
  failed: number
  bytes: number
}

export async function buildBackup(onProgress?: (done: number, total: number) => void): Promise<ExportResult> {
  const s = get()
  const photoData: Record<string, string> = {}
  let failed = 0
  const total = s.photos.length
  for (let i = 0; i < total; i++) {
    const p = s.photos[i]
    try {
      const b = await getPhoto(p.id)
      if (b) photoData[p.id] = await blobToDataURL(b)
      else failed++
    } catch {
      failed++
    }
    onProgress?.(i + 1, total)
  }
  const backup: Backup = { ...s, exportedAt: new Date().toISOString(), photoData }
  const json = JSON.stringify(backup)
  return { json, photos: Object.keys(photoData).length, failed, bytes: json.length }
}

export interface ImportResult {
  ok: boolean
  reason?: string
  photos: number
  failed: number
}

export async function restoreBackup(text: string, onProgress?: (done: number, total: number) => void): Promise<ImportResult> {
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    return { ok: false, reason: '这不是一个 JSON 文件', photos: 0, failed: 0 }
  }
  if (!looksLikeBackup(parsed)) {
    return { ok: false, reason: '这个文件不像案头导出的备份', photos: 0, failed: 0 }
  }
  const b = parsed as Backup
  const data = b.photoData && typeof b.photoData === 'object' ? b.photoData : {}
  const ids = Object.keys(data)
  let ok = 0
  let failed = 0
  for (let i = 0; i < ids.length; i++) {
    try {
      await putPhoto(ids[i], await dataURLToBlob(data[ids[i]]))
      ok++
    } catch {
      failed++
    }
    onProgress?.(i + 1, ids.length)
  }
  // photoData 不进 state：它只是运输壳子，留着会把 localStorage 直接撑爆
  const { photoData: _drop, exportedAt: _drop2, ...rest } = b
  void _drop; void _drop2
  importState(rest)
  // 导入的那批照片替换掉旧的一批，旧 blob 就成了孤儿
  try { await pruneOrphans(rest.photos?.map((p) => p.id) ?? []) } catch { /* 清不掉不影响导入 */ }
  return { ok: true, photos: ok, failed }
}

export function backupName(): string {
  return `deskside-${D.key()}.json`
}

export function humanBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
