/**
 * 仓库里签着的那份离线单文件版（web/desk/deskside-standalone.html）：
 * 下载下来双击就能用，也是随手发给别人看的那一份。没有服务器、没有 Service Worker。
 *
 * 踩过的坑：单独发出去的 HTML 如果 <meta charset> 不在最前面，
 * iPhone 的 Safari 会按 GBK 猜，满屏乱码。所以这条专门盯着它。
 */
import pkg from 'playwright'
import { readFileSync } from 'node:fs'
const { chromium, devices } = pkg
const PATH = new globalThis.URL('../../web/desk/deskside-standalone.html', import.meta.url)
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }

const raw = readFileSync(PATH)
const at = raw.indexOf(Buffer.from('charset'))
t('<meta charset="utf-8"> 在头 1024 字节里（否则 iPhone 会按 GBK 猜成乱码）', at >= 0 && at < 1024 && /charset=["']?utf-8/i.test(raw.subarray(0, 1024).toString()), `在第 ${at} 字节`)
t('以 <!doctype html> 开头', /^<!doctype html>/i.test(raw.subarray(0, 20).toString()))

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
t('双击打开就能用（出来了「从剪贴板贴入」）', (await pg.locator('.paste-btn').count()) === 1)
t('标题是「随手」', (await pg.title()).startsWith('随手'))

// 不只看它长出来了 —— 真的贴一次、复制一次
await pg.locator('[data-material]').fill('怎么在 Excel 里按两列同时去重？')
await pg.waitForTimeout(200)
await pg.locator('.copy').click(); await pg.waitForTimeout(200)
const c = await pg.evaluate(() => navigator.clipboard.readText()).catch(() => '')
t('离线版里一样能认、能复制', c.includes('回答下面这个问题') && c.includes('Excel'), c.slice(0, 20))
t('没有任何外部请求', outside.length === 0, outside.slice(0, 2).join(' '))
t('file:// 下没有报错（Service Worker 那套要完全空转）', errs.length === 0, errs.slice(0, 2).join(' | '))
await b.close()
process.exit(fail ? 1 : 0)
