import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const OUT = new globalThis.URL('./shots', import.meta.url).pathname
const today = new Date().toISOString().slice(0, 10)
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
let fail = 0
/** 扩充后的 prompt 库 + 零件：挂上去要真的跟着复制走，而且要记住 */
const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'], permissions: ['clipboard-read', 'clipboard-write'] })
await ctx.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort())
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', (e) => errs.push(e.message))
await pg.goto(URL, { waitUntil: 'load' })
await pg.evaluate((s) => localStorage.setItem('deskside.v1', JSON.stringify(s)), makeState(today))
await pg.goto(URL + '#/work', { waitUntil: 'load' }); await pg.reload(); await pg.waitForTimeout(600)
await pg.locator('button[aria-label="Prompt 管理器"]').click(); await pg.waitForTimeout(600)

const head = await pg.locator('.sheet .sheet-head .eyebrow').first().innerText()
t('库变大了（原来 15 条）', /39|4\d/.test(head), head)
const cats = await pg.locator('.chip').allInnerTexts()
t('新分类都在（成本 / 写东西 / 通用）', ['成本', '写东西', '通用'].every((c) => cats.includes(c)), cats.join(' '))

// 打开一条通用的
await pg.locator('.pitem:has-text("别顺着我说")').first().click(); await pg.waitForTimeout(500)
const plain = await pg.locator('.pbody').innerText()
t('打开的是「别顺着我说」', plain.includes('不要先铺垫'), plain.slice(0, 24))

// 挂零件
await pg.locator('button:has-text("挑几个挂上")').click(); await pg.waitForTimeout(400)
t('零件分成叮嘱语和附录两类', (await pg.locator('.card .eyebrow').allInnerTexts()).some((x) => x === '叮嘱语'))
const rows = await pg.locator('.partrow').count()
t('零件条数对（19 个）', rows === 19, String(rows))
await pg.locator('.partrow:has-text("不许编数字")').click(); await pg.waitForTimeout(200)
await pg.locator('.partrow:has-text("给出处")').click(); await pg.waitForTimeout(200)
await pg.locator('.partrow:has-text("完工标准")').click(); await pg.waitForTimeout(300)

const btn = await pg.locator('.sheet-foot .btn').first().innerText()
t('复制按钮标出挂了几个', btn.includes('含 3 个零件'), btn.replace(/\n/g, ' '))
await pg.locator('.sheet-foot .btn').first().click(); await pg.waitForTimeout(600)
const clip = await pg.evaluate(() => navigator.clipboard.readText().catch(() => null))
if (clip) {
  t('正文还在', clip.includes('不要先铺垫'))
  t('叮嘱语挂上了', clip.includes('不许编数字') && clip.includes('能给链接就给链接'))
  t('附录挂上了，并且带标题', clip.includes('【完工标准（什么才算做完）】'), clip.slice(-60).replace(/\n/g, '|'))
  t('两类是分开的段落，不是糊成一坨', clip.split('---').length >= 3, `${clip.split('---').length - 1} 个分隔`)
  t('多条叮嘱语之间有空行', /有害得多。\n\n每个关键结论/.test(clip))
  console.log('\n--- 拼出来的尾巴 ---\n' + clip.slice(-460) + '\n---')
}

// 记住
await pg.locator('.icon-btn[aria-label=返回]').click(); await pg.waitForTimeout(400)
await pg.locator('.pitem:has-text("写需求")').first().click(); await pg.waitForTimeout(500)
const btn2 = await pg.locator('.sheet-foot .btn').first().innerText()
t('换一条 prompt，挂的零件还在（记住了）', btn2.includes('含 3 个零件'), btn2.replace(/\n/g, ' '))
await pg.reload({ waitUntil: 'load' }); await pg.waitForTimeout(600)
const kept = await pg.evaluate(() => JSON.parse(localStorage.getItem('deskside.v1')).promptParts)
t('刷新之后也还在', Array.isArray(kept) && kept.length === 3, JSON.stringify(kept))

// 零件也要能单独找、单独拿
await pg.reload({ waitUntil: 'load' }); await pg.waitForTimeout(500)
await pg.locator('button[aria-label="Prompt 管理器"]').click(); await pg.waitForTimeout(500)
await pg.locator('.chip:has-text("零件")').click(); await pg.waitForTimeout(500)
const listed = await pg.locator('.partrow').count()
t('列表里能单独浏览零件', listed === 19, String(listed))
await pg.locator('.field').first().fill('出处'); await pg.waitForTimeout(400)
const found = await pg.locator('.partrow').count()
t('零件能搜', found >= 1 && found < 19, `搜到 ${found} 个`)
await pg.locator('.partrow').first().click(); await pg.waitForTimeout(500)
const one = await pg.evaluate(() => navigator.clipboard.readText().catch(() => null))
// 单独复制就该只有那一条：不带分隔线、不把挂着的三个零件也塞进来
if (one) t('点一条＝单独复制它（不带分隔线、不夹带挂着的那几个）',
  !one.includes('---') && !one.includes('不许编数字') && one.length < 200,
  `${one.length} 字：${one.split('\n')[0]}`)

t('无页面错误', errs.length === 0, errs.slice(0, 2).join(' | '))
await b.close()
console.log(fail ? `\n✗ ${fail} 条不过` : '\n✓ 零件能挂、能跟着复制、能记住')
process.exit(fail ? 1 : 0)
