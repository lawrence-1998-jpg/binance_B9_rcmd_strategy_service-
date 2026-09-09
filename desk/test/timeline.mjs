import pkg from 'playwright'
const { chromium } = pkg
import { makeState } from './seed.mjs'
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const OUT = new globalThis.URL('./shots', import.meta.url).pathname
const today = new Date().toISOString().slice(0, 10)
const b = await chromium.launch()
const ctx = await b.newContext({ viewport: { width: 430, height: 932 }, deviceScaleFactor: 2 })
await ctx.route('**fonts.g**', r => r.abort())
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', e => errs.push(e.message))
const t = (n, ok, note = '') => console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`)

// 一年的日记 + 一年的任务：这是「攒了一年之后」的真实体量
await pg.goto(URL)
await pg.evaluate((s) => {
  const d = (n) => { const x = new Date(); x.setDate(x.getDate() - n); return x.toISOString().slice(0, 10) }
  s.entries = Array.from({ length: 365 }, (_, i) => ({
    date: d(i),
    lines: [`第 ${i + 1} 天做完了一些事。`, '力气主要花在咨询顾问。', '明天先做下一件。'],
    auto: i % 3 === 0, updatedAt: Date.now() - i * 86400000,
  }))
  s.tasks = Array.from({ length: 1200 }, (_, i) => ({
    id: 'bt' + i, title: '任务 ' + i, domain: ['consult', 'byte', 'us', 'me'][i % 4],
    est: 30, done: i % 2 === 0, date: d(i % 365),
  }))
  s.photos = Array.from({ length: 120 }, (_, i) => ({
    id: 'bp' + i, caption: '', date: d(i * 3 % 365), createdAt: Date.now(),
  }))
  localStorage.setItem('deskside.v1', JSON.stringify(s))
}, makeState(today))

await pg.goto(URL + '#/review'); await pg.reload(); await pg.waitForTimeout(800)
for (const btn of await pg.locator('button').all()) {
  if (((await btn.innerText().catch(() => '')) || '').includes('时间轴')) { await btn.click(); break }
}

const t0 = Date.now()
await pg.waitForSelector('.tl-month', { timeout: 10000 })
const renderMs = Date.now() - t0

const r = await pg.evaluate(() => {
  const months = [...document.querySelectorAll('.tl-month')].map(m => m.innerText.replace(/\n/g, ' '))
  const items = document.querySelectorAll('.tl-item').length
  const sticky = document.querySelector('.tl-month') ? getComputedStyle(document.querySelector('.tl-month')).position : null
  const de = document.documentElement
  return { months, items, sticky, overflow: de.scrollWidth > innerWidth ? `${de.scrollWidth}>${innerWidth}` : 'none' }
})
t('365 天全部渲染出来', r.items === 365, `${r.items} 条`)
t('按月分组', r.months.length >= 12, `${r.months.length} 个月：${r.months.slice(0, 3).join(' | ')}`)
t('月份条吸顶', r.sticky === 'sticky', r.sticky)
t('无横向溢出', r.overflow === 'none', r.overflow)
t('首屏渲染不卡', renderMs < 3000, `${renderMs}ms`)

// 滚动流畅度：连续滚 20 次量总耗时
const s0 = Date.now()
for (let i = 0; i < 20; i++) { await pg.mouse.wheel(0, 800); await pg.waitForTimeout(16) }
const scrollMs = Date.now() - s0
t('滚动 20 屏不卡', scrollMs < 4000, `${scrollMs}ms`)

await pg.screenshot({ path: OUT + '/tl-year.png' })
await pg.evaluate(() => window.scrollTo(0, 0)); await pg.waitForTimeout(300)
await pg.screenshot({ path: OUT + '/tl-top.png' })

console.log('\n页面错误:', errs.length ? errs.slice(0, 3) : '无')
await b.close()
