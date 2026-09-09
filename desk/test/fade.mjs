// 荒掉的分区：问一次要不要撤，然后闭嘴。
//
// 最要紧的一条断言是「说了留着就真的不再问」—— 一个问完还接着问的提示，
// 就是新的维护成本，而这整件事本来就是为了减维护成本。
import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const APP = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const today = new Date().toISOString().slice(0,10)
let fail = 0
const t = (n, ok, note='') => { console.log(`${ok?'✓':'✗'} ${n}${note?' — '+note:''}`); if(!ok) fail++ }
const DAY = 86400000

const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', e => errs.push(e.message))

// 造一份「想对他说」很久没动的状态
async function seed (momentAgeDays, extra = {}) {
  await pg.goto(APP)
  await pg.evaluate(({ s, age, extra, DAY }) => {
    s.moments = [{ id:'m1', text:'很久以前写的一句', createdAt: Date.now() - age*DAY }]
    Object.assign(s, extra)
    localStorage.setItem('deskside.v1', JSON.stringify(s))
  }, { s: makeState(today), age: momentAgeDays, extra, DAY })
  await pg.goto(APP+'#/life'); await pg.reload(); await pg.waitForTimeout(600)
}
const offer = () => pg.locator('.fade-offer', { hasText: '天没动了' })
const sectionThere = (label) => pg.locator('.sect-l', { hasText: label })

// ---- 没荒的时候不许出声 ----
await seed(3)
t('三天前刚写过，不问', await offer().count() === 0)
t('分区还在', await sectionThere('想对他说').count() > 0)

// ---- 荒了才问 ----
await seed(30)
t('三十天没动，开口问了', await offer().count() > 0)
t('说的是天数不是「快去填」', (await offer().first().innerText()).includes('30 天没动了'),
  (await offer().first().innerText()).replace(/\n/g,' '))
t('两个选项：收起来 / 留着',
  await pg.locator('.fade-offer button:has-text("收起来")').count() === 1 &&
  await pg.locator('.fade-offer button:has-text("留着")').count() === 1)

// ---- 档案型的分区一个都不许问 ----
t('纪念日那种「填一次就不动」的，不问它', await pg.locator('.fade-offer').count() === 1,
  `页面上共 ${await pg.locator('.fade-offer').count()} 条提示`)

// ---- 留着 = 真的闭嘴 ----
await pg.locator('.fade-offer button:has-text("留着")').first().click()
await pg.waitForTimeout(500)
t('点「留着」之后当场就不问了', await offer().count() === 0)
t('分区原样留着', await sectionThere('想对他说').count() > 0)
await pg.reload(); await pg.waitForTimeout(600)
t('刷新之后也还是不问（不是只藏了这一次）', await offer().count() === 0)
t('kept 里记下了时间', await pg.evaluate(() =>
  typeof JSON.parse(localStorage.getItem('deskside.v1')).kept.moments === 'number'))

// ---- 收起来 ----
await seed(30)
await pg.locator('.fade-offer button:has-text("收起来")').first().click()
await pg.waitForTimeout(600)
t('收起来之后这块不见了', await sectionThere('想对他说').count() === 0)
t('内容一条没删', await pg.evaluate(() =>
  JSON.parse(localStorage.getItem('deskside.v1')).moments.length === 1))
t('hidden 里记了 key', await pg.evaluate(() =>
  JSON.parse(localStorage.getItem('deskside.v1')).hidden.includes('moments')))
await pg.reload(); await pg.waitForTimeout(600)
t('刷新之后仍然收着', await sectionThere('想对他说').count() === 0)

// ---- 设置里放得回来 ----
await pg.goto(APP+'#/review'); await pg.reload(); await pg.waitForTimeout(500)
await pg.locator('button[aria-label=设置]').click(); await pg.waitForTimeout(500)
const back = pg.locator('.sheet button:has-text("放回来")')
t('设置里列出了收起来的那块', await back.count() === 1)
await back.first().click(); await pg.waitForTimeout(500)
await pg.locator('.sheet .icon-btn').first().click(); await pg.waitForTimeout(400)
await pg.goto(APP+'#/life'); await pg.reload(); await pg.waitForTimeout(600)
t('放回来之后分区回到原位', await sectionThere('想对他说').count() > 0)
t('放回来之后不会立刻又问一遍', await offer().count() === 0)

// ---- 一条都没有的分区不许自作主张 ----
await pg.goto(APP)
await pg.evaluate((s) => { s.moments = []; localStorage.setItem('deskside.v1', JSON.stringify(s)) }, makeState(today))
await pg.goto(APP+'#/life'); await pg.reload(); await pg.waitForTimeout(600)
t('一条都没写过的分区，不问也不收', await offer().count() === 0 && await sectionThere('想对他说').count() > 0)

t('无页面错误', errs.length === 0, errs.slice(0,2).join(' | '))
await b.close()
process.exit(fail ? 1 : 0)
