import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const OUT = new globalThis.URL('./shots', import.meta.url).pathname
const today = new Date().toISOString().slice(0, 10)
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
let fail = 0
const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
await ctx.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort())
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', (e) => errs.push(e.message))
await pg.goto(URL, { waitUntil: 'load' })
await pg.evaluate((s) => localStorage.setItem('deskside.v1', JSON.stringify(s)), makeState(today))
await pg.reload({ waitUntil: 'load' }); await pg.waitForTimeout(700)
const notice = pg.locator('.install button'); if (await notice.count()) { await notice.first().click(); await pg.waitForTimeout(300) }

const secs = await pg.locator('.screen .eyebrow').allInnerTexts()
console.log('首页分区:', secs.join(' | '))
t('首页不再有「我们俩」（生活 tab 里已经有）', !secs.includes('我们俩'))
t('首页不再有「国庆」', !secs.some((x) => x.includes('国庆') || x.includes('假期')))
t('首页不再有「下一场」', !secs.includes('下一场'))
t('首页不再有「两条线」（工作 tab 就在底栏，摆两遍是重复）', !secs.includes('两条线'))
t('首页只剩四段', secs.filter((x) => !x.includes('·')).length <= 4, secs.join('/'))
t('Prompt 管理器在第一屏', await pg.locator('.hero').isVisible())
const heroTop = (await pg.locator('.hero').boundingBox()).y
t('它在首屏里（不用滚）', heroTop < 700, `y=${Math.round(heroTop)}`)
t('标出了条数', (await pg.locator('.hero-n').innerText()).includes('39'), await pg.locator('.hero-n').innerText())
await pg.locator('.hero').click(); await pg.waitForTimeout(600)
t('点它直接进 Prompt 管理器', await pg.locator('.sheet[aria-label="Prompt 管理器"]').count() === 1)
await pg.locator('.sheet .icon-btn').last().click(); await pg.waitForTimeout(500)

const sample = pg.locator('.sample')
t('有样例报告入口', await sample.count() === 1)
t('入口点明了它好在哪（已排除与未排除）', (await sample.innerText()).includes('已排除与未排除'))
const href = await sample.getAttribute('href')
t('指向本地文件（离线也能开）', href === './sample-report.html', String(href))
const r = await pg.evaluate(async (u) => { const x = await fetch(u); return { ok: x.ok, n: (await x.text()).length } }, href)
t('样例报告真的在（不是死链）', r.ok && r.n > 20000, `${r.n} 字节`)

t('文案是对她说话，不是谈论她', !(await pg.locator('.screen').innerText()).includes('她'))

// 断网也要能打开 —— 她说过是在飞机上、地铁里用的
const off = await ctx.newPage()
await off.route('**/*', (route, req) => req.url().startsWith('http://127.0.0.1:8765') ? route.continue() : route.abort())
await off.goto(URL, { waitUntil: 'load' }); await off.waitForTimeout(2500)
await off.context().setOffline(true)
const offRes = await off.evaluate(async () => {
  try { const r = await fetch('./sample-report.html'); return { ok: r.ok, n: (await r.text()).length } }
  catch (e) { return { ok: false, n: 0, e: String(e) } }
})
t('断网也能打开样例报告（已进 precache）', offRes.ok && offRes.n > 20000, JSON.stringify(offRes).slice(0, 60))
await off.context().setOffline(false)

t('无横向溢出', await pg.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
t('无页面错误', errs.length === 0, errs.slice(0, 2).join(' | '))
await pg.screenshot({ path: OUT + '/home-new.png', fullPage: true })
await b.close()
console.log(fail ? `\n✗ ${fail} 条不过` : '\n✓ 首页简介化完成')
process.exit(fail ? 1 : 0)
