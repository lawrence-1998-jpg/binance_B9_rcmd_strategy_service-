// 这个仓库是**公开**的，而「我们俩」那部分和照片绝不能离开这台设备。
// 「没有后端」是口头承诺，这条把它变成能失败的检查：
// 走一遍全 App（含写下我们俩的内容、存一张照片），
// 记录每一个网络请求，只要有一个不是自家域名就红。
import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const ORIGIN = new globalThis.URL(process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html').origin
const today = new Date().toISOString().slice(0,10)
let fail = 0
const t = (n, ok, note='') => { console.log(`${ok?'✓':'✗'} ${n}${note?' — '+note:''}`); if(!ok) fail++ }

const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
const seen = new Set()
// 连 SW 发出去的也算：不放过任何一条
// 注意：这个文件里的 URL 是个字符串常量，把全局的 URL 类遮住了。
// 第一版写 new URL(u) 全落进 catch，于是同源请求也被当成「出网」报红 ——
// 一个自己造出来的假阳性。用 globalThis.URL 把真的那个拿回来。
const parse = globalThis.URL
ctx.on('request', (r) => {
  const u = r.url()
  if (u.startsWith('data:') || u.startsWith('blob:')) return
  try { seen.add(new parse(u).origin) } catch { seen.add('解析不了:' + u.slice(0, 60)) }
})
const pg = await ctx.newPage()
await pg.goto(URL, { waitUntil: 'load' })
await pg.evaluate((s)=>localStorage.setItem('deskside.v1',JSON.stringify(s)), makeState(today))

// 把最私人的那部分真的走一遍
for (const h of ['#/today','#/work','#/life','#/review']) {
  await pg.goto(URL+h, { waitUntil:'load' }); await pg.reload(); await pg.waitForTimeout(500)
}
await pg.goto(URL+'#/life'); await pg.reload(); await pg.waitForTimeout(600)
// 写一句「想对他说」—— 全 App 最私人的写入路径，必须真的走到。
// 展开的是个内联输入框（不是 sheet），而这一屏本来就有好几个 input，
// 所以认 autofocus 那个，别按位置猜
const SECRET = '只该留在这台手机上的一句话'
const say = pg.locator('button').filter({ hasText: '写一句' })
t('找得到「写一句」', await say.count() > 0)
await say.first().click(); await pg.waitForTimeout(400)
await pg.evaluate((v) => {
  const el = document.activeElement
  if (!el || !('value' in el)) return false
  const setter = Object.getOwnPropertyDescriptor(
    el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value').set
  setter.call(el, v)
  el.dispatchEvent(new Event('input', { bubbles: true }))
  return true
}, SECRET)
await pg.waitForTimeout(200)
await pg.locator('button').filter({ hasText: /^存$/ }).first().click()
await pg.waitForTimeout(600)
t('那句话真的写进去了（这条路径确实被走到了）',
  await pg.evaluate((v) => (localStorage.getItem('deskside.v1')||'').includes(v), SECRET))
// 存一张照片进 IndexedDB（模拟她从手机加的那张）
const stored = await pg.evaluate(async () => {
  const c = document.createElement('canvas'); c.width=c.height=64
  const x = c.getContext('2d'); x.fillStyle='#c67139'; x.fillRect(0,0,64,64)
  const blob = await new Promise(r => c.toBlob(r,'image/jpeg',0.9))
  const db = await new Promise((res,rej)=>{ const q=indexedDB.open('deskside-media',1)
    q.onupgradeneeded=()=>{ if(!q.result.objectStoreNames.contains('photos')) q.result.createObjectStore('photos') }
    q.onsuccess=()=>res(q.result); q.onerror=()=>rej(q.error) })
  await new Promise((res,rej)=>{ const tr=db.transaction('photos','readwrite')
    const r=tr.objectStore('photos').put(blob,'pp1'); r.onsuccess=()=>res(); r.onerror=()=>rej() })
  const s = JSON.parse(localStorage.getItem('deskside.v1'))
  s.photos=[{id:'pp1',caption:'私人照片',date:'2026-09-01',createdAt:Date.now()}]
  localStorage.setItem('deskside.v1',JSON.stringify(s))
  return true
})
await pg.goto(URL+'#/life'); await pg.reload(); await pg.waitForTimeout(900)
t('照片渲染出来了（确实在用它）', stored && await pg.locator('.pview, img').count() > 0)

const outside = [...seen].filter(o => o !== ORIGIN)
t('全程没有任何一个请求出过自家域名', outside.length === 0, outside.join(' | ') || `只访问了 ${ORIGIN}`)

// 照片本体不许进 localStorage —— 那份是要被「导出备份」以外的路径读到的
const inLS = await pg.evaluate(() => {
  const raw = localStorage.getItem('deskside.v1') || ''
  return { hasDataURL: /data:image/.test(raw), kb: Math.round(raw.length/1024) }
})
t('照片本体不在 localStorage 里（只有 IndexedDB 有）', !inLS.hasDataURL, `deskside.v1 共 ${inLS.kb}KB`)

t('那句话只在本地，没被任何请求带出去', outside.length === 0)
await b.close()
process.exit(fail ? 1 : 0)
