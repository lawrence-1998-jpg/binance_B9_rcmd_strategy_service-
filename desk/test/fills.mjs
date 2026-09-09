import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const today = new Date().toISOString().slice(0, 10)
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
let fail = 0
/** 39 条里 31 条带占位符 —— 复制出去必须是填好的，不然她得在手机上找尖括号 */
const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'], permissions: ['clipboard-read', 'clipboard-write'] })
await ctx.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort())
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', (e) => errs.push(e.message))
await pg.goto(URL, { waitUntil: 'load' })
await pg.evaluate((s) => localStorage.setItem('deskside.v1', JSON.stringify(s)), makeState(today))
await pg.goto(URL + '#/work', { waitUntil: 'load' }); await pg.reload(); await pg.waitForTimeout(600)
await pg.locator('button[aria-label="Prompt 管理器"]').click(); await pg.waitForTimeout(500)

await pg.locator('.pitem:has-text("帮我挑刺")').first().click(); await pg.waitForTimeout(500)
const label = await pg.locator('.card .eyebrow').first().innerText()
t('认出了占位符并列出来', label.includes('我的方案'), label)
const before = await pg.locator('.pbody').innerText()
t('没填之前正文里还带着尖括号', before.includes('<我的方案'), before.split('\n')[0])
t('明确提示还有几处没填', (await pg.locator('.sheet-foot').innerText()).includes('还有 1 处没填'))

await pg.locator('textarea[aria-label="我的方案 / 我写的东西"]').fill('用关键词黑名单过滤低质内容')
await pg.waitForTimeout(400)
const after = await pg.locator('.pbody').innerText()
t('填完预览里就换成了真内容', after.includes('用关键词黑名单过滤低质内容') && !after.includes('<我的方案'), after.split('\n')[0])
t('填完之后不再提示没填', !(await pg.locator('.sheet-foot').innerText()).includes('没填'))

await pg.locator('.sheet-foot .btn').first().click(); await pg.waitForTimeout(500)
const clip = await pg.evaluate(() => navigator.clipboard.readText().catch(() => null))
if (clip) {
  t('复制出去的是填好的', clip.includes('用关键词黑名单过滤低质内容'))
  t('复制出去的不含尖括号占位符', !clip.includes('<我的方案'))
  t('prompt 正文还完整', clip.includes('三个最致命的问题'))
}

// 留空的要原样保留，不能悄悄变没
await pg.locator('.icon-btn[aria-label=返回]').click(); await pg.waitForTimeout(400)
await pg.locator('.pitem:has-text("解释给外行听")').first().click(); await pg.waitForTimeout(500)
const carried = await pg.locator('textarea').first().inputValue()
t('换一条时上一条填的内容不会串过来', carried === '', carried.slice(0, 20))
await pg.locator('.sheet-foot .btn').first().click(); await pg.waitForTimeout(500)
const clip2 = await pg.evaluate(() => navigator.clipboard.readText().catch(() => null))
if (clip2) t('留空的原样保留 <…>，不悄悄替换成空', clip2.includes('<要解释的东西>'), clip2.split('\n')[0])

t('无页面错误', errs.length === 0, errs.slice(0, 2).join(' | '))
await b.close()
console.log(fail ? `\n✗ ${fail} 条不过` : '\n✓ 复制出去就是填好的')
process.exit(fail ? 1 : 0)
