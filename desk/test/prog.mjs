// 卡片上那个百分比。
//
// 起因是一张截图：「增长策略陪跑」右上角写着 45%，而正下方那根进度条
// 是空的。两个数说的是同一件事，差了 45 个百分点。
//
// 原因是一次只做了一半的重构：pct() 早就改成了「有结论条数 / 总条数」
// （没拆提纲时恒等于 0），但右上角那个 chip 和编辑面板里 0–100 的
// 手填滑块都留在原地。389 条断言一条都没碰过它。
//
// 所以这套测的是一条不变量，比「chip 该显示什么」更硬：
//   **同一张卡片上，报数的地方不许互相矛盾。**
// 要么都报、且一致；要么都不报。
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
const errs = []; pg.on('pageerror', e => errs.push(e.message))

await pg.goto(APP)
await pg.evaluate((s) => localStorage.setItem('deskside.v1', JSON.stringify(s)), makeState(today))
await pg.goto(APP + '#/work'); await pg.reload(); await pg.waitForTimeout(700)

// 每张 engagement 卡片：名字、chip 文字、进度条有没有、条走了多宽
async function cards () {
  const out = []
  for (const c of await pg.locator('.card').all()) {
    const name = await c.locator('.row-t').first().innerText().catch(() => null)
    if (!name) continue
    const chip = await c.locator('.chip').first().innerText().catch(() => null)
    const bars = await c.locator('[role=progressbar]').count()
    const aria = bars ? Number(await c.locator('[role=progressbar]').first().getAttribute('aria-valuenow')) : null
    out.push({ name, chip, bars, aria })
  }
  return out
}

const cs = await cards()
const split = cs.find((c) => c.name.includes('会员体系诊断'))   // 拆过提纲：3 条调研线，1 条有结论
const whole = cs.find((c) => c.name.includes('增长策略陪跑'))   // 没拆：seed 里 progress=45

t('两张卡都找到了', !!split && !!whole, cs.map(c=>c.name).join(' / '))

// ---- 这是这套的主角 ----
for (const c of cs) {
  const reportsNumber = /\d/.test(c.chip ?? '')
  // 报了数就得有条，有条就得报数 —— 一张卡上不能一个说 45%、一个说 0
  t(`「${c.name}」chip 和进度条要么都报数、要么都不报`,
    reportsNumber === (c.bars > 0), `chip=${c.chip} 条=${c.bars}`)
}

// ---- 拆过提纲的：数是真的，而且两处一致 ----
t('拆过提纲 → chip 报「1 / 3」', split.chip === '1 / 3', split.chip)
t('拆过提纲 → 有进度条', split.bars === 1)
t('条走的宽度＝1/3，跟 chip 对得上', Math.round(split.aria) === 33, String(split.aria))

// ---- 没拆提纲的：不报数，也不画条 ----
t('没拆提纲 → chip 说「还没拆」', whole.chip === '还没拆', whole.chip)
t('没拆提纲 → chip 里没有百分号', !/%/.test(whole.chip ?? ''), whole.chip)
t('没拆提纲 → 根本不画进度条', whole.bars === 0, `条=${whole.bars}`)

// ---- 老数据里的 progress 要被彻底无视 ----
// seed 里 e2.progress=45 / e1=62 / e3=40 / e4=75，一个都不许露头
const bodyText = await pg.locator('body').innerText()
t('老数据的 45% 没有出现在界面上', !bodyText.includes('45%'), '看 seed 里 e2.progress=45')
t('老数据的 62% 也没有', !bodyText.includes('62%'))
await pg.goto(APP + '#/work?tab=byte'); await pg.waitForTimeout(400)
const byteText = await pg.locator('body').innerText()
t('字节那条线上的 40% / 75% 同样不出现', !byteText.includes('40%') && !byteText.includes('75%'))

// ---- 手填滑块必须没了 ----
await pg.goto(APP + '#/work'); await pg.reload(); await pg.waitForTimeout(600)
await pg.getByText('增长策略陪跑').click(); await pg.waitForTimeout(400)
t('展开没拆提纲的卡片，里面没有 0–100 的手填滑块',
  await pg.locator('input[type=range]').count() === 0)
const openText = await pg.locator('body').innerText()
t('展开后也没有「进度 45%」这种字样', !/进度\s*\d+%/.test(openText))
// 真正说得出话的四样还在
t('阶段还在', openText.includes('阶段'))
t('卡在哪还在', openText.includes('卡在哪'))
t('下一步还在', openText.includes('下一步'))

// ---- 新建的 engagement 不许再带 progress 字段 ----
await pg.goto(APP + '#/work'); await pg.reload(); await pg.waitForTimeout(500)
await pg.getByRole('button', { name: '＋ 加一件' }).click(); await pg.waitForTimeout(300)
await pg.locator('input.field').first().fill('随手加的一件')
await pg.getByRole('button', { name: '加进来' }).click(); await pg.waitForTimeout(500)
const fresh = await pg.evaluate(() => {
  const s = JSON.parse(localStorage.getItem('deskside.v1'))
  return s.engagements[s.engagements.length - 1]
})
t('新建的 engagement 里没有 progress 这个字段',
  fresh && !('progress' in fresh), JSON.stringify(fresh ?? {}).slice(0, 120))

t('没有 JS 报错', errs.length === 0, errs.join(' | '))

await b.close()
console.log(fail ? `\n${fail} 条没过` : '\n全过')
process.exit(fail ? 1 : 0)
