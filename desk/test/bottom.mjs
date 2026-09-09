// 底栏是 fixed 的，永远浮在屏幕最下面。
// 所以每一屏滚到底之后，最后一个能点的东西必须还在底栏**上面** ——
// 不然那个按钮就永远点不到，而且这种事整页截图看不出来
// （fixed 元素在整页截图里会假性压住内容，我这次已经被骗过一次）。
import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const APP = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const today = new Date().toISOString().slice(0,10)
let fail = 0
const t = (n, ok, note='') => { console.log(`${ok?'✓':'✗'} ${n}${note?' — '+note:''}`); if(!ok) fail++ }

const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
const pg = await ctx.newPage()
await pg.goto(APP)
await pg.evaluate((s)=>localStorage.setItem('deskside.v1',JSON.stringify(s)), makeState(today))

for (const [name, hash] of [['今日','#/today'],['工作','#/work'],['生活','#/life'],['复盘','#/review']]) {
  await pg.goto(APP+hash); await pg.reload(); await pg.waitForTimeout(600)
  // 滚到底
  await pg.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
  await pg.waitForTimeout(500)
  const r = await pg.evaluate(() => {
    const bar = document.querySelector('.tabbar')
    const barTop = bar ? bar.getBoundingClientRect().top : window.innerHeight
    // 屏幕内可见的、能点的东西里，最靠下的那个（底栏自己和它的孩子不算）
    let worst = null
    document.querySelectorAll('button,a[href],input,textarea,label.check').forEach(el => {
      if (bar && bar.contains(el)) return
      if (el.classList.contains('sr') || el.classList.contains('cap')) return
      const q = el.getBoundingClientRect()
      if (q.width < 1 || q.height < 1) return
      if (q.top > window.innerHeight || q.bottom < 0) return   // 不在屏内
      if (!worst || q.bottom > worst.bottom) {
        worst = { bottom: q.bottom, label: (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\s+/g,' ').slice(0,22) }
      }
    })
    return { barTop: Math.round(barTop), worst: worst && { ...worst, bottom: Math.round(worst.bottom) }, vh: window.innerHeight }
  })
  if (!r.worst) { t(`${name}：滚到底还能看到可点的东西`, false, '一个都没找到'); continue }
  const gap = r.barTop - r.worst.bottom
  t(`${name}：滚到底，最后一个能点的没被底栏盖住`, gap >= 0,
    `「${r.worst.label}」底边 ${r.worst.bottom}px，底栏顶边 ${r.barTop}px，${gap >= 0 ? `还差 ${gap}px` : `被盖住 ${-gap}px`}`)
}
await b.close()
process.exit(fail ? 1 : 0)
