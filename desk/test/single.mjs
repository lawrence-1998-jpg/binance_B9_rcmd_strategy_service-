/**
 * 仓库里签着的那份离线单文件版（web/desk/deskside-standalone.html）：
 * 下载下来双击就能用，也是直接发给别人看的那一份。没有服务器；数据存在这台电脑的浏览器里。
 * 在设置里填了 Key 的话，双击打开的这一份也能直连 Claude（file:// 页面的跨域请求，接口是放行的）。
 *
 * 踩过的坑：单独发出去的 HTML 如果 <meta charset> 不在最前面，
 * iPhone 的 Safari 会按 GBK 猜，满屏乱码。所以专门盯着它。
 */
import pkg from 'playwright'
import { readFileSync } from 'node:fs'
import { mockAnthropic, presetKey } from './mock-anthropic.mjs'
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
t('没开 Claude：没有任何外部请求', outside.length === 0, outside.slice(0, 2).join(' '))
await pg.reload({ waitUntil: 'load' }); await pg.waitForTimeout(500)
t('刷新之后还在（file:// 下也存得住）', (await pg.locator('.list article.card').count()) === 1)
t('file:// 下没有报错（Service Worker 那套完全空转）', errs.length === 0, errs.slice(0, 2).join(' | '))
await ctx.close()

// 双击打开的这份 + 自己的 Key：SDK 是内联在这一个文件里的，照样能叫 Claude
const ctx2 = await b.newContext({ ...devices['iPhone 13'] })
const stray = []
await ctx2.route('**/*', (route, req) => {
  if (!req.url().startsWith('file://')) { stray.push(req.url()); return route.abort() }
  return route.continue()
})
await presetKey(ctx2)
const api = await mockAnthropic(ctx2)
const pg2 = await ctx2.newPage()
pg2.on('pageerror', (e) => errs.push(e.message))
await pg2.goto(PATH.href, { waitUntil: 'load' }); await pg2.waitForTimeout(500)
await pg2.locator('#capture').fill('王总：周五上午 10 点国贸见')
await pg2.locator('.take').click(); await pg2.waitForTimeout(1000)
t('单文件版填了 Key：一样交给 Claude 整理', (await pg2.locator('.card.open h3').innerText()) === '王总的会改到周五' && api.calls.some((c) => c.path === '/v1/messages'))
t('……除了 api.anthropic.com，没有别的外部请求', stray.length === 0, stray.slice(0, 2).join(' '))
t('……也没有报错', errs.length === 0, errs.slice(0, 2).join(' | '))
await b.close()
process.exit(fail ? 1 : 0)
