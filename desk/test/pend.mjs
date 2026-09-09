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
await pg.goto(URL + '#/review', { waitUntil: 'load' }); await pg.reload(); await pg.waitForTimeout(700)

const rows = await pg.locator('.pend').count()
t('待归类每条是一整行可点', rows >= 3, `${rows} 条`)
const chipsClosed = await pg.locator('.card .chips .chip').count()
console.log('  收起时页面上的 chip 数:', chipsClosed)
t('默认不摊开分类 chip（原来每条七个，三条二十一个）', chipsClosed < 12, `${chipsClosed} 个`)
// 种子里第一条本来就归过类了，所以要看的是「还没归类的那些」怎么说
const texts = await pg.locator('.pend').allInnerTexts()
t('还没归类的那几条提示怎么用', texts.some((x) => x.includes('点一下归类')),
  texts.map((x) => x.split('\n').pop()).join(' | '))

await pg.locator('.pend').first().click(); await pg.waitForTimeout(400)
const chipsOpen = await pg.locator('.card .chips .chip').count()
t('点开那条才出 chip', chipsOpen > chipsClosed, `${chipsClosed} → ${chipsOpen}`)
t('一次只开一条', chipsOpen - chipsClosed <= 8, `多出 ${chipsOpen - chipsClosed} 个`)

// 归类还能用。注意 classify 只设 kind 不设 handled —— 归完还留在单子上，
// 所以要验的是「那一条的 kind 变了」，不是「单子少了一条」
const id0 = await pg.evaluate(() => JSON.parse(localStorage.getItem('deskside.v1')).notes.filter((n) => !n.handled)[0].id)
await pg.locator('.chips .chip:has-text("想法")').first().click(); await pg.waitForTimeout(500)
const kind0 = await pg.evaluate((id) => JSON.parse(localStorage.getItem('deskside.v1')).notes.find((n) => n.id === id).kind, id0)
t('归类真的写进去了', !!kind0, `kind=${kind0}`)
t('归好类的那条不再说「点一下归类」，而是说它现在是什么',
  (await pg.locator('.pend').first().innerText()).includes('已归为'),
  (await pg.locator('.pend').first().innerText()).replace(/\n/g, ' '))
t('归完自动收起，接着看下一条', await pg.locator('.card .chips .chip').count() <= chipsClosed)

// 明天的三件事：表单收起来了
const addBtn = pg.locator('button:has-text("定明天的")')
t('「明天的三件事」表单默认收起', await addBtn.count() === 1, await addBtn.count() ? await addBtn.innerText() : '')
await addBtn.click(); await pg.waitForTimeout(400)
t('点开才出输入框', await pg.locator('input[placeholder="明天先做什么"]').count() === 1)
await pg.locator('button:has-text("算了")').click(); await pg.waitForTimeout(300)
t('能收回去', await pg.locator('input[placeholder="明天先做什么"]').count() === 0)

const h = await pg.evaluate(() => document.querySelector('.screen').scrollHeight)
console.log(`  复盘现在 ${h}px（改之前 1809px）`)
t('复盘明显变短', h < 1500, `${h}px`)
t('无页面错误', errs.length === 0, errs.slice(0, 2).join(' | '))
await pg.screenshot({ path: OUT + '/review-new.png', fullPage: true })
await b.close()
console.log(fail ? `\n✗ ${fail} 条不过` : '\n✓ 复盘瘦下来了，归类没坏')
process.exit(fail ? 1 : 0)
