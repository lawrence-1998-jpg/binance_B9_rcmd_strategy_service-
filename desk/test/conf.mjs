// 置信度是算出来的，不是选出来的。
//
// 业内做法（原子化研究 / Glean.ly）是让证据的数量和新鲜度决定置信度，
// 而不是让人自己打分。手选的置信度跟「拍脑袋填的 62% 进度」是同一个病，
// 而那个已经砍掉了。
//
// 更要紧的是：prompt.ts 里发出去的硬约束写着「每个关键结论至少找
// 2 个独立来源交叉验证」，而以前 Fact 只能存一个 source ——
// App 存不下它自己要求的东西。
import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const APP = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const today = new Date().toISOString().slice(0,10)
let fail = 0
const t = (n, ok, note='') => { console.log(`${ok?'✓':'✗'} ${n}${note?' — '+note:''}`); if(!ok) fail++ }

const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'], permissions: ['clipboard-read','clipboard-write'] })
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', e => errs.push(e.message))

// ---------- ① 老数据的迁移 ----------
// 老结构：单个 source + 手选 confidence。她压低的要留住，她抬高的要丢掉。
await pg.goto(APP)
await pg.evaluate((s) => {
  s.inquiries = [{ id:'q9', engagementId:'e1', question:'迁移用', kind:'ai', keywords:[],
    facts: [
      { id:'f1', value:'A', what:'两个来源在老结构里存不下，只能存一个', source:'来源甲', confidence:'high' },
      { id:'f2', value:'B', what:'没出处却被标成高 —— 那个高没有任何东西撑着', source:'', confidence:'high' },
      { id:'f3', value:'C', what:'有出处但她知道不靠谱，当年压到了低', source:'某软文', confidence:'low' },
    ],
    // 得有结论，「出材料」才会出现 —— 那一步要验出处有没有全带上
    conclusion: '有个结论。',
    createdAt: Date.now(), updatedAt: Date.now() }]
  localStorage.setItem('deskside.v1', JSON.stringify(s))
}, makeState(today))
await pg.goto(APP+'#/work'); await pg.reload(); await pg.waitForTimeout(700)

// 迁移发生在 load 时的内存里，localStorage 要等下一次写入才跟着变（惰性迁移）。
// 所以这里从**界面**验迁移结果 —— 那也正是她真正会看到的东西。

// 界面上照着算出来的显示
const open = async (n=0) => {
  const card = pg.locator('.card', { has: pg.locator('button:has-text("会员体系诊断")') }).first()
  await card.locator('.qrow').nth(n).click(); await pg.waitForTimeout(500)
}
await open(0)
const facts = pg.locator('.sheet .fact')
t('三条老数据都还在', await facts.count() === 3)
t('一个出处 → 算「中」，她当年手填的「高」不算数了',
  (await facts.nth(0).innerText()).includes('中 置信') && (await facts.nth(0).innerText()).includes('来源甲'),
  (await facts.nth(0).innerText()).replace(/\n/g,' · ').slice(0,44))
t('没出处却标过「高」的 → 现在是「低」', (await facts.nth(1).innerText()).includes('低 置信'),
  (await facts.nth(1).innerText()).replace(/\n/g,' · ').slice(0,44))
t('她当年压低的档留住了，并注明是她压的',
  (await facts.nth(2).innerText()).includes('低 置信') && (await facts.nth(2).innerText()).includes('你手动压低了'),
  (await facts.nth(2).innerText()).replace(/\n/g,' · ').slice(0,52))

// ---------- ② 新加一条：出处条数决定档位 ----------
await pg.locator('.sheet button:has-text("记一个数字")').click(); await pg.waitForTimeout(300)
const conf = pg.locator('.conf-box')
t('默认 0 个出处 → 低', (await conf.innerText()).includes('按 0 个出处算') && (await conf.innerText()).includes('低 置信'))
t('写清楚了规则', (await conf.innerText()).includes('两个及以上独立来源'))
t('没有「抬到高」这种选项', !(await conf.innerText()).includes('压到「高」'))

await pg.locator('.sheet input[aria-label=出处]').fill('第一个来源')
await pg.waitForTimeout(250)
t('一个出处 → 中', (await conf.innerText()).includes('按 1 个出处算') && (await conf.innerText()).includes('中 置信'))

t('能再加一个出处', await pg.locator('.sheet button:has-text("再加一个出处")').count() === 1)
await pg.locator('.sheet button:has-text("再加一个出处")').click(); await pg.waitForTimeout(250)
await pg.locator('.sheet input[aria-label="第 2 个出处"]').fill('第二个独立来源')
await pg.waitForTimeout(250)
t('两个出处 → 高（这正是 prompt 里要求的交叉验证）',
  (await conf.innerText()).includes('按 2 个出处算') && (await conf.innerText()).includes('高 置信'))

t('高的时候可以往下压', await pg.locator('.conf-box .chip').count() === 2)
await pg.locator('.conf-box .chip:has-text("压到「中」")').click(); await pg.waitForTimeout(250)

await pg.locator('.sheet input[aria-label="数字或事实"]').fill('约 30%')
await pg.locator('.sheet input[aria-label="它是什么"]').fill('交叉验证过的一个比例')
await pg.locator('.sheet button:has-text("记下来")').click(); await pg.waitForTimeout(600)
const saved = await pg.evaluate(() =>
  JSON.parse(localStorage.getItem('deskside.v1')).inquiries.find(q => q.id==='q9').facts.at(-1))
t('两个出处都存下来了', saved.sources.length === 2, JSON.stringify(saved.sources))
t('压低的档存下来了', saved.lowered === 'mid')
t('没有写死的 confidence 字段', !('confidence' in saved))

// 写过一次之后，老数据也跟着落盘成新结构了
const all = await pg.evaluate(() =>
  JSON.parse(localStorage.getItem('deskside.v1')).inquiries.find(q => q.id==='q9').facts)
t('落盘之后老数据也是新结构了', all.every(f => Array.isArray(f.sources) && !('source' in f)),
  JSON.stringify(all.map(f => f.sources)))
t('落盘之后她压低的那档还在', all[2].lowered === 'low')
t('落盘之后她抬高的那档没留下', all[0].lowered === undefined && all[1].lowered === undefined)

// ---------- ③ 出材料时出处全都要带上 ----------
await pg.locator('.sheet .icon-btn').first().click(); await pg.waitForTimeout(400)
const card = pg.locator('.card', { has: pg.locator('button:has-text("会员体系诊断")') }).first()
await card.locator('button:has-text("出材料")').click(); await pg.waitForTimeout(700)
const brief = await pg.evaluate(() => navigator.clipboard.readText().catch(() => null))
if (brief) {
  t('材料里两个出处都在（不是只写一个）',
    brief.includes('第一个来源') && brief.includes('第二个独立来源'))
  t('没出处的照实写「没有出处」', brief.includes('没有出处'))
} else t('读到剪贴板', false, '无头环境读不到')

t('无页面错误', errs.length === 0, errs.slice(0,2).join(' | '))
await b.close()
process.exit(fail ? 1 : 0)
