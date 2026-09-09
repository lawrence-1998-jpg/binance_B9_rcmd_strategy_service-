import pkg from 'playwright'
const { chromium, devices } = pkg
const FILE = new globalThis.URL('../../web/desk/deskside-standalone.html', import.meta.url).href
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
let fail = 0
// 单文件版是双击打开的桌面快捷方式：没有服务器，没有 Service Worker。
// update.ts 在这种环境下必须完全空转，不能报错
const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
const outside = []
await ctx.route('**/*', (route, req) => {
  if (!req.url().startsWith('file://')) { outside.push(req.url()); return route.abort() }
  return route.continue()
})
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', (e) => errs.push(e.message))
await pg.goto(FILE, { waitUntil: 'load' })
await pg.waitForTimeout(1200)
t('双击打开就能用（渲染出底部导航）', await pg.locator('.tabbar').count() > 0)
t('没有任何外部请求', outside.length === 0, outside.slice(0, 2).join(' '))
t('file:// 下没有报错', errs.length === 0, errs.slice(0, 2).join(' | '))
await pg.evaluate(async () => { await document.fonts.load('400 40px Caprasimo'); return document.fonts.ready })
t('字体也内嵌了（离线、无服务器也是完整的样子）', await pg.evaluate(() => document.fonts.check('400 40px Caprasimo')))
await b.close()
process.exit(fail ? 1 : 0)
