// 项目卡上「下一步」不能因为拆了调研线就消失。
//
// 之前：卡片右上角的 chip 显示「1 / 3」，卡片左下角显示「1 / 3 条有结论」——
// 同一个数，相隔 130px 说两遍；而真正该在那儿的「下一步 交初稿」
// 被这个重复的计数顶掉了。也就是说**她一贴提纲，下一步就看不见了**。
import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const today = new Date().toISOString().slice(0,10)
let fail = 0
const t = (n, ok, note='') => { console.log(`${ok?'✓':'✗'} ${n}${note?' — '+note:''}`); if(!ok) fail++ }
const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', e => errs.push(e.message))
await pg.goto(URL)
await pg.evaluate((s)=>localStorage.setItem('deskside.v1',JSON.stringify(s)), makeState(today))
await pg.goto(URL+'#/work'); await pg.reload(); await pg.waitForTimeout(700)

const cardOf = (name) => pg.locator('.card', { has: pg.locator(`button:has-text("${name}")`) }).first()

// e1 有 4 条调研线（3 条在跑 + 1 条搁置），也有 next='交初稿'
const withQ = await cardOf('会员体系诊断').innerText()
t('拆了调研线的卡片，「下一步」还在', withQ.includes('交初稿'), withQ.replace(/\n/g,' · ').slice(0,110))

// 同一个数不要在同一张卡上说两遍
const counts = (withQ.match(/1 \/ 3/g) || []).length
t('进度那个数在一张卡上只出现一次', counts === 1, `出现 ${counts} 次`)
t('计数还是看得到（在右上角那个 chip 上）', /1\s*\/\s*3/.test(withQ))

// e2 没有调研线：本来就该显示「下一步」，不能改坏
const noQ = await cardOf('增长策略陪跑').innerText()
t('没拆调研线的卡片，「下一步」照旧', noQ.includes('出工作坊纪要'), noQ.replace(/\n/g,' · ').slice(0,90))

// 一条 next 都没写的：得说点有用的，不能空着
await pg.evaluate(() => {
  const s = JSON.parse(localStorage.getItem('deskside.v1'))
  s.engagements = s.engagements.map(e => e.id==='e1' ? { ...e, next:'' } : e)
  localStorage.setItem('deskside.v1', JSON.stringify(s))
})
await pg.reload(); await pg.waitForTimeout(600)
const noNext = await cardOf('会员体系诊断').innerText()
t('没写下一步的，退回去说进度', noNext.includes('条有结论'), noNext.replace(/\n/g,' · ').slice(0,110))

t('无页面错误', errs.length === 0, errs.slice(0,2).join(' | '))
await b.close()
process.exit(fail ? 1 : 0)
