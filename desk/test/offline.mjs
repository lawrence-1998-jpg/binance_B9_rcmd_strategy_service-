/**
 * 不在 claude.ai 里打开（GitHub Pages、下载的单文件）：没有 window.claude。
 * 页面照样能收、能整理（本地那一遍）、能复制、刷新还在 —— 只是少了 AI。
 */
import pkg from 'playwright'
const { chromium, devices } = pkg
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }

const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13'], permissions: ['clipboard-read', 'clipboard-write'] })
const pg = await ctx.newPage()
const errs = []
pg.on('pageerror', (e) => errs.push(e.message))
const wait = (ms = 300) => pg.waitForTimeout(ms)
const cards = () => pg.locator('.list article.card')

await pg.goto(URL, { waitUntil: 'load' })
await pg.evaluate(() => localStorage.clear())
await pg.reload({ waitUntil: 'load' }); await wait(500)

t('没有 Claude 时说清楚：只存在这台设备，在 Claude 里打开才有 AI', (await pg.locator('.cap-hint').innerText()).includes('只存在这台设备'), await pg.locator('.cap-hint').innerText())
t('空的时候照样有示例卡', (await pg.locator('.badge', { hasText: '示例' }).count()) === 3)

await pg.evaluate(() => navigator.clipboard.writeText('明天下午 3 点跟 Lily 通电话 138 1234 5678，聊报价 ¥36,000'))
await pg.locator('#capture').focus()
await pg.keyboard.press('Control+V'); await wait()
const c = cards().first()
t('粘贴即收下', (await cards().count()) === 1)
t('不转圈（没有 Claude 可等）', (await c.locator('.busy-t').count()) === 0 && (await c.getAttribute('data-status')) === 'local')
const vals = await c.locator('.row-v').allInnerTexts()
t('本地认出了时间、电话、金额', vals.some((v) => v.includes('明天下午 3 点')) && vals.includes('138 1234 5678') && vals.some((v) => v.includes('36,000')), JSON.stringify(vals))
t('没有「重新整理」（这里没有 Claude 可以叫）', (await c.locator('.acts button', { hasText: '重新整理' }).count()) === 0)

await c.locator('.row', { hasText: '电话' }).click(); await wait()
t('一样能点一格复制', (await pg.evaluate(() => navigator.clipboard.readText())) === '138 1234 5678')
await c.locator('.copies .btn', { hasText: '复制给 AI' }).click(); await wait()
t('复制给 AI：没有 Claude 起的指令，也有一句兜底的', (await pg.evaluate(() => navigator.clipboard.readText())).startsWith('请帮我理解这条信息'))

await pg.reload({ waitUntil: 'load' }); await wait(500)
t('刷新之后还在（存在这台设备的浏览器里）', (await cards().count()) === 1)
t('页脚说清楚存在哪', (await pg.locator('.foot').innerText()).includes('这台设备'))
t('没有页面报错', errs.length === 0, errs.join(' | '))
await b.close()
process.exit(fail ? 1 : 0)
