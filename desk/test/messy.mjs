// 「贴回整套结果」靠 `## 1.` 这样的题号把内容分到各条上。
// Prompt 里写死了这个格式，但**模型会漂** —— 换个模型、换个心情，
// 回来的就可能是没有题号的一大段，或者题号写成「1、」「第一题」。
//
// 这时候唯一不能接受的结果是：**她的材料没了**。
// 分不出来可以，分错可以改，但不许悄悄吞掉。
import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const APP = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const today = new Date().toISOString().slice(0,10)
let fail = 0
const t = (n, ok, note='') => { console.log(`${ok?'✓':'✗'} ${n}${note?' — '+note:''}`); if(!ok) fail++ }

const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'], permissions:['clipboard-read','clipboard-write'] })
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', e => errs.push(e.message))
await pg.goto(APP, { waitUntil:'load' })
await pg.evaluate((s)=>localStorage.setItem('deskside.v1',JSON.stringify(s)), makeState(today))
await pg.goto(APP+'#/work', { waitUntil:'load' }); await pg.reload(); await pg.waitForTimeout(700)

const card = pg.locator('.card', { has: pg.locator('button:has-text("增长策略陪跑")') }).first()
await card.locator('button:has-text("贴提纲")').first().click(); await pg.waitForTimeout(400)
await pg.locator('.sheet textarea').first().fill('1、他们怎么定价\n2、续费率一般多少')
await pg.locator('button:has-text("拆开")').click(); await pg.waitForTimeout(700)
t('先拆出两条', await card.locator('.qrow').count() === 2)

// 模型回了一大段，一个题号都没有 —— 而且里面有她要的真东西
const MESSY = `关于定价：他们按人头分三档，年付打七折，这是从官网价目表看到的。
续费率方面，公开渠道查不到确切数字，行业里同类产品大概在 60%-75% 之间，
但这个区间是推断，没有权威来源，别写死。`
await card.locator('button:has-text("贴回整套结果")').click(); await pg.waitForTimeout(400)
await pg.locator('.sheet textarea').first().fill(MESSY)
await pg.waitForTimeout(200)
// toast 是瞬时的，得在点击之后马上抓，别等它自己消失
await pg.locator('button:has-text("按题号分到各条")').click()
await pg.waitForTimeout(350)
const toastText = await pg.locator('.toast').innerText().catch(() => '')
await pg.waitForTimeout(400)

t('没崩', errs.length === 0, errs.slice(0,2).join(' | '))
t('明确告诉她「没敢乱分」，而不是假装成功', /题号|没敢|分不|看不出/.test(toastText), toastText || '（没抓到 toast）')

// ⚠️ textarea 的内容是 value，不在 innerText 里。
// 第一版拿 body.innerText 去找，当然「找不到」—— 那是我自己写错的假阳性，
// 差点去改一段本来就正确的代码
const still = await pg.locator('.sheet textarea').first().inputValue()
t('她粘进去的内容一个字都还在（这条最要紧）',
  still.includes('年付打七折') && still.includes('60%-75%'),
  still ? `还在，${still.length} 字` : '⚠️ 真丢了')
t('没有硬塞给任何一条（塞错比不塞更糟）',
  await pg.evaluate(() => JSON.parse(localStorage.getItem('deskside.v1')).inquiries
    .filter(q => q.engagementId === 'e2').every(q => !q.findings)))

await b.close()
process.exit(fail ? 1 : 0)
