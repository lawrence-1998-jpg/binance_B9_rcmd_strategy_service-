import pkg from 'playwright'
const { chromium } = pkg
import { makeState } from './seed.mjs'
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const today = new Date().toISOString().slice(0, 10)
const b = await chromium.launch()
const ctx = await b.newContext({ viewport: { width: 430, height: 932 } })
await ctx.route('**fonts.g**', r => r.abort())
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', e => errs.push(e.message))
const t = (n, ok, note = '') => console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`)

// 12 条待归类：第 9 条起以前永远看不到也清不掉
await pg.goto(URL)
await pg.evaluate((s) => {
  s.notes = Array.from({ length: 12 }, (_, i) => ({ id: 'n' + i, text: '待归类第 ' + (i + 1) + ' 条', kind: null, createdAt: Date.now() - i * 3600000, handled: false }))
  localStorage.setItem('deskside.v1', JSON.stringify(s))
}, makeState(today))
await pg.goto(URL + '#/review'); await pg.reload(); await pg.waitForTimeout(500)
const shown1 = await pg.evaluate(()=>document.body.innerText.split('\n').filter(l=>l.startsWith('待归类第')).length)
const expandBtn = pg.locator('button:has-text("全部展开")')
const hasExpand = await expandBtn.count() > 0
t('12 条待归类默认只显示 8 条', shown1 === 8, `实际 ${shown1} 条`)
t('有「全部展开」入口', hasExpand, hasExpand ? (await expandBtn.innerText()).trim() : '没有')
if (hasExpand) {
  await expandBtn.click(); await pg.waitForTimeout(300)
  const shown2 = await pg.evaluate(()=>document.body.innerText.split('\n').filter(l=>l.startsWith('待归类第')).length)
  t('展开后 12 条全在', shown2 === 12, `实际 ${shown2} 条`)
  const before = await pg.evaluate(() => JSON.parse(localStorage.getItem('deskside.v1')).notes.filter(n => n.handled).length)
  await pg.locator('.pend').last().click(); await pg.waitForTimeout(300)
await pg.locator('button:has-text("归档")').last().click()
  await pg.waitForTimeout(300)
  const after = await pg.evaluate(() => JSON.parse(localStorage.getItem('deskside.v1')).notes.filter(n => n.handled).length)
  t('第 9 条以后的也能真的归档掉', after > before, `已处理 ${before}→${after}`)
}

// GrowText 自动长高
await pg.goto(URL); await pg.evaluate(s => localStorage.setItem('deskside.v1', JSON.stringify(s)), makeState(today))
await pg.goto(URL + '#/review'); await pg.reload(); await pg.waitForTimeout(500)
const ta = pg.locator('textarea').first()
const h0 = (await ta.boundingBox()).height
await ta.fill('这是一段很长很长的话，长到必须换好几行才放得下，用来检查输入框会不会跟着内容长高，而不是把写好的内容藏进一个只有两行高的滚动框里让人看不见。再补一点字确保它真的超过三行。')
await pg.waitForTimeout(500)
const h1 = (await ta.boundingBox()).height
t('三句话输入框跟着内容长高', h1 > h0 + 20, `${Math.round(h0)}px → ${Math.round(h1)}px`)

// 手写过之后「重写」要先问
const rewrite = pg.locator('button:has-text("按今天的事重写")')
await rewrite.click(); await pg.waitForTimeout(400)
const dlg = await pg.evaluate(() => { const d = document.querySelector('.dialog'); return d ? d.textContent.slice(0, 24) : null })
t('手写过之后点「重写」会先问', !!dlg, dlg || '直接覆盖了')
if (dlg) { await pg.locator('.dialog .btn.quiet').click(); await pg.waitForTimeout(250) }
const kept = await pg.evaluate(() => JSON.parse(localStorage.getItem('deskside.v1')).entries.find(e => e.date === new Date().toISOString().slice(0, 10))?.lines[0] || '')
t('点「算了」后手写内容还在', kept.includes('很长很长'), kept.slice(0, 18) + '…')

console.log('\n页面错误:', errs.length ? errs : '无')
await b.close()
