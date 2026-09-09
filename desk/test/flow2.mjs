import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const OUT = new globalThis.URL('./shots', import.meta.url).pathname
const today = new Date().toISOString().slice(0, 10)
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
let fail = 0

/**
 * 她说的那套完整流程，一路走到底：
 * 贴提纲 → 拿到一整套能直接复制的 Prompt → 去问 → 整段结果贴回来自动归位
 * → 记关键词 → 记数据（带出处）→ 写结论 → 收口状态 → 出材料
 */
const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'], permissions: ['clipboard-read', 'clipboard-write'] })
await ctx.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort())
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', (e) => errs.push(e.message))

await pg.goto(URL, { waitUntil: 'load' })
await pg.evaluate((s) => localStorage.setItem('deskside.v1', JSON.stringify(s)), makeState(today))
await pg.goto(URL + '#/work', { waitUntil: 'load' }); await pg.reload(); await pg.waitForTimeout(700)

// ---- ① 贴提纲 ----
// 两件事一起改：
// ① 用一条还没有调研线的项目 —— 这条套件整条是按位置走的
//    （first / nth(1) / nth(2)），「共三条」只在空盘子上成立，
//    而客户 A 那条线上已经有活儿了；
// ② 把 .qrow 圈在这条项目的卡片里 —— 工作屏是所有项目的调研线**同时**摊着，
//    全局的 .qrow 会把别的项目的行一起数进来。
//    以前两条都不成立却一直绿，只是因为种子里一条调研线都没有。
const card = pg.locator('.card', { has: pg.locator('button:has-text("增长策略陪跑")') }).first()
await card.locator('button:has-text("增长策略陪跑")').first().click(); await pg.waitForTimeout(300)
await card.locator('button:has-text("贴提纲")').first().click(); await pg.waitForTimeout(400)
await pg.locator('.sheet textarea').first().fill(
`1、UGC 投稿用户的流量下滑导致投稿流失问题，抖音有没有出现过，怎么解决的
2、抖音现在做作者流量反馈的流量占比大概有多少，是怎么做的
3、会员分层之后，低频用户的召回一般怎么做`)
await pg.waitForTimeout(200)
await pg.locator('button:has-text("拆开")').click(); await pg.waitForTimeout(700)

t('拆成三条', await card.locator('.qrow').count() === 3)
const firstRow = await card.locator('.qrow').first().innerText()
t('行首有题号（贴回来靠它对上）', (await card.locator('.qrow').first().locator('.qn').innerText()).trim() === '1',
  await card.locator('.qrow').first().locator('.qn').innerText())
t('序号前缀被剥掉了（「1、」不该进问题本身）',
  !(await card.locator('.qrow').first().locator('.row-t').innerText()).replace(/^1\s*/, '').startsWith('、'),
  await card.locator('.qrow').first().locator('.row-t').innerText())
t('拆完状态已经是「Prompt 已备」，不用再一条条去点生成',
  (await card.locator('.qrow').first().innerText()).includes('Prompt 已备'),
  firstRow.replace(/\n/g, ' ').slice(0, 46))

// ---- ② 一次复制一整套 ----
const setBtn = card.locator('button:has-text("复制整套")')
t('有「复制整套」，并标了条数', await setBtn.count() > 0,
  await setBtn.count() ? (await setBtn.innerText()).replace(/\n/g, ' ') : '')
await setBtn.click(); await pg.waitForTimeout(500)
const clip = await pg.evaluate(() => navigator.clipboard.readText().catch(() => null))
if (clip) {
  t('整套 Prompt 里三道题都在', ['UGC', '流量占比', '低频用户'].every((k) => clip.includes(k)))
  t('带「不许编数字」硬约束', clip.includes('不许编数字'))
  t('把题号标题格式定死了（不然贴不回来）', clip.includes('## 1.') && clip.includes('不要改题号'))
  t('一份就够（不是三份拼起来）', clip.split('# 角色').length === 2)
} else t('读到剪贴板', false, '无头环境读不到')

// ---- ③ 整段结果一次贴回，自动归位 ----
await card.locator('button:has-text("贴回整套结果")').click(); await pg.waitForTimeout(400)
await pg.locator('.sheet textarea').first().fill(
`先说一句：以下三题都做了检索。

## 1. UGC 投稿用户的流量下滑导致投稿流失
[事实] 抖音 2021 年前后上线「创作者服务中心」的流量诊断。
[推断] 起作用的是诊断的可见性，不是补贴本身。

## 2. 抖音现在做作者流量反馈的流量占比
[事实] 没有公开数据。
[推断] 估算区间 3%–8%，依据是……

## 3. 会员分层之后低频用户的召回
[事实] 常见做法是权益到期提醒 + 专属回归礼包。

## 还没搞清楚的
- 抖音诊断入口的实际打开率
- 回归礼包的成本结构`)
await pg.waitForTimeout(300)
await pg.locator('button:has-text("按题号分到各条")').click(); await pg.waitForTimeout(800)

