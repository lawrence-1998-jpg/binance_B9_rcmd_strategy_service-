import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const today = new Date().toISOString().slice(0, 10)
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
let fail = 0
/** 她的活有两条路：拿去问 AI，拿去问人。第二条也得走得通 */
const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'], permissions: ['clipboard-read', 'clipboard-write'] })
await ctx.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort())
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', (e) => errs.push(e.message))
await pg.goto(URL, { waitUntil: 'load' })
await pg.evaluate((s) => localStorage.setItem('deskside.v1', JSON.stringify(s)), makeState(today))
await pg.goto(URL + '#/work', { waitUntil: 'load' }); await pg.reload(); await pg.waitForTimeout(700)

await pg.locator('button:has-text("会员体系诊断")').first().click(); await pg.waitForTimeout(300)
await pg.locator('button:has-text("贴提纲")').first().click(); await pg.waitForTimeout(400)
await pg.locator('.sheet textarea').first().fill('1、他们内部现在怎么决定给谁发券\n2、什么情况下他们会推翻这个规则')
await pg.locator('button:has-text("拆开")').click(); await pg.waitForTimeout(700)

// 按内容认这一行，不按位置。
// 以前写的是 .qrow.first()，等于假设「列表里只有我刚拆出来的那两条」——
// 种子里一有真实的调研线，first() 就变成别人，
// 于是三条断言一起变红，而被测的功能一点没坏
const mine = pg.locator('.qrow', { hasText: '给谁发券' })
await mine.first().click(); await pg.waitForTimeout(500)
t('默认是「查资料」', await pg.locator('button[aria-pressed=true]:has-text("查资料")').count() === 1)
const aiPrompt = await pg.locator('.pbody').innerText()
t('这时候第二站是给模型的 Prompt', aiPrompt.includes('不许编数字'))

await pg.locator('button:has-text("约访谈")').click(); await pg.waitForTimeout(600)
t('切成访谈后，进度条改叫访谈的说法',
  (await pg.locator('.flow').innerText()).includes('提纲已备'), (await pg.locator('.flow').innerText()).replace(/\n/g, ' '))
const guide = await pg.locator('.pbody').innerText()
t('第二站换成了访谈提纲', guide.includes('开场') && guide.includes('收尾'), guide.split('\n')[0])
t('访谈提纲里没有给模型的硬约束（这是照着念的）', !guide.includes('不许编数字'))
t('带追问和「还有什么我没问到的」', guide.includes('追问反例') && guide.includes('我没问到'))
t('问题原文进去了', guide.includes('他们内部现在怎么决定给谁发券'))
t('留了记录的位置', guide.includes('记录：'))

await pg.locator('.sheet textarea').nth(1).fill('他说其实规则是运营手动调的，季度末尤其明显。')
await pg.waitForTimeout(300)
await pg.locator('.sheet .icon-btn').click(); await pg.waitForTimeout(500)
const row = await mine.first().innerText()
t('列表上标出这条是访谈', row.includes('访谈'), row.replace(/\n/g, ' ').slice(0, 60))
t('访谈那条的状态用访谈的说法', row.includes('访谈记录'), row.replace(/\n/g, ' ').slice(0, 60))
t('无页面错误', errs.length === 0, errs.slice(0, 2).join(' | '))
await b.close()
console.log(fail ? `\n✗ ${fail} 条不过` : '\n✓ 访谈这条路也通')
process.exit(fail ? 1 : 0)
