import pkg from 'playwright'
const { chromium } = pkg
const URL=process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const b=await chromium.launch()
const ctx=await b.newContext({viewport:{width:430,height:932}})
const pg=await ctx.newPage()

// 1) 图标真实 alpha
await pg.goto(URL)
const icons = await pg.evaluate(async () => {
  const out = {}
  for (const f of ['icons/apple-touch-icon.png','icons/icon-192.png','icons/icon-512.png']) {
    const img = new Image(); img.src = './' + f
    await new Promise(r => { img.onload = r; img.onerror = r })
    const c = document.createElement('canvas'); c.width = img.width; c.height = img.height
    const x = c.getContext('2d'); x.drawImage(img,0,0)
    const d = x.getImageData(0,0,c.width,c.height).data
    let minA = 255, transparent = 0
    for (let i=3;i<d.length;i+=4){ if(d[i]<minA) minA=d[i]; if(d[i]<250) transparent++ }
    out[f] = { size: `${img.width}×${img.height}`, minAlpha: minA, transparentPx: transparent, total: d.length/4 }
  }
  return out
})
console.log('== 图标实际透明度 ==')
for (const [k,v] of Object.entries(icons)) console.log(` ${k}: ${v.size} 最小alpha=${v.minAlpha} 半透明像素=${v.transparentPx}/${v.total}`)

// 2) 字体：外链能否加载 / 离线时会怎样
const fontReqs = []
pg.on('request', r => { if (/fonts\.(googleapis|gstatic)/.test(r.url())) fontReqs.push(r.url().slice(0,60)) })
await pg.goto(URL); await pg.waitForTimeout(1200)
const fonts = await pg.evaluate(() => {
  const el = document.querySelector('.h1') || document.body
  const big = document.querySelector('.big')
  return {
    h1Font: getComputedStyle(el).fontFamily,
    bigFont: big ? getComputedStyle(big).fontFamily : null,
    loaded: [...document.fonts].map(f => `${f.family} ${f.status}`),
    ready: document.fonts.status,
  }
})
console.log('\n== 字体 ==')
console.log(' 外链请求数:', fontReqs.length, fontReqs.slice(0,2))
console.log(' document.fonts:', fonts.loaded.length ? fonts.loaded : '（空 —— 外链样式表没加载成功）')
console.log(' .h1 实际字体栈:', fonts.h1Font)
console.log(' .big 实际字体栈:', fonts.bigFont)

// 3) 离线
await pg.goto(URL); await pg.waitForTimeout(1500)   // 让 sw 装上
const swOK = await pg.evaluate(async () => {
  const r = await navigator.serviceWorker.getRegistration()
  return r ? (r.active ? 'active' : r.installing ? 'installing' : 'waiting') : 'none'
})
console.log('\n== Service Worker ==', swOK)
await ctx.setOffline(true)
let offlineOK = 'unknown', offlineErr = null
try {
  await pg.reload({ waitUntil: 'load', timeout: 8000 })
  offlineOK = await pg.evaluate(() => {
    const h = document.querySelector('.h1')
    const tabs = document.querySelectorAll('.tab').length
    return h ? `渲染成功 h1="${h.textContent}" tabs=${tabs}` : '白屏'
  })
} catch(e) { offlineErr = String(e.message).split('\n')[0].slice(0,80) }
console.log(' 断网后 reload:', offlineOK, offlineErr||'')
await ctx.setOffline(false)

// 4) 键盘遮挡（缩小视口高度模拟）
await pg.goto(URL + '#/review'); await pg.reload(); await pg.waitForTimeout(500)
const kb = await pg.evaluate(() => {
  const ta = document.querySelector('textarea')
  if (!ta) return 'no textarea'
  ta.focus()
  const r = ta.getBoundingClientRect()
  const bar = document.querySelector('.tabbar')?.getBoundingClientRect()
  return { taBottom: Math.round(r.bottom), vh: window.innerHeight, tabbarTop: bar?Math.round(bar.top):null }
})
console.log('\n== 输入框与 tabbar ==', JSON.stringify(kb))

// 5) sheet 打开时背景能否滚动 / 手势返回
await pg.goto(URL + '#/today'); await pg.reload(); await pg.waitForTimeout(400)
await pg.locator('.cap').click(); await pg.waitForTimeout(300)
const sheetState = await pg.evaluate(() => ({
  sheetOpen: !!document.querySelector('.sheet'),
  bodyOverflow: getComputedStyle(document.body).overflow,
  sheetOverscroll: document.querySelector('.sheet') ? getComputedStyle(document.querySelector('.sheet')).overscrollBehavior : null,
  historyLen: history.length,
  hash: location.hash,
}))
console.log('\n== sheet 打开时 ==', JSON.stringify(sheetState))
await pg.goBack().catch(()=>{})
await pg.waitForTimeout(400)
const afterBack = await pg.evaluate(() => ({ sheetOpen: !!document.querySelector('.sheet'), hash: location.hash, url: location.href.slice(-30) }))
console.log(' 手势返回后:', JSON.stringify(afterBack))

await b.close()