const left = await pg.locator('.leftover').count()
t('没归到题上的那段被摆出来了，没有悄悄扔掉', left > 0,
  left ? (await pg.locator('.leftover').innerText()).replace(/\n/g, ' ').slice(0, 40) : '没显示')
await pg.locator('button:has-text("知道了，关掉")').click(); await pg.waitForTimeout(500)

const rows = await card.locator('.qrow').allInnerTexts()
t('三条都变成「有材料」', rows.filter((r) => r.includes('有材料')).length === 3,
  rows.map((r) => r.split('\n')[1]).join(' | '))

// 内容真的分对了地方
await card.locator('.qrow').nth(1).click(); await pg.waitForTimeout(500)
const f2 = await pg.locator('.sheet textarea').nth(1).inputValue()
t('第二条拿到的是第二题的答案', f2.includes('3%–8%') && !f2.includes('创作者服务中心'), f2.slice(0, 30))
t('结尾那节没被粘进第二条', !f2.includes('还没搞清楚的'))

const steps = await pg.locator('.flow-i').allInnerTexts()
t('四步进度条在', steps.length === 4, steps.map((x) => x.replace(/\n/g, '')).join(' → '))

// ---- ④ 关键词 ----
await pg.locator('input[aria-label=加关键词]').fill('流量诊断')
await pg.locator('button[aria-label="加上这个关键词"]').click(); await pg.waitForTimeout(300)
t('关键词加上了', await pg.locator('.kw.on').count() === 1, await pg.locator('.kw.on').first().innerText())

// ---- ⑤ 记数据（带出处、带置信） ----
await pg.locator('button:has-text("记一个数字")').click(); await pg.waitForTimeout(300)
await pg.locator('input[aria-label="数字或事实"]').fill('3%–8%')
await pg.locator('input[aria-label="它是什么"]').fill('作者流量反馈占大盘流量的比例（估算）')
await pg.locator('input[aria-label=出处]').fill('AI 推断，无公开来源')
await pg.locator('button:has-text("记下来")').click(); await pg.waitForTimeout(500)
t('数据记下了', await pg.locator('.fact').count() === 1)
t('数字和出处是绑在一起的', (await pg.locator('.fact').innerText()).includes('无公开来源'),
  (await pg.locator('.fact').innerText()).replace(/\n/g, ' · '))

// ---- ⑥ 写结论 ----
await pg.locator('.sheet textarea').last().fill('这个比例没有公开数据，别在材料里写死，用区间并标注估算。')
await pg.waitForTimeout(300)
await pg.locator('.sheet .icon-btn').click(); await pg.waitForTimeout(500)

// ---- ⑦ 收口：第三条不查了 ----
await card.locator('.qrow').nth(2).click(); await pg.waitForTimeout(400)
await pg.locator('button:has-text("不查了")').click(); await pg.waitForTimeout(400)
await pg.locator('.sheet .icon-btn').click(); await pg.waitForTimeout(500)
// 计数在卡片右上角那个 chip 上（卡片左下角那行留给「下一步」——
// 以前两处都在报同一个数，把「下一步」顶掉了）。
// 也得圈在这张卡里：全页找会捞到别的项目的进度
const prog = await card.locator('.chip').first().innerText()
t('「不查了」的那条不算进分母', prog.replace(/\s/g, '') === '1/2', prog)

// ---- ⑧ 出材料 ----
await card.locator('button:has-text("出材料")').click(); await pg.waitForTimeout(600)
const brief = await pg.evaluate(() => navigator.clipboard.readText().catch(() => null))
if (brief) {
  t('材料里有结论', brief.includes('别在材料里写死'))
  t('材料里带上了数据和出处', brief.includes('3%–8%') && brief.includes('无公开来源'))
  t('不含贴回来的 AI 原文（那是过程不是产物）', !brief.includes('[推断]'))
  t('照实写了「不查了」的那条', brief.includes('不查了') || brief.includes('还没搞清楚'))
  console.log('\n--- 材料预览 ---\n' + brief.slice(0, 700) + '\n---')
}

const de = await pg.evaluate(() => document.documentElement.scrollWidth > innerWidth ? 'overflow' : 'none')
t('无横向溢出', de === 'none', de)
t('无页面错误', errs.length === 0, errs.slice(0, 2).join(' | '))
await pg.screenshot({ path: OUT + '/flow2.png', fullPage: true })
await b.close()
console.log(fail ? `\n✗ ${fail} 条不过` : '\n✓ 全过')
process.exit(fail ? 1 : 0)
