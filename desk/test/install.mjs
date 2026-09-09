import pkg from 'playwright'
const { chromium, devices } = pkg
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const OUT = new globalThis.URL('./shots', import.meta.url).pathname
const b = await chromium.launch()
const t = (n, ok, note = '') => console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`)

// ---- 1. iPhone + 浏览器里：必须提示 ----
{
  const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
  await ctx.route(/fonts\.(googleapis|gstatic)\.com/, r => r.abort())
  const pg = await ctx.newPage()
  const errs = []; pg.on('pageerror', e => errs.push(e.message))
  await pg.goto(URL); await pg.waitForTimeout(700)
  const shown = await pg.evaluate(() => {
    const el = document.querySelector('.install')
    return el ? el.innerText.replace(/\n+/g, ' | ').slice(0, 130) : null
  })
  t('iPhone + 浏览器：提示出现', !!shown, shown || '没出现')
  await pg.screenshot({ path: OUT + '/install-notice.png' })

  // 关掉之后不再出现
  await pg.locator('.install button').click(); await pg.waitForTimeout(300)
  const gone = await pg.evaluate(() => !document.querySelector('.install'))
  await pg.reload(); await pg.waitForTimeout(600)
  const stillGone = await pg.evaluate(() => !document.querySelector('.install'))
  t('点「知道了」后消失', gone)
  t('刷新后不再出现', stillGone)
  t('无页面错误', errs.length === 0, errs.slice(0, 2).join(' | ') || '无')
  await ctx.close()
}

// ---- 2. 主屏 App（standalone）：不该提示 ----
{
  const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
  await ctx.route(/fonts\.(googleapis|gstatic)\.com/, r => r.abort())
  await ctx.addInitScript(() => {
    Object.defineProperty(navigator, 'standalone', { get: () => true, configurable: true })
  })
  const pg = await ctx.newPage()
  await pg.goto(URL); await pg.waitForTimeout(700)
  const shown = await pg.evaluate(() => !!document.querySelector('.install'))
  t('主屏 App 里不提示', !shown, shown ? '还在提示（错）' : '正确地不提示')
  await ctx.close()
}

// ---- 3. 桌面 / 安卓：不该提示（那边两个入口共享存储，没这个坑）----
{
  const ctx = await b.newContext({ viewport: { width: 430, height: 932 } })
  await ctx.route(/fonts\.(googleapis|gstatic)\.com/, r => r.abort())
  const pg = await ctx.newPage()
  await pg.goto(URL); await pg.waitForTimeout(700)
  const shown = await pg.evaluate(() => !!document.querySelector('.install'))
  t('非 iOS 不提示', !shown, shown ? '误报了' : '正确地不提示')
  await ctx.close()
}

// ---- 4. 设置页的浏览器警告 ----
{
  const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
  await ctx.route(/fonts\.(googleapis|gstatic)\.com/, r => r.abort())
  const pg = await ctx.newPage()
  await pg.goto(URL + '#/review'); await pg.reload(); await pg.waitForTimeout(700)
  await pg.locator('button[aria-label=设置]').click(); await pg.waitForTimeout(500)
  const warn = await pg.evaluate(() => {
    const ps = [...document.querySelectorAll('.sheet p')]
    const w = ps.find(p => p.innerText.includes('两份'))
    return w ? w.innerText.replace(/\n+/g, ' ').slice(0, 90) : null
  })
  t('设置页也说清了两份存储', !!warn, warn || '没说')
  await pg.screenshot({ path: OUT + '/install-settings.png', fullPage: true })
  await ctx.close()
}

await b.close()
