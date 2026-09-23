/**
 * 仓库里签着的那份离线单文件版（web/desk/deskside-standalone.html）：
 * 下载下来双击就能用，也是直接发给别人看的那一份。没有服务器、没有 Claude。
 *
 * 踩过的坑：单独发出去的 HTML 如果 <meta charset> 不在最前面，
 * iPhone 的 Safari 会按 GBK 猜，满屏乱码。所以专门盯着它。
 */
import pkg from 'playwright'
import { readFileSync } from 'node:fs'
const { chromium, devices } = pkg
const PATH = new globalThis.URL('../../web/desk/deskside-standalone.html', import.meta.url)
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }

const raw = readFileSync(PATH)
const head = raw.subarray(0, 1024).toString()
t('<meta charset="utf-8"> 在头 1024 字节里（否则 iPhone 会按 GBK 猜成乱码）', /charset=["']?utf-8/i.test(head), `在第 ${raw.indexOf(Buffer.from('charset'))} 字节`)
t('以 <!doctype html> 开头', /^<!doctype html>/i.test(head))

const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13'], permissions: ['clipboard-read', 'clipboard-write'] })
const outside = []
await ctx.route('**/*', (route, req) => {
  if (!req.url().startsWith('file://')) { outside.push(req.url()); return route.abort() }
  return route.continue()
})
const pg = await ctx.newPage()
const errs = []
pg.on('pageerror', (e) => errs.push(e.message))
await pg.goto(PATH.href, { waitUntil: 'load' })
await pg.waitForTimeout(800)
t('标题是「随手拾」', (await pg.title()) === '随手拾', await pg.title())
t('双击打开就能用（出来了收件框和示例卡）', (await pg.locator('#capture').count()) === 1 && (await pg.locator('.card').count()) === 3)

await pg.locator('#capture').fill('明天下午 3 点和 Lily 通电话 138 1234 5678')
await pg.locator('.take').click()
await pg.waitForTimeout(300)
await pg.locator('.card.open .row', { hasText: '电话' }).click()
await pg.waitForTimeout(200)
t('离线版里一样能收、能认、能复制', (await pg.evaluate(() => navigator.clipboard.readText())) === '138 1234 5678')
t('没有任何外部请求', outside.length === 0, outside.slice(0, 2).join(' '))
t('file:// 下没有报错（Service Worker 那套完全空转）', errs.length === 0, errs.slice(0, 2).join(' | '))
await b.close()
process.exit(fail ? 1 : 0)
