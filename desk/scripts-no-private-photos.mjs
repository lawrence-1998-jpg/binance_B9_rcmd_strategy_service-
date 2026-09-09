/**
 * 这个仓库是**公开**的。
 *
 * 案头的照片按设计只存在她自己的手机里（IndexedDB），一张都不进 git ——
 * private.mjs 在运行时守着「不出网」，这一条守的是另一半：**别提交进来**。
 * 公开仓库里的东西删了也还在历史里，所以这必须是提交前就拦住的检查，
 * 不是事后发现。
 *
 * 判据是相机 EXIF：手机拍的照片带 Make/Model，截图和图标不带。
 * 宁可漏判也不误判 —— 这条一旦老是误报就会被无视，那就等于没有。
 */
import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'

// 所有图片格式都扫。
// 第一版只认 jpg/heic —— 而仓库里一张都没有，于是它扫了 0 个文件、
// 报了个绿。一条永远不会红的检查等于没有检查。
// 手机照片转成 png / webp 之后 EXIF 常常还在，所以按容器分别找。
const IMG = /\.(jpe?g|heic|heif|tiff?|png|webp|avif)$/i
// -z / NUL 分隔：`git ls-files` 默认会把非 ASCII 文件名转义成
// "desk/public/\346\210\221..." 这种带引号的八进制串，照着它去读文件必然失败。
// 而她真要漏一张，文件名多半就叫「我和他.jpg」—— 正好是会被转义的那种。
const files = execSync('git ls-files -z', { encoding: 'utf8' })
  .split('\0').filter((f) => f && IMG.test(f))

/** 从 JPEG/TIFF 里把 EXIF 的 Make / Model 抠出来。够用就行，不引依赖 */
function camera (buf) {
  // JPEG / WebP：APP1 段里的 "Exif\0\0"，后面直接跟 TIFF 头
  let tiff = -1
  const at = buf.indexOf(Buffer.from('Exif\0\0', 'binary'))
  if (at >= 0) tiff = at + 6
  else {
    // PNG：eXIf 块，块内容就是 TIFF，没有 "Exif\0\0" 前缀
    const c = buf.indexOf(Buffer.from('eXIf', 'ascii'))
    if (c >= 0) tiff = c + 4
  }
  if (tiff < 0) return null
  if (tiff + 8 > buf.length) return null
  const le = buf.toString('ascii', tiff, tiff + 2) === 'II'
  const u16 = (o) => (le ? buf.readUInt16LE(o) : buf.readUInt16BE(o))
  const u32 = (o) => (le ? buf.readUInt32LE(o) : buf.readUInt32BE(o))
  let ifd = tiff + u32(tiff + 4)
  if (ifd + 2 > buf.length) return null
  const n = u16(ifd); ifd += 2
  const out = {}
  for (let i = 0; i < n; i++) {
    const e = ifd + i * 12
    if (e + 12 > buf.length) break
    const tag = u16(e)
    if (tag !== 0x010f && tag !== 0x0110) continue    // Make / Model
    const count = u32(e + 4)
    let off = count > 4 ? tiff + u32(e + 8) : e + 8
    if (off + count > buf.length) continue
    const v = buf.toString('ascii', off, off + count).replace(/\0+$/, '').trim()
    if (v) out[tag === 0x010f ? 'make' : 'model'] = v
  }
  return out.make || out.model ? out : null
}

const hits = []
const unreadable = []
for (const f of files) {
  try {
    const c = camera(readFileSync(f))
    if (c) hits.push(`${f} —— 相机 EXIF：${[c.make, c.model].filter(Boolean).join(' ')}`)
  } catch (e) {
    // 读不了的必须说出来。
    // 原来这里是个空 catch —— 于是文件名一被转义，读失败被悄悄吞掉，
    // 一张真照片就那么过去了，检查还报绿。看不见的跳过就是假绿。
    unreadable.push(`${f} —— ${e.message}`)
  }
}

if (unreadable.length) {
  console.error('❌ 有文件读不了，没法判断它是不是私人照片：')
  for (const u of unreadable) console.error('   ' + u)
  process.exit(1)
}

if (hits.length) {
  console.error('❌ 公开仓库里出现了带相机 EXIF 的照片 —— 照片只该留在她手机上：')
  for (const h of hits) console.error('   ' + h)
  console.error('\n   公开仓库删了也还在历史里。先别提交，把文件拿出去。')
  process.exit(1)
}
console.log(`✓ 扫了 ${files.length} 个可能带 EXIF 的文件，没有相机照片`)
